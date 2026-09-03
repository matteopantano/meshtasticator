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
│ (Gateway - e.g. Heltec)│      │ (Gen 2+, e.g. 1 Gen4)  │
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

1. **ESP32 Dev Board (Hub)**: Any standard ESP32-WROOM / ESP32-S3 / ESP32-C3 board ($4-$6). Runs `firmware/esp32-gateway/`.
2. **Meshtastic Gateway Node (Node B / RX)**: an **ESP32-based** LoRa node **with Wi-Fi** (e.g. Heltec V3, LilyGO T-Beam, T-Deck, Station G2). nRF52 boards (RAK4631, T-Echo) are **not** suitable: no Wi-Fi and no `mqtt.json_enabled` support.
3. **Meshtastic Transmitter Node (Node A / TX)**: Any Meshtastic node (handheld, phone-app connected, or stationary).
4. **Shelly Smart Relay**: a **Gen 2+ device** (Shelly Plus 1 / Plus 1PM, Pro, Gen3, **Shelly 1 Gen4** - the model validated in Phase 4). Gen 1 devices (Shelly 1 / 1PM / 2.5) are currently *not* controllable (see [`05_multi_node_iot_mqtt_pipeline.md`](05_multi_node_iot_mqtt_pipeline.md) §2C).
5. **USB cables** for provisioning the Meshtastic nodes and flashing the ESP32, and a laptop with the repo's `.venv` (`meshtastic` CLI) and PlatformIO.

---

## 3. Step 1: Flash & Configure the ESP32 Hub

The complete, maintained firmware is `firmware/esp32-gateway/src/main.cpp`;
see [`../firmware/esp32-gateway/README.md`](../firmware/esp32-gateway/README.md) for
the library list, the PlatformIO toolchain workarounds, the `.env` ➔ macro
mapping and the flashing steps. In short:

```bash
cp .env.example .env            # then edit WIFI_PASS, CONTROL_SECRET, LORA_REGION, GATEWAY_NODE_ID
cd firmware/esp32-gateway
pio run -t upload                # load_env.py injects .env values as compile-time defines
pio device monitor               # 115200 baud
```

Before flashing for production:

1. Set `GATEWAY_NODE_ID` in `.env` to the Node ID of your RX gateway node
   (`meshtastic --port /dev/ttyUSB0 --info` ➔ `Owner`/`My info` ➔ `!xxxxxxxx`
   ➔ write it as `0xxxxxxxxx`). It is used as `from` in the downlink ACK.
2. Set `LORA_REGION` to the same region you will set on the nodes
   (`EU_868`, `US`, ...). It becomes the `REGION` segment of the ACK topic.
3. Replace `ALLOWED_NODES[] = {"*"}` in `main.cpp` with the TX node IDs
   allowed to control the relay.

What the firmware does once running (all natively in C++ on the hub):

| Stage | Behaviour |
| :-- | :-- |
| Wi-Fi | SoftAP `WIFI_SSID` (default `ESP32-Hub`) at `192.168.4.1/24` |
| Broker | `TinyMqtt` MQTT 3.1.1 broker on `1883`, unauthenticated (SoftAP password is the access control) |
| Uplink | Subscribes to `msh/#`; for `type == "text"` envelopes extracts `payload.text` and parses the command JSON |
| Check 1/3 | Sender whitelist (`ALLOWED_NODES`, decimal `from` converted to `!xxxxxxxx`) |
| Check 2/3 | Per-sender monotonic `seq` (table of 16 nodes) |
| Check 3/3 | HMAC-SHA256 over `target:ACTION:seq`, first 8 hex chars, constant-time compare |
| Command | Publishes `<target>/command/switch:0` with `on` / `off` / `toggle` |
| Status | Subscribes `+/status/switch:0` and `shellies/+/relay/0`; matches the target against a pending-request table (30 s timeout) |
| ACK | Publishes `{"from":GATEWAY_NODE_ID,"to":<sender>,"type":"sendtext","payload":"{...ack...}"}` to `msh/<REGION>/2/json/mqtt/` |

Expected serial output on boot:

```
============================================================
  ESP32 Meshtastic <-> MQTT <-> Shelly Security Gateway
============================================================
[Wi-Fi] SoftAP 'ESP32-Hub' active. IP: 192.168.4.1
[MQTT] Embedded broker listening on port 1883.
[MQTT] Local client subscribed to Shelly status & mesh uplink topics.
[Ready] Listening for secure Meshtastic control packets...
```

(If you see `[WARNING] MESH_GATEWAY_NODE_ID is not configured`, fix `.env`
and rebuild - ACKs will not be routable otherwise.)

> [!NOTE]
> As of Phase 4 only the build, SoftAP and broker stages of this table have
> been confirmed on hardware. The security checks, command publish and the
> ACK downlink were validated through the *Python* `mqtt_bridge.py` using the
> ESP32 as broker, not through the firmware's own code path. Phase 5 in
> `ROADMAP.md` is the test plan that closes this gap.

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
2. Configures the LoRa frequency region (`LORA_REGION` from `.env`, or `--region`).
3. **For RX Gateway**: Connects to the ESP32 Hub Wi-Fi (`WIFI_SSID_RX="ESP32-Hub"`) and enables the native Meshtastic MQTT client pointing to the ESP32 (`mqtt.address` = `MQTT_HOST_REAL`, default `192.168.4.1`; `json_enabled true`, `encryption_enabled false`, `root msh`).
4. **For Remote TX**: Connects to your local Wi-Fi (`WIFI_SSID_TX="YourHomeWifi"`) so you can access its Web UI from your phone/browser on your home network, while leaving MQTT disabled (communication travels strictly over LoRa).

> [!WARNING]
> **What the provisioner does *not* do (yet)** - finish these by hand on the
> RX gateway node, otherwise nothing reaches the ESP32 and no ACK comes back:
>
> ```bash
> # 1. Uplink: publish channel-0 mesh packets to MQTT as JSON
> meshtastic --port /dev/ttyUSB0 --ch-index 0 --ch-set uplink_enabled true
>
> # 2. Downlink: a channel literally named "mqtt" with downlink enabled is
> #    what makes the node forward msh/<REGION>/2/json/mqtt/ envelopes to LoRa
> meshtastic --port /dev/ttyUSB0 --ch-add mqtt
> meshtastic --port /dev/ttyUSB0 --info          # find the new channel index
> meshtastic --port /dev/ttyUSB0 --ch-index <idx> --ch-set downlink_enabled true
>
> # 3. Check the result
> meshtastic --port /dev/ttyUSB0 --info | grep -A3 -i "mqtt\|channel"
> ```
>
> Also note: `mqtt.address` carries only the host; a non-default port must be
> written as `host:port`. Enabling Wi-Fi on an ESP32 node turns its Bluetooth
> off, so keep the USB cable connected while configuring.

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

## 5. Step 3: Configure the Shelly Smart Relay (Gen 2+ / Gen4)

1. Power the Shelly on mains or bench power (**mind the mains wiring** -
   use a qualified electrician for the 110-240 V AC terminals).
2. From your phone/laptop, join the Shelly's setup Wi-Fi (`ShellyXXXX-XXXXXX`).
3. Open a browser to **`http://192.168.33.1/`**.
4. **Settings ➔ Wi-Fi ➔ Wi-Fi 1 client**:
   * **SSID**: `ESP32-Hub` (your `WIFI_SSID`)
   * **Password**: your `WIFI_PASS`
5. **Settings ➔ MQTT**:
   * **Enable MQTT network**: `[x]`
   * **Server**: `192.168.4.1:1883` - no TLS, no user/password
   * **Custom prefix**: `shelly1-01` (**this exact string is the `target` in
     every signed command**; leave empty to use the device id instead)
   * **Enable 'MQTT Control'**: `[x]` (default on) - command topic `<prefix>/command/switch:0`
   * **Generic status update over MQTT**: `[x]` (**default off** - required for
     `<prefix>/status/switch:0`, i.e. for the ACK)
   * Save and reboot.
6. Verify from a laptop joined to `ESP32-Hub`:
   ```bash
   mosquitto_sub -h 192.168.4.1 -v -t 'shelly1-01/#'          # in one terminal
   mosquitto_pub -h 192.168.4.1 -t 'shelly1-01/command/switch:0' -m toggle
   ```
   The relay should click and `shelly1-01/status/switch:0 {"output":...}`
   should appear. If the click happens but no status line appears, step 5's
   "Generic status update" is still off.

---

## 6. Step 4: Transmitting Commands from Node A

From your phone app or transmitter CLI, send the signed JSON string over your encrypted Meshtastic channel:

```json
{"ver": 1, "target": "shelly1-01", "action": "ON", "seq": 1001, "sig": "ccb1d0e1"}
```

*(Signature for the default development secret `MeshShellySecret2026`;
compute your own with the one-liner in
[`../firmware/esp32-gateway/README.md`](../firmware/esp32-gateway/README.md) §7,
or let the CLI do it.)*

With the TX node attached over USB/Wi-Fi the repository's transmitter does
the signing, sequencing and ACK matching for you:

```bash
# USB-attached TX node: the meshtastic TCP API is not available over serial,
# so first expose it, e.g. by enabling Wi-Fi on the TX node (provisioner does
# this) and then:
python3 meshtasticd-config/send_control_cmd.py \
  --mesh-host <tx-node-ip> --mesh-port 4403 \
  --target shelly1-01 --action ON

# Negative tests (must be silently dropped by the gateway - no ACK):
python3 meshtasticd-config/send_control_cmd.py --mesh-host <tx-node-ip> --mesh-port 4403 --target shelly1-01 --action ON --replay
python3 meshtasticd-config/send_control_cmd.py --mesh-host <tx-node-ip> --mesh-port 4403 --target shelly1-01 --action ON --bad-sig
```

`send_control_cmd.py` uses `seq = int(time.time() % 1_000_000)` unless
`--seq` is given, so consecutive commands are normally monotonic. **Caveat**:
the modulo makes `seq` wrap roughly every 11.6 days; after a wrap the gateway
will reject new commands as replays until it is rebooted (or you pass an
explicit larger `--seq`). Fixing this is part of Phase 5. When sending by
hand from the phone app you must increment `seq` yourself - the gateway
remembers the last accepted `seq` **per sender** until it reboots (state is
in RAM only).

Expected ACK on the TX side (as a text message on the `mqtt` channel, or
printed by `send_control_cmd.py`):

```json
{"ver": 1, "device": "shelly1-01", "state": "ON", "ack_seq": 1001, "status": "OK"}
```

### Security Guarantees in Effect:
1. **LoRa Private PSK**: Protects the message in flight over the air.
2. **Sender whitelist**: Only Node IDs listed in `ALLOWED_NODES` (firmware) / `--allowed-nodes` (Python bridge) are processed.
3. **HMAC-SHA256 Signature**: Guarantees only someone with the shared secret can issue commands.
4. **Monotonic Sequence (`seq`)**: Prevents any eavesdropper from capturing and replaying previous packets.
5. **Air-Gapped & Offline**: Zero internet connection, zero external servers, runs entirely locally.

### Known limitations of the current design

- The **ACK is not signed**; a rogue node on the channel could forge a
  positive ACK. The relay state itself cannot be forged that way.
- Anti-replay state lives in **RAM**: after an ESP32 reboot the first command
  of any `seq` is accepted, so an attacker who captured an old packet could
  replay it once per gateway reboot. Using a Unix timestamp as `seq` (what
  `send_control_cmd.py` does) shrinks this window in practice; persisting
  the last `seq` to NVS is on the roadmap.
- The embedded broker has **no authentication**: anyone who knows the SoftAP
  password can publish to `<target>/command/switch:0` directly, bypassing
  the mesh and the HMAC. Choose a strong `WIFI_PASS`.
- `target` must **exactly** equal the Shelly's MQTT prefix; there is no
  discovery. A typo results in a silent no-op (command published to a topic
  nobody listens on, then a 30 s pending-request timeout).
