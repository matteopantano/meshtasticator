/**
 * ESP32 Standalone Meshtastic <-> MQTT <-> Shelly Security Gateway
 * ------------------------------------------------------------------
 * Replaces the Python `meshtasticd-config/mqtt_bridge.py` runtime for
 * physical (non-Docker) deployments. Runs entirely on a single ESP32:
 *
 *   1. Hosts its own Wi-Fi Access Point (SoftAP) so a physical Meshtastic
 *      gateway node (configured with its native `mqtt.*` client pointed at
 *      this ESP32) and a Shelly smart relay can both connect locally,
 *      with zero internet dependency.
 *   2. Runs an embedded MQTT 3.1.1 broker (TinyMqtt) on port 1883.
 *   3. Performs the exact same Zero-Trust security pipeline as
 *      `mqtt_bridge.py` natively, using `mbedtls/md.h` for HMAC-SHA256:
 *        Check 1/3 - Sender Node ID whitelist
 *        Check 2/3 - Anti-replay (monotonic `seq` per sender)
 *        Check 3/3 - HMAC-SHA256 signature verification
 *   4. Bridges validated commands to the Shelly's MQTT command topics, and
 *      republishes a signed ACK back onto the mesh once the Shelly reports
 *      its new relay state.
 *
 * See `firmware/esp32-gateway/README.md` for wiring, library dependencies,
 * flashing instructions, and how to connect a real Shelly relay.
 *
 * See `docs/05_multi_node_iot_mqtt_pipeline.md` for the full protocol/security spec that
 * this firmware implements (payload schema, HMAC vector, topics).
 */

#include <Arduino.h>
#include <WiFi.h>
#include <TinyMqtt.h>       // https://github.com/hsaturn/TinyMqtt
#include <ArduinoJson.h>    // https://arduinojson.org/
#include "mbedtls/md.h"     // Native ESP32 hardware-accelerated HMAC-SHA256

// ============================================================
// --- CONFIGURATION (Loaded dynamically from .env via load_env.py) ---
// ============================================================

#ifndef AP_SSID
#define AP_SSID "ESP32-Hub"
#endif

#ifndef AP_PASS
#define AP_PASS "YourSecureWifiPass123"
#endif

#ifndef CONTROL_SECRET
#define CONTROL_SECRET "MeshShellySecret2026"
#endif

#ifndef MESH_LORA_REGION
#define MESH_LORA_REGION "US"
#endif

#ifndef MESH_GATEWAY_NODE_ID
#define MESH_GATEWAY_NODE_ID 0x00000000
#endif

// Wi-Fi SoftAP credentials (injected from .env WIFI_SSID / WIFI_PASS).
static const char* AP_SSID_STR = AP_SSID;
static const char* AP_PASS_STR = AP_PASS;

// Static AP IP. 192.168.4.1 is the ESP32 SoftAP default and is assumed
// throughout docs/05_multi_node_iot_mqtt_pipeline.md / docs/07_physical_hardware_deployment.md.
static const IPAddress AP_IP(192, 168, 4, 1);
static const IPAddress AP_GATEWAY(192, 168, 4, 1);
static const IPAddress AP_SUBNET(255, 255, 255, 0);

static const uint16_t MQTT_PORT = 1883;

// Shared HMAC-SHA256 secret (injected from .env CONTROL_SECRET).
static const char* CONTROL_SECRET_STR = CONTROL_SECRET;

// Decimal Meshtastic Node ID of the physical gateway node.
static const uint32_t MESH_GATEWAY_NODE_ID_VAL = MESH_GATEWAY_NODE_ID;

// Meshtastic MQTT root topic and JSON "channel" name used for downlink
// (MQTT -> mesh) messages.
static const char* MESH_ROOT = "msh";
static const char* MESH_DOWNLINK_CHANNEL = "mqtt";
static const char* MESH_LORA_REGION_STR = MESH_LORA_REGION;

// Sender Node ID whitelist (Check 1/3). Use {"*"} to allow any sender
// (development/simulation only - NOT recommended for production). In
// production, list the exact `!xxxxxxxx` Node IDs allowed to issue
// control commands, e.g. {"!a1b2c3d4"}.
static const char* ALLOWED_NODES[] = {"*"};
static const size_t ALLOWED_NODES_COUNT = sizeof(ALLOWED_NODES) / sizeof(ALLOWED_NODES[0]);

static const size_t MAX_TRACKED_NODES = 16;   // anti-replay seq table size
static const size_t MAX_PENDING_REQUESTS = 8; // in-flight Shelly command ACKs
static const unsigned long PENDING_REQUEST_TIMEOUT_MS = 30000;

// ============================================================
// --- Embedded MQTT Broker + local clients ---
// ============================================================
// The broker accepts external TCP connections (the Meshtastic gateway
// node's native MQTT client, and the Shelly relay) on MQTT_PORT.
// `mqttClient` is a *local* (in-process) client used to publish commands
// to the Shelly and subscribe to both the Shelly's status topics and the
// Meshtastic mesh's uplink/downlink JSON topics, without an extra TCP hop.
MqttBroker broker(MQTT_PORT);
MqttClient mqttClient(&broker, "esp32-gateway");

// ============================================================
// --- HMAC-SHA256 Verification (mirrors mqtt_bridge.py::compute_hmac_sig) ---
// ============================================================
//
// Python reference (meshtasticd-config/mqtt_bridge.py):
//
//   def compute_hmac_sig(secret, target, action, seq):
//       canonical = f"{target}:{action.upper()}:{seq}"
//       digest = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"),
//                          hashlib.sha256).hexdigest()
//       return digest[:8]
//
// This produces byte-identical truncated-hex signatures given the same
// secret/target/action/seq inputs.

/** Computes the full 32-byte HMAC-SHA256 digest of `message` under `key`. */
static void hmacSha256(const char* key, const char* message, uint8_t out[32]) {
  const mbedtls_md_info_t* mdInfo = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mdInfo, 1 /* use HMAC */);
  mbedtls_md_hmac_starts(&ctx, (const unsigned char*)key, strlen(key));
  mbedtls_md_hmac_update(&ctx, (const unsigned char*)message, strlen(message));
  mbedtls_md_hmac_finish(&ctx, out);
  mbedtls_md_free(&ctx);
}

/** Formats the first 4 bytes (8 hex chars, lowercase) of a 32-byte digest. */
static String hexEncodeTruncated8(const uint8_t digest[32]) {
  char hex[9];
  for (int i = 0; i < 4; i++) {
    sprintf(hex + (i * 2), "%02x", digest[i]);
  }
  hex[8] = '\0';
  return String(hex);
}

/**
 * Computes the truncated 8-hex-char HMAC-SHA256 signature for
 * (target, action, seq), matching compute_hmac_sig() in mqtt_bridge.py.
 */
String computeHmacSig(const String& target, const String& action, long seq) {
  String actionUpper = action;
  actionUpper.toUpperCase();
  String canonical = target + ":" + actionUpper + ":" + String(seq);

  uint8_t digest[32];
  hmacSha256(CONTROL_SECRET, canonical.c_str(), digest);
  return hexEncodeTruncated8(digest);
}

/** Constant-time (length-fixed) comparison of two equal-length hex strings. */
bool constantTimeEquals(const String& a, const String& b) {
  if (a.length() != b.length()) return false;
  uint8_t diff = 0;
  for (size_t i = 0; i < a.length(); i++) {
    diff |= (uint8_t)a[i] ^ (uint8_t)b[i];
  }
  return diff == 0;
}

// ============================================================
// --- Check 1/3: Sender Whitelist ---
// ============================================================
bool isSenderAllowed(const String& fromId) {
  for (size_t i = 0; i < ALLOWED_NODES_COUNT; i++) {
    if (strcmp(ALLOWED_NODES[i], "*") == 0) return true;
    if (fromId.equals(ALLOWED_NODES[i])) return true;
  }
  return false;
}

// ============================================================
// --- Check 2/3: Anti-Replay (monotonic seq per sender Node ID) ---
// ============================================================
struct NodeSeqEntry {
  String nodeId;
  long lastSeenSeq = -1;
  bool used = false;
};
NodeSeqEntry nodeSeqTable[MAX_TRACKED_NODES];

long getLastSeenSeq(const String& fromId) {
  for (size_t i = 0; i < MAX_TRACKED_NODES; i++) {
    if (nodeSeqTable[i].used && nodeSeqTable[i].nodeId.equals(fromId)) {
      return nodeSeqTable[i].lastSeenSeq;
    }
  }
  return -1;
}

void setLastSeenSeq(const String& fromId, long seq) {
  for (size_t i = 0; i < MAX_TRACKED_NODES; i++) {
    if (nodeSeqTable[i].used && nodeSeqTable[i].nodeId.equals(fromId)) {
      nodeSeqTable[i].lastSeenSeq = seq;
      return;
    }
  }
  // Not tracked yet: insert into the first free slot (or overwrite slot 0
  // if the table is full - acceptable degraded behavior for a small
  // fixed-size embedded whitelist of trusted senders).
  for (size_t i = 0; i < MAX_TRACKED_NODES; i++) {
    if (!nodeSeqTable[i].used) {
      nodeSeqTable[i].used = true;
      nodeSeqTable[i].nodeId = fromId;
      nodeSeqTable[i].lastSeenSeq = seq;
      return;
    }
  }
  nodeSeqTable[0].nodeId = fromId;
  nodeSeqTable[0].lastSeenSeq = seq;
  nodeSeqTable[0].used = true;
}

// ============================================================
// --- Pending Requests (target -> {fromId, seq}) for ACK routing ---
// ============================================================
// Mirrors `self.pending_requests` in mqtt_bridge.py: records who asked to
// control which Shelly target and with what seq, so that once the Shelly
// reports its new state we know who to send the signed ACK back to.
struct PendingRequest {
  String target;
  String fromId;
  long seq = 0;
  unsigned long timestampMs = 0;
  bool used = false;
};
PendingRequest pendingRequests[MAX_PENDING_REQUESTS];

void setPendingRequest(const String& target, const String& fromId, long seq) {
  for (size_t i = 0; i < MAX_PENDING_REQUESTS; i++) {
    if (pendingRequests[i].used && pendingRequests[i].target.equals(target)) {
      pendingRequests[i].fromId = fromId;
      pendingRequests[i].seq = seq;
      pendingRequests[i].timestampMs = millis();
      return;
    }
  }
  for (size_t i = 0; i < MAX_PENDING_REQUESTS; i++) {
    if (!pendingRequests[i].used) {
      pendingRequests[i] = {target, fromId, seq, millis(), true};
      return;
    }
  }
  // Table full: overwrite the oldest slot.
  size_t oldestIdx = 0;
  unsigned long oldestTs = pendingRequests[0].timestampMs;
  for (size_t i = 1; i < MAX_PENDING_REQUESTS; i++) {
    if (pendingRequests[i].timestampMs < oldestTs) {
      oldestTs = pendingRequests[i].timestampMs;
      oldestIdx = i;
    }
  }
  pendingRequests[oldestIdx] = {target, fromId, seq, millis(), true};
}

bool popPendingRequest(const String& target, String& outFromId, long& outSeq) {
  for (size_t i = 0; i < MAX_PENDING_REQUESTS; i++) {
    if (pendingRequests[i].used && pendingRequests[i].target.equals(target)) {
      if (millis() - pendingRequests[i].timestampMs > PENDING_REQUEST_TIMEOUT_MS) {
        pendingRequests[i].used = false;
        return false; // stale, drop it
      }
      outFromId = pendingRequests[i].fromId;
      outSeq = pendingRequests[i].seq;
      pendingRequests[i].used = false;
      return true;
    }
  }
  return false;
}

// ============================================================
// --- Meshtastic Node ID helpers ---
// ============================================================
// The Meshtastic MQTT JSON envelope carries Node IDs as plain decimal
// integers (e.g. `2130636288`), while the whitelist / anti-replay tables
// here (and the `--allowed-nodes` list in mqtt_bridge.py) use the
// human-readable hex form (e.g. `!7efeee00`). Convert so both firmware
// and Python configs can share the same whitelist format.
String decimalNodeIdToHex(uint32_t nodeId) {
  char buf[10];
  snprintf(buf, sizeof(buf), "!%08x", nodeId);
  return String(buf);
}

// ============================================================
// --- Meshtastic Downlink ACK (mirrors mesh_iface.sendText(ack_json, ...)) ---
// ============================================================
// Publishes a signed status ACK back onto the mesh via the standard
// Meshtastic "JSON downlink" mechanism: any node with a channel literally
// named "mqtt" (downlink enabled) will forward a JSON envelope published
// to `msh/<REGION>/2/json/mqtt/` onto the mesh as a text message. See
// https://meshtastic.org/docs/software/integrations/mqtt/ and
// docs/05_multi_node_iot_mqtt_pipeline.md for the exact envelope fields.
void sendMeshAck(uint32_t toNodeIdDecimal, const String& target, const String& state, long seq) {
  JsonDocument ackDoc;
  ackDoc["ver"] = 1;
  ackDoc["device"] = target;
  ackDoc["state"] = state;
  ackDoc["ack_seq"] = seq;
  ackDoc["status"] = "OK";
  String ackJson;
  serializeJson(ackDoc, ackJson);

  JsonDocument envelope;
  envelope["from"] = MESH_GATEWAY_NODE_ID_VAL;
  envelope["to"] = toNodeIdDecimal;
  envelope["type"] = "sendtext";
  envelope["payload"] = ackJson;
  String envelopeJson;
  serializeJson(envelope, envelopeJson);

  String downlinkTopic = String(MESH_ROOT) + "/" + MESH_LORA_REGION + "/2/json/" + MESH_DOWNLINK_CHANNEL + "/";
  mqttClient.publish(downlinkTopic.c_str(), envelopeJson.c_str());
  Serial.printf("[Mesh ACK] -> %s : %s\n", downlinkTopic.c_str(), envelopeJson.c_str());
}

// ============================================================
// --- Security Pipeline: process a validated mesh command JSON string ---
// ============================================================
// Mirrors MeshtasticMQTTBridge.on_meshtastic_receive() in mqtt_bridge.py.
void processMeshCommand(uint32_t fromNodeIdDecimal, const String& commandText) {
  JsonDocument cmdDoc;
  DeserializationError err = deserializeJson(cmdDoc, commandText);
  if (err) {
    return; // Not a JSON command - ignore (could be a regular chat message)
  }

  if (!cmdDoc["target"].is<const char*>() || !cmdDoc["action"].is<const char*>() ||
      cmdDoc["seq"].isNull() || !cmdDoc["sig"].is<const char*>()) {
    Serial.println("[Validation FAILED] Missing required fields (target, action, seq, sig).");
    return;
  }

  String target = cmdDoc["target"].as<String>();
  String action = cmdDoc["action"].as<String>();
  action.toUpperCase();
  long seq = cmdDoc["seq"].as<long>();
  String sig = cmdDoc["sig"].as<String>();

  String fromId = decimalNodeIdToHex(fromNodeIdDecimal);

  // --- Check 1/3: Sender Whitelist ---
  if (!isSenderAllowed(fromId)) {
    Serial.printf("[Security DENIED] Sender %s is NOT in allowed whitelist.\n", fromId.c_str());
    return;
  }
  Serial.printf("[Check 1/3: Whitelist] Sender %s Authorized.\n", fromId.c_str());

  // --- Check 2/3: Anti-Replay (Monotonic Sequence) ---
  long lastSeq = getLastSeenSeq(fromId);
  if (seq <= lastSeq) {
    Serial.printf("[Security REJECTED: Replay Attack] seq=%ld <= last_seen_seq=%ld for %s\n",
                  seq, lastSeq, fromId.c_str());
    return;
  }
  Serial.printf("[Check 2/3: Anti-Replay] Sequence %ld > %ld Verified.\n", seq, lastSeq);

  // --- Check 3/3: HMAC-SHA256 Signature ---
  String expectedSig = computeHmacSig(target, action, seq);
  String sigLower = sig; sigLower.toLowerCase();
  String expectedLower = expectedSig; expectedLower.toLowerCase();
  if (!constantTimeEquals(sigLower, expectedLower)) {
    Serial.printf("[Security REJECTED: Bad Signature] Received sig='%s' != Expected '%s'\n",
                  sig.c_str(), expectedSig.c_str());
    return;
  }
  Serial.println("[Check 3/3: HMAC Signature] Cryptographic Signature Verified.");

  // All checks passed - update sequence number and register pending ACK.
  setLastSeenSeq(fromId, seq);
  setPendingRequest(target, String(fromNodeIdDecimal), seq);

  // Publish command to the Shelly's Gen 1 command topic.
  String shellyCmdTopic = "shellies/" + target + "/relay/0/command";
  String shellyPayload = action;
  shellyPayload.toLowerCase();
  mqttClient.publish(shellyCmdTopic.c_str(), shellyPayload.c_str());
  Serial.printf("[MQTT Publish] Topic: %s | Payload: %s\n", shellyCmdTopic.c_str(), shellyPayload.c_str());
}

// ============================================================
// --- Shelly Status Feedback -> Meshtastic ACK ---
// ============================================================
// Mirrors on_mqtt_message() in mqtt_bridge.py: parses Gen 1
// (`shellies/<id>/relay/0`) and Gen 2 (`<id>/status/switch:0`) status
// topics, matches against a pending request, and sends the signed ACK.
void handleShellyStatus(const String& topic, const String& payload) {
  String target;
  String state;

  if (topic.startsWith("shellies/") && topic.endsWith("/relay/0")) {
    // shellies/<device_id>/relay/0
    int firstSlash = topic.indexOf('/');
    int secondSlash = topic.indexOf('/', firstSlash + 1);
    target = topic.substring(firstSlash + 1, secondSlash);
    String upperPayload = payload;
    upperPayload.toUpperCase();
    state = upperPayload;
  } else if (topic.endsWith("/status/switch:0")) {
    // <device_id>/status/switch:0
    int firstSlash = topic.indexOf('/');
    target = topic.substring(0, firstSlash);
    JsonDocument statusDoc;
    if (deserializeJson(statusDoc, payload) == DeserializationError::Ok) {
      bool output = statusDoc["output"] | false;
      state = output ? "ON" : "OFF";
    } else {
      state = "UNKNOWN";
    }
  } else {
    return; // Not a recognized Shelly status topic
  }

  if (target.isEmpty() || state.isEmpty()) return;

  Serial.printf("[MQTT State Event] Target: %s | State: %s\n", target.c_str(), state.c_str());

  String fromIdStr;
  long seq;
  if (popPendingRequest(target, fromIdStr, seq)) {
    uint32_t toNodeIdDecimal = (uint32_t)fromIdStr.toInt();
    sendMeshAck(toNodeIdDecimal, target, state, seq);
  }
}

// ============================================================
// --- Local MQTT client callback: dispatches by topic ---
// ============================================================
// TinyMqtt CallBack signature:
//   void (*)(const MqttClient* source, const Topic& topic,
//            const char* payload, size_t payload_length)
void onMqttMessage(const MqttClient* /* source */, const Topic& topic, const char* payload, size_t length) {
  String topicStr(topic.c_str());
  String payloadStr;
  payloadStr.reserve(length);
  for (size_t i = 0; i < length; i++) payloadStr += payload[i];
  payloadStr.trim();

  Serial.printf("[MQTT RX] %s -> %s\n", topicStr.c_str(), payloadStr.c_str());

  // 1. Shelly status feedback (Gen 1 or Gen 2)
  if ((topicStr.startsWith("shellies/") && topicStr.endsWith("/relay/0")) ||
      topicStr.endsWith("/status/switch:0")) {
    handleShellyStatus(topicStr, payloadStr);
    return;
  }

  // 2. Meshtastic JSON uplink for a TEXT_MESSAGE_APP packet, e.g.
  //    msh/<REGION>/2/json/<CHANNEL>/<USERID>
  //    Envelope: {"id":..,"channel":0,"from":<decimal>,"payload":{"text":".."},
  //               "sender":"!xxxxxxxx","timestamp":..,"to":-1,"type":"text"}
  if (topicStr.startsWith(String(MESH_ROOT) + "/")) {
    JsonDocument envelope;
    if (deserializeJson(envelope, payloadStr) != DeserializationError::Ok) return;
    if (envelope["type"] != "text") return;

    uint32_t fromNodeIdDecimal = envelope["from"] | 0;
    String commandText;
    JsonVariant payloadField = envelope["payload"];
    if (payloadField.is<const char*>()) {
      commandText = payloadField.as<String>();
    } else if (payloadField.is<JsonObject>() && payloadField["text"].is<const char*>()) {
      commandText = payloadField["text"].as<String>();
    } else {
      return;
    }
    processMeshCommand(fromNodeIdDecimal, commandText);
  }
}

// ============================================================
// --- Arduino entry points ---
// ============================================================

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println();
  Serial.println("============================================================");
  Serial.println("  ESP32 Meshtastic <-> MQTT <-> Shelly Security Gateway");
  Serial.println("============================================================");

  if (MESH_GATEWAY_NODE_ID == 0x00000000) {
    Serial.println("[WARNING] MESH_GATEWAY_NODE_ID is not configured - ACKs will be");
    Serial.println("          sent with 'from': 0, which will not be routable back");
    Serial.println("          to the physical gateway node. Edit main.cpp before");
    Serial.println("          production use.");
  }

  // 1. Start Wi-Fi SoftAP
  WiFi.mode(WIFI_AP);
  WiFi.softAPConfig(AP_IP, AP_GATEWAY, AP_SUBNET);
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.printf("[Wi-Fi] SoftAP '%s' active. IP: %s\n", AP_SSID, WiFi.softAPIP().toString().c_str());

  // 2. Start the embedded MQTT broker (accepts the Meshtastic gateway
  //    node's native MQTT client and the Shelly relay as external clients)
  broker.begin();
  Serial.printf("[MQTT] Embedded broker listening on port %u.\n", MQTT_PORT);

  // 3. Configure the local in-process MQTT client used to publish Shelly
  //    commands / mesh ACKs and to receive Shelly status + mesh uplink
  //    messages.
  mqttClient.setCallback(onMqttMessage);
  mqttClient.subscribe("shellies/+/relay/0");     // Shelly Gen 1 status
  mqttClient.subscribe("+/status/switch:0");      // Shelly Gen 2 status
  mqttClient.subscribe(String(String(MESH_ROOT) + "/#").c_str()); // Mesh uplink (all channels/regions)
  Serial.println("[MQTT] Local client subscribed to Shelly status & mesh uplink topics.");
  Serial.println("[Ready] Listening for secure Meshtastic control packets...\n");
}

void loop() {
  broker.loop();     // Required for every broker instance
  mqttClient.loop();  // Required for every client instance
}

