# ESP32 Standalone Meshtastic ↔ MQTT ↔ Shelly Gateway Firmware

This is a self-contained Arduino/PlatformIO firmware that replaces the
Python `meshtasticd-config/mqtt_bridge.py` runtime for **physical,
non-Docker deployments**. A single ESP32 hosts its own Wi-Fi Access Point,
an embedded MQTT broker, and performs the same Zero-Trust HMAC-SHA256 +
anti-replay + whitelist security pipeline natively in C++.

See [`docs/05_multi_node_iot_mqtt_pipeline.md`](../../docs/05_multi_node_iot_mqtt_pipeline.md) at the
repository root for the full protocol/security specification this firmware
implements, and
[`docs/07_physical_hardware_deployment.md`](../../docs/07_physical_hardware_deployment.md) for the
end-to-end physical deployment (Meshtastic nodes + ESP32 + Shelly).

---

## 1. What this firmware does

1. **Networking (SoftAP mode)**: Configures the ESP32 as a Wi-Fi Access
   Point (SSID `ESP32-Hub`, default IP `192.168.4.1`) and starts an
   embedded MQTT 3.1.1 broker (`TinyMqtt`) on port `1883`. Both the physical
   Meshtastic gateway node (its native `mqtt.*` client) and a Shelly smart
   relay connect to this broker over Wi-Fi - no internet, no external
   broker, no computer required at runtime.
2. **Cryptographic validation (`mbedtls/md.h`)**: Implements HMAC-SHA256
   signature verification using the ESP32's native mbedTLS library, with
   the exact same signing vector as `compute_hmac_sig(secret, target,
   action, seq)` in `meshtasticd-config/mqtt_bridge.py`:
   `HMAC-SHA256(secret, f"{target}:{action.upper()}:{seq}")`, truncated to
   the first 8 hex characters.
3. **Anti-replay & whitelisting**: Tracks the last-seen monotonic `seq` per
   sender Node ID (only accepting strictly increasing values) and checks
   the sender against a compile-time whitelist array.
4. **MQTT/Mesh bridge**: Parses incoming signed command JSON (via
   `ArduinoJson`) from the Meshtastic JSON uplink topic, publishes the
   validated action to the Shelly's `shellies/<id>/relay/0/command` topic,
   listens for the Shelly's status feedback, and publishes a signed ACK
   back onto the mesh via the Meshtastic JSON downlink topic.

---

## 2. Hardware & Library Dependencies

- **Board**: Any standard ESP32 (ESP32-WROOM / ESP32-S3 / ESP32-C3, etc).
  The included `platformio.ini` targets the generic `esp32dev` board -
  change `board = esp32dev` to match your specific board if needed.
- **Libraries** (declared in `platformio.ini` / installable via Arduino
  Library Manager):
  - [`TinyMqtt`](https://github.com/hsaturn/TinyMqtt) by hsaturn - embedded
    MQTT broker + client.
  - [`ArduinoJson`](https://arduinojson.org/) by Benoit Blanchon (v7.x) -
    JSON parsing/serialization.
  - `mbedtls/md.h` - bundled with the ESP32 Arduino core, no separate
    install needed.

---

## 3. Flashing Instructions

### Option A: PlatformIO (recommended)

```bash
cd firmware/esp32-gateway
pio run                  # build
pio run -t upload        # flash over USB
pio device monitor       # serial monitor at 115200 baud
```

PlatformIO will automatically fetch `TinyMqtt` and `ArduinoJson` per the
`lib_deps` in `platformio.ini`.

### Option B: Arduino IDE

1. Copy `src/main.cpp` into a sketch folder named `esp32_gateway` and
   rename it to `esp32_gateway.ino` (Arduino IDE requires the `.ino` file
   name to match its containing folder).
2. **Tools ➔ Manage Libraries...** and install:
   - `TinyMqtt` (by hsaturn)
   - `ArduinoJson` (by Benoit Blanchon, v7.x)
3. **Tools ➔ Board** ➔ select your ESP32 board variant.
4. Click **Upload**.

---

## 4. Single Source of Truth Configuration (`.env`)

When building with PlatformIO, configuration parameters are **automatically loaded directly from the repository's root `.env` file** at compile time via `load_env.py`. This ensures your Wi-Fi credentials, HMAC secret, and LoRa region are maintained in **one place only**:

| `.env` Key | C++ Macro | Default / Fallback | Purpose |
| :--- | :--- | :--- | :--- |
| `WIFI_SSID` | `AP_SSID` | `"ESP32-Hub"` | SoftAP Wi-Fi SSID |
| `WIFI_PASS` | `AP_PASS` | `"YourSecureWifiPass123"` | SoftAP Wi-Fi Password |
| `CONTROL_SECRET` | `CONTROL_SECRET` | `"MeshShellySecret2026"` | Shared HMAC-SHA256 Secret |
| `LORA_REGION` | `MESH_LORA_REGION` | `"US"` | Meshtastic LoRa Region |
| `GATEWAY_NODE_ID` | `MESH_GATEWAY_NODE_ID` | `0x00000000` | Decimal/Hex Node ID of Gateway Node |

> [!TIP]
> You only need to set these once in `.env`. Both the Python scripts (`provision_nodes.py`, `mqtt_bridge.py`, `send_control_cmd.py`) and the ESP32 firmware build (`pio run`) will automatically use the exact same values!

> [!IMPORTANT]
> Never commit a real production `.env`, `CONTROL_SECRET`, or Wi-Fi password to a public repository. `.env` is ignored by git, while `.env.example` provides safe development defaults.

---

## 5. Connecting the Meshtastic Gateway Node

Configure the physical Meshtastic node that will bridge mesh traffic to
this ESP32 to join its SoftAP and use its native MQTT client:

```bash
meshtastic --set network.wifi_enabled true \
           --set network.wifi_ssid "ESP32-Hub" \
           --set network.wifi_psk "YourSecureWifiPass123"

meshtastic --set mqtt.enabled true \
           --set mqtt.address "192.168.4.1" \
           --set mqtt.json_enabled true \
           --set mqtt.encryption_enabled false \
           --set mqtt.root "msh"

# Enable uplink so mesh text messages reach this ESP32:
meshtastic --ch-index 0 --ch-set uplink_enabled true

# Create/enable a channel literally named "mqtt" with downlink enabled so
# this ESP32's ACKs can be delivered back onto the mesh:
meshtastic --ch-add mqtt
meshtastic --ch-index <new-channel-index> --ch-set downlink_enabled true
```

Or use the repository's automated provisioner (see
`meshtasticd-config/provision_nodes.py` and
[`docs/07_physical_hardware_deployment.md`](../../docs/07_physical_hardware_deployment.md) §4).

---

## 6. Connecting a Real Shelly

1. Power the Shelly on and join its setup Wi-Fi (`Shelly1-XXXXXX`).
2. Browse to `http://192.168.33.1/` and configure **Wi-Fi Mode - Client**
   with SSID `ESP32-Hub` / your `AP_PASS`.
3. Configure **MQTT** (Advanced ➔ Developer Settings on Gen 1, or
   Settings ➔ MQTT on Gen 2/Plus):
   - **Enable MQTT**: checked
   - **Server**: `192.168.4.1:1883`
   - **Custom MQTT Prefix / Device ID**: any short ID, e.g. `shelly1-01`
     (this is the `target` value used in signed commands)
   - Save and reboot.

Once connected, the Shelly will publish its state to
`shellies/<id>/relay/0` (Gen 1) or `<id>/status/switch:0` (Gen 2), and this
firmware will match its response to any pending mesh request and publish a
signed ACK back to the sender.

---

## 7. Testing without physical Meshtastic hardware

You do not need a physical Meshtastic node to validate this firmware's MQTT
broker and security logic - see **§6 "Hybrid Testing"** in
[`docs/05_multi_node_iot_mqtt_pipeline.md`](../../docs/05_multi_node_iot_mqtt_pipeline.md) for
instructions on pointing the repository's Docker-based simulated mesh
(`meshtasticd-rx`/`tx` + `sim-radio-bridge`) and `shelly_simulator.py` at
this ESP32's broker on `192.168.4.1:1883`.

You can also connect any generic MQTT client (e.g. `mosquitto_pub`/`_sub`,
MQTT Explorer) directly to `192.168.4.1:1883` to manually publish a signed
test command to the mesh uplink topic and observe the Serial monitor logs
for the three security checks, without any Meshtastic hardware at all:

```bash
# Compute a valid signature (must match CONTROL_SECRET in main.cpp):
python3 -c "
import hmac, hashlib
secret = 'MeshShellySecret2026'
canonical = 'shelly1-01:ON:1'
print(hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()[:8])
"

# Publish a fake mesh uplink JSON envelope (replace <sig> with the value above):
mosquitto_pub -h 192.168.4.1 -p 1883 \
  -t 'msh/US/2/json/LongFast/!a1b2c3d4' \
  -m '{"from":2712847316,"type":"text","payload":{"text":"{\"target\":\"shelly1-01\",\"action\":\"ON\",\"seq\":1,\"sig\":\"<sig>\"}"}}'
```
