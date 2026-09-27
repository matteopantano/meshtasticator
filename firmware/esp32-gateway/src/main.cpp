/**
 * ESP32 Simple MQTT Gateway - No Security
 * Just AP + MQTT broker + Shelly relay control
 */

#include <Arduino.h>
#include <WiFi.h>
#include <TinyMqtt.h>
#include <ArduinoJson.h>

// Configuration
#define AP_SSID "Hidden Network"
#define AP_PASS "PantanoViaMarconi567"
#define MQTT_PORT 1883

static const IPAddress AP_IP(192, 168, 4, 1);
static const IPAddress AP_GATEWAY(192, 168, 4, 1);
static const IPAddress AP_SUBNET(255, 255, 255, 0);

// MQTT broker and local client
MqttBroker broker(MQTT_PORT);
MqttClient mqttClient(&broker, "esp32-gateway");

// Simple callback - just log and publish to Shelly
void onMqttMessage(const MqttClient* /* source */, const Topic& topic, const char* payload, size_t length) {
  String topicStr(topic.c_str());
  String payloadStr;
  for (size_t i = 0; i < length; i++) payloadStr += payload[i];
  payloadStr.trim();

  Serial.printf("[MQTT RX] Topic: %s\n", topicStr.c_str());
  Serial.printf("[MQTT RX] Payload: %s\n", payloadStr.c_str());

  // If it's a test command, echo back
  if (topicStr == "test/cmd") {
    Serial.printf("  -> Received test command: %s\n", payloadStr.c_str());
    mqttClient.publish("test/response", "OK");
    return;
  }

  // Shelly listens directly on shelly1-01/command/switch:0, just log it
  if (topicStr == "shelly1-01/command/switch:0") {
    Serial.printf("  -> Shelly control command: %s\n", payloadStr.c_str());
    return;
  }

  // If Shelly reports state, log it
  if (topicStr == "shelly1-01/status/switch:0") {
    Serial.printf("  -> Shelly relay state: %s\n", payloadStr.c_str());
    return;
  }

  // If it's a mesh uplink from RX node, parse and forward to Shelly
  if (topicStr.startsWith("msh/")) {
    Serial.printf("  -> Mesh uplink received\n");
    
    // Parse envelope JSON
    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, payloadStr);
    if (err) {
      Serial.printf("  -> JSON parse failed: %s\n", err.c_str());
      return;
    }

    // Extract type and payload
    if (doc["type"] != "text") {
      Serial.printf("  -> Type is '%s', not 'text', ignoring\n", doc["type"].as<const char*>());
      return;
    }

    String commandText;
    if (doc["payload"]["text"].is<const char*>()) {
      commandText = doc["payload"]["text"].as<String>();
    } else {
      Serial.println("  -> No 'text' field in payload");
      return;
    }

    Serial.printf("  -> Command text: %s\n", commandText.c_str());

    // Parse command JSON: {"target":"shelly1-01","action":"ON"}
    StaticJsonDocument<256> cmdDoc;
    err = deserializeJson(cmdDoc, commandText);
    if (err) {
      Serial.printf("  -> Command JSON parse failed: %s\n", err.c_str());
      return;
    }

    String target = cmdDoc["target"] | "";
    String action = cmdDoc["action"] | "";
    
    if (target.isEmpty() || action.isEmpty()) {
      Serial.println("  -> Missing target or action");
      return;
    }

    Serial.printf("  -> Forwarding to %s: %s\n", target.c_str(), action.c_str());
    String shellyTopic = target + "/command/switch:0";
    String shellyCmd = action;
    shellyCmd.toLowerCase();
    mqttClient.publish(shellyTopic.c_str(), shellyCmd.c_str());
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println();
  Serial.println("================================================");
  Serial.println("  ESP32 Simple MQTT Gateway (No Security)");
  Serial.println("================================================");

  // Start WiFi AP
  Serial.println("[Setup] Starting WiFi AP...");
  WiFi.mode(WIFI_AP);
  WiFi.softAPConfig(AP_IP, AP_GATEWAY, AP_SUBNET);
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.printf("[WiFi] AP '%s' active at %s\n", AP_SSID, WiFi.softAPIP().toString().c_str());

  // Start MQTT broker
  Serial.println("[Setup] Starting MQTT broker...");
  broker.begin();
  Serial.printf("[MQTT] Broker listening on port %u\n", MQTT_PORT);

  // Configure local client
  Serial.println("[Setup] Configuring MQTT client...");
  mqttClient.setCallback(onMqttMessage);
  mqttClient.subscribe("test/cmd");
  mqttClient.subscribe("shelly1-01/command/switch:0");
  mqttClient.subscribe("shelly1-01/status/switch:0");
  mqttClient.subscribe("msh/#");  // Subscribe to mesh uplink from RX node
  Serial.println("[MQTT] Subscribed to test/cmd, shelly1-01/command/switch:0, shelly1-01/status/switch:0, msh/#");

  Serial.println();
  Serial.println("[Ready] Connect clients and publish to topics:");
  Serial.println("  - publish to 'test/cmd' with payload 'hello' -> test connectivity");
  Serial.println("  - publish to 'shelly1-01/command/switch:0' with payload 'on'/'off' -> control relay");
  Serial.println();
}

void loop() {
  broker.loop();
  mqttClient.loop();
  delay(10);
}
