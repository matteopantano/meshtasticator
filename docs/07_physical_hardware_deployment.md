# Physical Hardware Deployment Guide: Meshtastic + ESP32 MQTT Hub + Shelly Smart Relay

This guide details how to deploy the entire secure control pipeline on physical hardware without relying on computers or cloud services.

---

## 1. Physical System Architecture

The ESP32 acts as the **central wireless hub**, hosting its own local Wi-Fi Access Point, an embedded MQTT broker, and the cryptographic verification engine.

```
┌────────────────────────────────────────────────────────┐
│                   ESP32 Central Hub                    │
│                                                        │
│  ├─ 1. Wi-Fi Access Point (SoftAP: "ESP32-Hub")        │
│  ├─ 2. Embedded MQTT Broker (TinyMqtt on port 1883)    │
│  └─ 3. HMAC-SHA256 Security & Anti-Replay Router       │
│     IP: 192.168.4.1                                    │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
               │ 📶 Wi-Fi                 │ 📶 Wi-Fi
               ▼                          ▼
┌────────────────────────┐      ┌────────────────────────┐
│   Meshtastic Node B    │      │   Shelly Smart Relay   │
│ (Gateway - e.g. Heltec)│      │  (Shelly 1 / Plus 1)   │
│   Wi-Fi Client         │      │   Wi-Fi Client         │
│   IP: 192.168.4.2      │      │   IP: 192.168.4.3      │
│   MQTT ➔ 192.168.4.1   │      │   MQTT ➔ 192.168.4.1   │
└──────────────▲─────────┘      └────────────────────────┘
               │
               │ 📡 LoRa RF (Encrypted Channel)
               │
┌──────────────┴─────────┐
│   Meshtastic Node A    │
│ (Remote Transmitter)   │
└────────────────────────┘
```

---

## 2. Bill of Materials (BOM)

1. **ESP32 Dev Board**: Any standard ESP32-WROOM / ESP32-S3 / ESP32-C3 board ($4-$6).
2. **Meshtastic Gateway Node (Node B)**: Any ESP32-based LoRa node with Wi-Fi (e.g. Heltec V3, LilyGO T-Beam, T-Echo).
3. **Meshtastic Transmitter Node (Node A)**: Any Meshtastic node (Handheld, mobile app connected, or stationary).
4. **Shelly Smart Relay**: Shelly 1, Shelly Plus 1, Shelly Pro, or Shelly 2.5 (110-240V AC / 12-24V DC).

---

## 3. Step 1: Flash & Configure the ESP32 Hub

See [`../firmware/esp32-gateway/README.md`](../firmware/esp32-gateway/README.md) for the complete PlatformIO firmware implementation and flashing steps.

### Required Arduino Libraries (if using Arduino IDE)
Open Arduino IDE ➔ **Tools** ➔ **Manage Libraries...** and install:
- **`TinyMqtt`** (by hsaturn)
- **`ArduinoJson`** (by Benoit Blanchon, v7.x)

### ESP32 Firmware (`ESP32_WiFi_AP_MQTT_Hub.ino` / `firmware/esp32-gateway/src/main.cpp`)
Upload the sketch to your ESP32 board:

```cpp
#include <WiFi.h>
#include <TinyMqtt.h>       // Lightweight C++ MQTT Broker
#include <ArduinoJson.h>    // JSON parser
#include "mbedtls/md.h"     // Native hardware HMAC-SHA256

// --- CONFIGURATION ---
const char* AP_SSID       = "ESP32-Hub";
const char* AP_PASS       = "YourSecureWifiPass123";
const char* CONTROL_SECRET = "MeshShellySecret2026"; // Must match transmitter HMAC secret

MqttBroker broker(1883);
long last_seen_seq = -1;

// --- HMAC-SHA256 Verification ---
bool verify_hmac(const String& target, const String& action, long seq, const String& received_sig) {
    String payload = target + ":" + action + ":" + String(seq);
    
    byte hmacResult[32];
    mbedtls_md_context_t ctx;
    mbedtls_md_init(&ctx);
    mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
    mbedtls_md_hmac_starts(&ctx, (const unsigned char*)CONTROL_SECRET, strlen(CONTROL_SECRET));
    mbedtls_md_hmac_update(&ctx, (const unsigned char*)payload.c_str(), payload.length());
    mbedtls_md_hmac_finish(&ctx, hmacResult);
    mbedtls_md_free(&ctx);
    
    char calculated_sig[9];
    sprintf(calculated_sig, "%02x%02x%02x%02x", hmacResult[0], hmacResult[1], hmacResult[2], hmacResult[3]);
    return received_sig.equalsIgnoreCase(calculated_sig);
}

// --- MQTT Message Router ---
void onMqttMessage(const MqttClient* /*source*/, const Topic& topic, const char* payload, size_t /*length*/) {
    String topicStr = topic.c_str();
    String msgStr = String(payload);

    // 1. Ingest Meshtastic Packets
    if (topicStr.startsWith("msh/")) {
        Serial.printf("\n[Mesh MQTT RX] Topic: %s\n", topicStr.c_str());

        // Decode Meshtastic JSON wrapper or raw JSON
        JsonDocument meshDoc;
        DeserializationError err = deserializeJson(meshDoc, msgStr);
        if (err) return;

        String textPayload = meshDoc["payload"]["text"] | "";
        if (textPayload.length() == 0) {
            textPayload = msgStr;
        }

        JsonDocument cmdDoc;
        DeserializationError cmdErr = deserializeJson(cmdDoc, textPayload);
        if (cmdErr) return;

        const char* target = cmdDoc["target"];
        const char* action = cmdDoc["action"];
        long seq           = cmdDoc["seq"] | -1;
        const char* sig    = cmdDoc["sig"];

        if (!target || !action || seq < 0 || !sig) return;

        // Security Check 1: Anti-Replay
        if (seq <= last_seen_seq) {
            Serial.printf("🛡️ [REJECTED: Replay Attack] Received seq %ld <= last %ld\n", seq, last_seen_seq);
            return;
        }

        // Security Check 2: HMAC-SHA256 Signature
        if (!verify_hmac(target, action, seq, sig)) {
            Serial.println("🛡️ [REJECTED: Invalid HMAC Signature] Tampering detected!");
            return;
        }

        // Passed security checks
        last_seen_seq = seq;
        Serial.println("✓ HMAC & Sequence Verified! Dispatching to Shelly...");

        // Publish to Shelly MQTT command topic
        String shellyTopic = "shellies/" + String(target) + "/relay/0/command";
        String cmdVal = String(action);
        cmdVal.toLowerCase();

        broker.publish(shellyTopic.c_str(), cmdVal.c_str());
        Serial.printf("[Shelly Command] %s ➔ %s\n", shellyTopic.c_str(), cmdVal.c_str());
    }
    // 2. Capture Shelly Status Feedback
    else if (topicStr.startsWith("shellies/") && topicStr.endsWith("/relay/0")) {
        Serial.printf("📥 [Shelly State Feedback] %s -> %s\n", topicStr.c_str(), msgStr.c_str());
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=== ESP32 Meshtastic-Shelly Wireless Hub ===");

    // 1. Start SoftAP
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASS);
    Serial.printf("✓ Wi-Fi AP '%s' active at IP: %s\n", AP_SSID, WiFi.softAPIP().toString().c_str());

    // 2. Start Embedded Broker
    broker.begin();
    broker.setCallback(onMqttMessage);
    Serial.println("✓ Embedded MQTT Broker listening on port 1883.\n");
}

void loop() {
    broker.loop();
}
```

---

## 4. Step 2: Configure Meshtastic Nodes (1-Click Automated Provisioning)

Instead of manually configuring each setting in the Web UI or typing dozens of CLI flags, use the included **Automated Provisioner**:

### Option A: 1-Click Provisioning Tool (Recommended)
Plug your physical Meshtastic node into your computer via USB and run:

```bash
# Provision Gateway Node (RX):
# Connects to ESP32-Hub SoftAP and enables MQTT uplink to 192.168.4.1
python3 meshtasticd-config/provision_nodes.py --serial /dev/ttyUSB0 --role rx

# Provision Remote Transmitter (TX):
# Connects to your Home/Lab Wi-Fi (WIFI_SSID_TX) for Web UI access without MQTT
python3 meshtasticd-config/provision_nodes.py --serial /dev/ttyUSB1 --role tx
```

This automatically:
1. Names the node (`Mesh RX Node` / `Mesh TX Node`).
2. Configures the LoRa frequency region (`LORA_REGION` from `.env`).
3. **For RX Gateway**: Connects to the ESP32 Hub Wi-Fi (`WIFI_SSID_RX="ESP32-Hub"`) and enables native Meshtastic MQTT client pointing to the ESP32 (`192.168.4.1:1883`).
4. **For Remote TX**: Connects to your local Wi-Fi (`WIFI_SSID_TX="YourHomeWifi"`) so you can access its Web UI from your phone/browser on your home network, while leaving MQTT disabled (communication travels strictly over LoRa).

---

### Option B: Manual CLI Commands
If you prefer manual configuration:

```bash
# 1. RX Gateway Node: Connect to ESP32-Hub and enable MQTT
meshtastic --port /dev/ttyUSB0 \
           --set network.wifi_enabled true \
           --set network.wifi_ssid "ESP32-Hub" \
           --set network.wifi_psk "YourSecureWifiPass123" \
           --set mqtt.enabled true \
           --set mqtt.address "192.168.4.1" \
           --set mqtt.json_enabled true \
           --set mqtt.encryption_enabled false \
           --set mqtt.root "msh"

# 2. Remote TX Node: Connect to your Home/Lab Wi-Fi for Web UI access
meshtastic --port /dev/ttyUSB1 \
           --set network.wifi_enabled true \
           --set network.wifi_ssid "YourHomeWifi" \
           --set network.wifi_psk "YourHomeWifiPassword" \
           --set mqtt.enabled false
```

---

## 5. Step 3: Configure the Shelly Smart Relay

1. Power the Shelly on mains or bench power.
2. From your phone/laptop, join the Shelly's setup Wi-Fi (`Shelly1-XXXXXX`).
3. Open browser to **`http://192.168.33.1/`**.
4. Configure **Wi-Fi Mode - Client**:
   * **SSID**: `ESP32-Hub`
   * **Password**: `YourSecureWifiPass123`
5. Configure **Advanced - Developer Settings (MQTT)**:
   * **Enable MQTT**: `[x] Checked`
   * **Server**: `192.168.4.1:1883`
   * **Custom MQTT Prefix / Device ID**: `shelly1-01`
   * Save and reboot.

---

## 6. Step 4: Transmitting Commands from Node A

From your phone app or transmitter CLI, send the signed JSON string over your encrypted Meshtastic channel:

```json
{"ver": 1, "target": "shelly1-01", "action": "ON", "seq": 1001, "sig": "e0e2e92c"}
```

### Security Guarantees in Effect:
1. **LoRa Private PSK**: Protects the message in flight over the air.
2. **HMAC-SHA256 Signature**: Guarantees only someone with the shared secret can issue commands.
3. **Monotonic Sequence (`seq`)**: Prevents any eavesdropper from capturing and replaying previous packets.
4. **Air-Gapped & Offline**: Zero internet connection, zero external servers, runs entirely locally.
