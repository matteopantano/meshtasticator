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
   `ArduinoJson`) from the Meshtastic JSON uplink topic
   (`msh/<REGION>/2/json/<CHANNEL>/<USERID>`), publishes the validated
   action to the Shelly Gen 2+/Gen4 **MQTT control** topic
   `<target>/command/switch:0` (payload `on` / `off` / `toggle`), listens for
   the Shelly's status feedback on `+/status/switch:0` (Gen 2+) and
   `shellies/+/relay/0` (Gen 1), and publishes an ACK back onto the mesh via
   the Meshtastic JSON downlink topic `msh/<REGION>/2/json/mqtt/`.

> [!NOTE]
> **Verification status**: building, the SoftAP and the embedded broker
> were validated on real hardware in Phase 4 (a real Shelly 1 Gen4 and the
> Python tooling connected to it). The firmware's **own** security pipeline
> (steps 2-4 above) has so far only been reviewed against the Python
> reference implementation and has **not** yet been exercised end-to-end on
> hardware. That is the goal of ROADMAP Phase 5.

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

**Toolchain notes (from the Phase 4 bring-up)** - `platformio.ini` /
`load_env.py` contain three deliberate workarounds; keep them if you touch
the build:

| Setting | Why |
| :-- | :-- |
| `lib_deps = https://github.com/hsaturn/TinyMqtt.git` | The registry version `hsaturn/TinyMqtt @ ^1.1.4` did not resolve reliably; the Git source builds. |
| `build_unflags = -std=gnu++11` + `build_flags = -std=gnu++17` | TinyMqtt's dependency `TinyConsole` needs modern C++. |
| `env.Append(CXXFLAGS=["-include", "utility"])` in `load_env.py` | `TinyConsole` uses `std::exchange` without including `<utility>` on some toolchains. Applied to C++ units only (adding it to `CCFLAGS` breaks the C compilation of the ESP-IDF sources). |

The build was verified with PlatformIO on **Windows**; a Linux/macOS build
has not been re-confirmed since these changes.

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
| `LORA_REGION` | `MESH_LORA_REGION` | `"US"` (`.env.example` ships `EU_868`) | Meshtastic LoRa Region - **must equal the region string in the node's MQTT topics** (`msh/EU_868/...`), since the firmware builds the downlink ACK topic from it |
| `GATEWAY_NODE_ID` | `MESH_GATEWAY_NODE_ID` | `0x00000000` | Decimal/Hex Node ID of the physical RX gateway node (`from` of downlink ACKs) |

> [!NOTE]
> `load_env.py` reads `.env` with a minimal parser (no `export`, no
> multi-line values). Quotes are stripped. Re-run `pio run` after every `.env`
> change - the values are baked in at compile time, not read at runtime.

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

(Add `--port /dev/ttyUSB0` or `--host <node-ip>` to each command.)

The repository's automated provisioner
(`meshtasticd-config/provision_nodes.py --serial /dev/ttyUSB0 --role rx`)
performs the first two blocks (Wi-Fi + `mqtt.*`) for you, but **not** the
channel `uplink_enabled` / `mqtt` downlink channel steps - run those
manually. See
[`docs/07_physical_hardware_deployment.md`](../../docs/07_physical_hardware_deployment.md) §4.

Requirements and gotchas for the gateway node:

- It must be an **ESP32-based** Meshtastic board with Wi-Fi (Heltec V3,
  LilyGO T-Beam, T-Deck, Station G2 ...). **nRF52 boards** (RAK4631, T-Echo,
  ...) have no Wi-Fi and the Meshtastic firmware does **not** support
  `mqtt.json_enabled` on that platform.
- Enabling Wi-Fi on an ESP32 node **disables Bluetooth**; you will need the
  USB serial or the node's IP (Web/TCP API) to keep configuring it.
- The node's `lora.region` determines the `REGION` segment of every MQTT
  topic (`msh/EU_868/2/json/...`). It must match `LORA_REGION` in `.env`
  (and therefore `MESH_LORA_REGION` in the firmware) or the downlink ACK
  will be published on a topic the node never subscribes to.
- `mqtt.encryption_enabled false` is required for the JSON uplink to contain
  clear-text `payload.text`; the LoRa link itself is still encrypted with
  the channel PSK.
- The TX node's channel and the RX node's channel `0` must share the same
  name/PSK, and the `mqtt` channel on the RX node must be present on the
  TX node too (same name + PSK) for the ACK to be decryptable there.

---

## 6. Connecting a Real Shelly

1. Power the Shelly on and join its setup Wi-Fi (`Shelly1-XXXXXX`).
2. Browse to `http://192.168.33.1/` and configure **Wi-Fi Mode - Client**
   with SSID `ESP32-Hub` / your `AP_PASS`.
3. Configure **MQTT** (Settings ➔ MQTT on Gen 2 / Plus / Gen3 / Gen4):
   - **Enable MQTT network**: checked
   - **Server**: `192.168.4.1:1883` (no TLS, no username/password - the
     embedded `TinyMqtt` broker is unauthenticated; the SoftAP password is
     the only access control)
   - **Custom prefix**: any short ID, e.g. `shelly1-01`. **This is the
     `target` value used in signed commands** and must match exactly. If you
     leave it empty, the prefix is the device id (e.g.
     `shelly1g4-a1b2c3d4e5f6`) and you must use *that* as `target`.
   - **Enable 'MQTT Control'**: checked (default on) - required for the
     `<prefix>/command/switch:0` command topic this firmware publishes.
   - **Generic status update over MQTT**: **checked** (default **off**!) -
     required so the device publishes `<prefix>/status/switch:0`, which is
     what triggers the ACK back to the mesh. Without it the relay toggles
     but no ACK is ever sent.
   - *RPC status notifications over MQTT* can stay at its default; it is not
     used by this firmware.
   - Save and reboot.

Once connected, the Shelly will publish its state to
`<prefix>/status/switch:0` (Gen 2+) and this firmware will match it to any
pending mesh request and publish an ACK back to the sender.

> [!WARNING]
> **Gen 1 Shelly devices** (Shelly 1 / 1PM / 2.5, `shellies/...` topics)
> are currently **not controllable** by this firmware or by
> `mqtt_bridge.py`: since Phase 4 the command is published only to the Gen 2+
> `<prefix>/command/switch:0` topic. Their Gen 1 status topic
> `shellies/<id>/relay/0` is still parsed. A topic-profile switch is on the
> roadmap.

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
# Compute a valid signature (must match CONTROL_SECRET in .env / main.cpp):
python3 -c "
import hmac, hashlib
secret = 'MeshShellySecret2026'
canonical = 'shelly1-01:ON:1'
print(hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()[:8])
"
# -> 5fcfbf0c  (for the default development secret)

# Publish a fake mesh uplink JSON envelope (replace <sig> with the value above).
# The region segment must match MESH_LORA_REGION only for the *downlink* ACK
# topic; the firmware subscribes to msh/# so any region works for uplink.
mosquitto_pub -h 192.168.4.1 -p 1883 \
  -t 'msh/EU_868/2/json/LongFast/!a1b2c3d4' \
  -m '{"from":2712847316,"type":"text","payload":{"text":"{\"target\":\"shelly1-01\",\"action\":\"ON\",\"seq\":1,\"sig\":\"<sig>\"}"}}'

# In a second terminal, watch everything the ESP32 publishes back:
mosquitto_sub -h 192.168.4.1 -p 1883 -v -t 'shelly1-01/#' -t 'msh/#'
```

Expected on the serial monitor:

```
[MQTT RX] msh/EU_868/2/json/LongFast/!a1b2c3d4 -> {...}
[Check 1/3: Whitelist] Sender !a1b2c3d4 Authorized.
[Check 2/3: Anti-Replay] Sequence 1 > -1 Verified.
[Check 3/3: HMAC Signature] Cryptographic Signature Verified.
[MQTT Publish] Topic: shelly1-01/command/switch:0 | Payload: on
[MQTT RX] shelly1-01/status/switch:0 -> {"id":0,"source":"MQTT","output":true,...}
[MQTT State Event] Target: shelly1-01 | State: ON
[Mesh ACK] -> msh/EU_868/2/json/mqtt/ : {"from":<GATEWAY_NODE_ID>,"to":2712847316,"type":"sendtext","payload":"{\"ver\":1,\"device\":\"shelly1-01\",\"state\":\"ON\",\"ack_seq\":1,\"status\":\"OK\"}"}
```

Re-publishing the same envelope must produce `[Security REJECTED: Replay
Attack]`; changing one hex digit of `sig` must produce `[Security REJECTED:
Bad Signature]`. This `mosquitto_pub` procedure is the basis of the Phase 5
firmware-verification checklist in `ROADMAP.md`.

### Whitelist and Gateway Node ID (production)

- `ALLOWED_NODES[]` in `src/main.cpp` defaults to `{"*"}` (accept any
  sender). For production change it to the exact hex Node IDs of the TX
  nodes allowed to issue commands, e.g. `{"!a1b2c3d4", "!deadbeef"}`, and
  rebuild. The uplink envelope's decimal `from` is converted to this form
  by `decimalNodeIdToHex()`.
- `GATEWAY_NODE_ID` in `.env` (hex `0x...` or decimal) must be set to the
  Node ID of the **physical RX gateway node**; it is placed in the `from`
  field of the downlink ACK envelope. With the default `0x00000000` the
  firmware prints a warning at boot and the Meshtastic node will most likely
  drop or misattribute the downlink message.
