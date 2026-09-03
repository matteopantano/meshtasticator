# Multi-Node Docker Testbed & IoT/MQTT Pipeline

This document outlines the architecture, data structures, and security specifications for using a **Meshtastic LoRa mesh network** to wirelessly control **Shelly smart relays** over MQTT via a Gateway node.

---

## 1. System Architecture

```mermaid
graph TD
    subgraph MeshNetwork ["Meshtastic LoRa Mesh"]
        NodeA["Node TX (Remote Transmitter)\n(Heltec / T-Beam / Phone App / Web UI)"]
        NodeB["Node RX (Gateway / Receiver)\n(ESP32 / Linux Portduino)"]
        NodeA <--> |LoRa RF / Private Channel| NodeB
    end

    subgraph LocalGateway ["Local Gateway Subsystem"]
        NodeB <--> |TCP API / Serial / Wi-Fi| Bridge["MQTT Bridge / Embedded Firmware\n(ESP32 SoftAP Hub)"]
        Broker["MQTT Broker (Mosquitto / TinyMqtt)\n(Port 1883)"]
        Bridge <--> Broker
    end

    subgraph TargetDevices ["Shelly Smart Relays (Wi-Fi)"]
        Shelly1["Shelly Gen 2+ (Plus 1 / 1 Gen4)\n(switch:0)"]
        Broker <--> |MQTT Subscribe / Publish| Shelly1
    end
```

---

## 2. Technical Requirements & Security Design

### A. Data Structure (Payload Specification)
To keep LoRa payload sizes minimal (< 200 bytes) while enabling full validation and feedback, use compact JSON structures over a private channel (e.g. `SERIAL_APP` or `TEXT_MESSAGE_APP`).

#### Command Payload (Node TX ➔ Node RX)
```json
{
  "ver": 1,
  "target": "shelly1-sim01",
  "action": "ON",
  "seq": 1042,
  "sig": "5e6a85c2"
}
```
* **`ver`**: Protocol version integer (informational; not currently validated).
* **`target`**: Identifier of the target device connected to the MQTT broker.
  **Must exactly match the Shelly's MQTT topic prefix** (Gen 2+: *Settings ➔
  MQTT ➔ "Custom prefix"*, defaults to the device id such as
  `shelly1g4-a1b2c3d4e5f6`), since it is used verbatim to build the command
  topic `<target>/command/switch:0`.
* **`action`**: `ON`, `OFF`, or `TOGGLE` (case-insensitive on the wire; upper-cased before signing).
* **`seq`**: Monotonic counter / timestamp for anti-replay verification.
* **`sig`**: Truncated hex HMAC signature computed over `target:ACTION:seq` with a shared secret key (see §2B).

*(The sample `sig` above is computed with the default development secret
`MeshShellySecret2026`; regenerate it if you change `CONTROL_SECRET`.)*

#### Response / Status ACK Payload (Node RX ➔ Node TX)
```json
{
  "ver": 1,
  "device": "shelly1-sim01",
  "state": "ON",
  "ack_seq": 1042,
  "status": "OK"
}
```
* **`device`**: the `target` the ACK refers to (field name is `device`, as
  emitted by both `mqtt_bridge.py` and the ESP32 firmware and consumed by
  `send_control_cmd.py`).
* **`state`**: `ON` / `OFF` as reported by the Shelly's status topic
  (`UNKNOWN` if the Gen 2+ status JSON could not be parsed).
* **`ack_seq`**: echoes the `seq` of the command being acknowledged, which
  is how `send_control_cmd.py` matches the ACK to its request.
* The ACK is **not** HMAC-signed today: its authenticity relies on the
  LoRa channel PSK. Adding a signature is tracked in the roadmap.

---

### B. Zero-Trust Security & Verification Pipeline

The gateway (`meshtasticd-config/mqtt_bridge.py`, or the standalone
`firmware/esp32-gateway/` firmware) treats **every** incoming mesh packet as
untrusted until it passes all three checks below, in order. Any failure
causes the packet to be **silently dropped** (no ACK, no error reply) so
that an attacker cannot use error responses to fingerprint the validation
logic.

1. **Sender Node ID Whitelist** (`Check 1/3`):
   - The gateway verifies the packet's `from` (Node ID, e.g. `!a1b2c3d4`)
     against a configured `allowed_nodes` list (`--allowed-nodes` CLI flag in
     `mqtt_bridge.py`, default `["*"]` for simulation/dev; a hardcoded C
     array in the ESP32 firmware for production).
   - Packets from unlisted senders are rejected before any further
     processing (cheap fail-fast rejection).
2. **Anti-Replay Protection (Monotonic Sequence Tracking)** (`Check 2/3`):
   - The gateway keeps an in-memory map of `last_seen_seq` per sender Node
     ID (`self.last_seen_seq[from_id]` in Python; a per-node array in the
     firmware).
   - A command is only accepted if `seq > last_seen_seq[from_id]`; otherwise
     it is rejected as a **replay attack** (a captured-and-resent packet, or
     an out-of-order/duplicate delivery).
   - Callers are expected to use a monotonically increasing value for
     `seq` (a simple incrementing counter or a Unix timestamp both work;
     `send_control_cmd.py --seq <int>` lets you override it explicitly for
     testing, and also exposes `--replay` / `--bad-sig` flags that
     deliberately violate checks 2 and 3 to verify the gateway rejects
     them).
3. **HMAC-SHA256 Signature (Cryptographic Authorization)** (`Check 3/3`):
   - Node TX and the Gateway share a secret key `CONTROL_SECRET` (from
     `.env` / `CONTROL_SECRET` env var, **never committed to git**).
   - The canonical signing string is built as
     `f"{target}:{action.upper()}:{seq}"` (colon-delimited, action
     upper-cased, `seq` as its decimal string representation).
   - The signature is the first **8 hex characters** (4 bytes) of
     `HMAC-SHA256(CONTROL_SECRET, canonical_string)`:
     ```python
     def compute_hmac_sig(secret: str, target: str, action: str, seq: int) -> str:
         canonical = f"{target}:{action.upper()}:{seq}"
         digest = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
         return digest[:8]
     ```
     (verbatim from `meshtasticd-config/mqtt_bridge.py` /
     `meshtasticd-config/send_control_cmd.py`).
   - The gateway recomputes the expected signature and compares it to the
     received `sig` using a **constant-time comparison**
     (`hmac.compare_digest`, case-insensitive) to prevent timing-attack
     signature recovery. Any mismatch (including tampered `target`,
     `action`, or `seq`) is rejected.
   - Only after the signature check passes does `last_seen_seq[from_id]`
     get updated to the new `seq` - so a rejected/tampered packet can never
     advance a victim's sequence counter and invalidate their next
     legitimate command.
   - The ESP32 firmware performs the equivalent computation natively via
     `mbedtls/md.h`'s `mbedtls_md_hmac_*` API (see
     [`firmware/esp32-gateway/src/main.cpp`](../firmware/esp32-gateway/src/main.cpp)), producing byte-identical
     results to the Python implementation for the same secret/inputs.

Only once all three checks pass does the gateway publish the command to the
Shelly's MQTT topic and register a `pending_requests[target]` entry so the
subsequent Shelly state-change event can be matched back to the original
sender/seq for the ACK.

---

### C. Shelly Smart Relay MQTT Integration

#### Shelly Standard Topics (reference)
* **Shelly Gen 1 (e.g. Shelly 1/1PM, 2.5)**:
  * Command Topic: `shellies/<device_id>/relay/0/command` (Payload: `on` / `off` / `toggle`)
  * State Topic: `shellies/<device_id>/relay/0` (Payload: `on` or `off`)
* **Shelly Gen 2+ (Plus / Pro / Gen3 / Gen4 - RPC protocol)**:
  * RPC Topic: `<prefix>/rpc` (Payload: `{"id":1,"src":"meshtastic","method":"Switch.Set","params":{"id":0,"on":true}}`)
  * **MQTT control Topic: `<prefix>/command/switch:0`** (Payload: `on` / `off` / `toggle` / `status_update`) - requires the *"Enable 'MQTT Control'"* setting (`enable_control`, default **on**).
  * Status Topic: `<prefix>/status/switch:0` (Payload: `{"id":0,"source":"MQTT","output":true,...}`) - requires *"Generic status update over MQTT"* (`status_ntf`, default **off** - must be enabled!).

  `<prefix>` is the device's `topic_prefix` (defaults to its device id).

#### What the gateway actually publishes / subscribes (since Phase 4)

| Direction | Topic | Payload | Implemented in |
| :-- | :-- | :-- | :-- |
| Gateway ➔ Shelly (command) | `<target>/command/switch:0` | `on` / `off` / `toggle` | `mqtt_bridge.py` `on_meshtastic_receive()`, `main.cpp` `processMeshCommand()` |
| Shelly ➔ Gateway (status, Gen 2+) | `+/status/switch:0` | `{"output":true,...}` ➔ state `ON`/`OFF` | `on_mqtt_message()` / `handleShellyStatus()` |
| Shelly ➔ Gateway (status, Gen 1) | `shellies/+/relay/0` | `on` / `off` | same |

> [!IMPORTANT]
> Phase 4 (real Shelly 1 Gen4 bring-up) switched the **outbound command
> topic** from the Gen 1 `shellies/<id>/relay/0/command` to the Gen 2+
> `<target>/command/switch:0` format in **both** `mqtt_bridge.py` and the
> ESP32 firmware. Consequences:
> - A **Gen 1** Shelly is currently *not* controllable through the gateway
>   (only its status topic is still understood). A topic-profile flag
>   (`gen1` / `gen2` / `auto`) is on the roadmap.
> - The ACK path depends on the Shelly publishing `<prefix>/status/switch:0`,
>   which on Gen 2+ devices is **off by default** (`status_ntf`). Enable
>   *"Generic status update over MQTT"* in the Shelly web UI, otherwise the
>   relay toggles but the mesh never receives an ACK.
> - `shelly_simulator.py` subscribes to all three command formats, so the
>   simulated flow keeps working regardless of which topic the gateway uses.

---

## 3. End-to-End Simulation Quickstart

> [!IMPORTANT]
> The Docker multi-container stack must be started **before** running `provision_nodes.py`, because the provisioner configures the live daemons over ports 4404 and 4406.

### Option A: Fully Simulated Multi-Node Stack (Docker)

```bash
# 1. Setup local environment and start Docker containers
cp .env.example .env
docker compose up -d

# 2. Auto-provision both simulated nodes (RX on port 4404, TX on port 4406)
python3 meshtasticd-config/provision_nodes.py --sim

# 3. In separate terminal tabs, start the Shelly simulator & MQTT bridge:
# Terminal 1: Run Shelly smart relay emulator
python3 meshtasticd-config/shelly_simulator.py --id shelly1-sim01

# Terminal 2: Run security gateway on the Gateway RX node
python3 meshtasticd-config/mqtt_bridge.py --mesh-port 4404
```

#### 4. Transmit Commands & Observe the Real-Time ACK

**Method 1: Automated Transmitter CLI (Recommended)**
Automatically computes HMAC-SHA256 signature and sequence counter:
```bash
# Turn ON:
python3 meshtasticd-config/send_control_cmd.py --mesh-port 4406 --target shelly1-sim01 --action ON

# Turn OFF:
python3 meshtasticd-config/send_control_cmd.py --mesh-port 4406 --target shelly1-sim01 --action OFF

# TOGGLE:
python3 meshtasticd-config/send_control_cmd.py --mesh-port 4406 --target shelly1-sim01 --action TOGGLE
```

**Method 2: Manual Payload from the Web UI Chat (`http://localhost:8081`)**
To test directly from the browser, paste one of the following JSON payloads into the **Remote TX** Web UI chat box:
```json
// Action: ON (seq: 1)
{"ver": 1, "target": "shelly1-sim01", "action": "ON", "seq": 1, "sig": "4605904e"}

// Action: OFF (seq: 2)
{"ver": 1, "target": "shelly1-sim01", "action": "OFF", "seq": 2, "sig": "65f04183"}

// Action: TOGGLE (seq: 3)
{"ver": 1, "target": "shelly1-sim01", "action": "TOGGLE", "seq": 3, "sig": "dade3a52"}
```
*(Note: Because of anti-replay protection, each subsequent command requires an incremented `seq` value and its corresponding HMAC signature computed from `CONTROL_SECRET`)*

---

### Option B: Physical Hardware Provisioning (USB)

```bash
# Auto-provision the physical RX gateway node via USB (joins the ESP32-Hub
# SoftAP and points its native MQTT client at 192.168.4.1):
python3 meshtasticd-config/provision_nodes.py --serial /dev/ttyUSB0 --role rx

# Auto-provision the physical TX node (joins your home Wi-Fi, MQTT disabled):
python3 meshtasticd-config/provision_nodes.py --serial /dev/ttyUSB1 --role tx
```

`provision_nodes.py` sets owner names, `lora.region`, Wi-Fi and the
`mqtt.*` module, but it does **not** (yet) enable `uplink_enabled` /
`downlink_enabled` on channels nor create the `mqtt` downlink channel - do
that manually as described in
[`../firmware/esp32-gateway/README.md`](../firmware/esp32-gateway/README.md) §5,
or follow the full walkthrough in
[`07_physical_hardware_deployment.md`](07_physical_hardware_deployment.md).

---

## 4. Current Status & Verification Table

| Component | Status | Verification Details |
| :--- | :--- | :--- |
| **HMAC-SHA256 Auth** | ✅ Verified | Truncated hex signature verified against shared secret |
| **Anti-Replay Counter** | ✅ Verified | Reused/stale sequence numbers rejected |
| **Shelly Simulator** | ✅ Verified | Toggles relay state on Gen 1, Gen 2 RPC **and** Gen 2+ `command/switch:0` topics; emits Gen 1 / Gen 2 status topics on `1883` |
| **Mesh Status ACK (Python bridge)** | ✅ Verified | Bidirectional acknowledgment returned over mesh via `mesh_iface.sendText()` |
| **Automated Provisioning**| ✅ Verified | Reads `.env`, sets names, LoRa region, and MQTT module |
| **Simulated RF Cross-Routing** | ✅ Verified | `meshtasticd-config/sim_rf_bridge.py` cross-relays `SIMULATOR_APP` (portnum 69) packets between `ws-proxy-rx:4404` and `ws-proxy-tx:4404` mux ports, running as the `sim-radio-bridge` Docker service |
| **Real Shelly 1 Gen4 actuation** | ✅ Verified (Phase 4) | Hybrid setup: simulated mesh + `mqtt_bridge.py` publishing `<target>/command/switch:0` to the ESP32-hosted broker toggled a physical Shelly 1 Gen4 and returned the ACK |
| **ESP32 firmware: build, SoftAP, embedded broker** | ✅ Verified (Phase 4) | PlatformIO build/upload OK; SoftAP + `TinyMqtt` broker accepted the Shelly and the Python tooling as MQTT clients |
| **ESP32 firmware: native security pipeline** | ⚠️ **Not yet verified on hardware** | The C++ whitelist / anti-replay / HMAC path (`processMeshCommand()`) and the `msh/<REGION>/2/json/mqtt/` downlink ACK (`sendMeshAck()`) have only been reviewed against the Python reference - Phase 4 validated the *Python* bridge through the ESP32 broker, not the firmware's own verification. Covered by Phase 5 |

---

## 5. Simulated RF TCP Cross-Routing Bridge

`meshtasticd -s` (`SimRadio`) has no radio-layer networking of its own - each
simulated node only loops a transmitted packet back out over its own
phone/API TCP connection, framed as a `SIMULATOR_APP` (portnum 69) packet.
To let the `meshtasticd-rx` and `meshtasticd-tx` Docker containers exchange
simulated LoRa RF traffic, `meshtasticd-config/sim_rf_bridge.py` runs as the
`sim-radio-bridge` service and:

1. Connects to each node's TCP **mux** port (`ws-proxy-rx:4404` and
   `ws-proxy-tx:4404` on the Docker network) - never directly to
   `meshtasticd-*:4403`, since that port only accepts a single client
   connection, which is already permanently held open by the corresponding
   `ws-proxy-*` container.
2. For every framed `FromRadio` protobuf received from one node's mux
   connection whose `packet.decoded.portnum == SIMULATOR_APP` (69), copies
   the entire `MeshPacket` into a `ToRadio.packet` and writes it, framed with
   the standard `0x94 0xC3` + 2-byte big-endian length header, into the
   *other* node's mux connection.
3. Applies basic loop prevention using a single anti-loop cache **shared
   across both directions**: once a given `(from, id)` packet has been
   relayed one way, it will not be relayed back the other way - including
   when the receiving node performs its own normal mesh-flood rebroadcast of
   that same packet id (which appears on its mux connection as a fresh
   outgoing `SIMULATOR_APP` frame carrying the same `from`/`id`). Using two
   independent per-direction caches instead of one shared cache was tried
   first and found to bounce rebroadcasts straight back to the sender,
   causing spurious anti-replay rejections at the MQTT bridge - see the
   verified end-to-end run below.

**Verified end-to-end** (`docker compose up -d --build`, then
`provision_nodes.py --sim`, then `shelly_simulator.py`, `mqtt_bridge.py
--mesh-port 4404`, and `send_control_cmd.py --mesh-port 4406 --target
shelly1-sim01 --action ON`): the TX packet was relayed over the bridge to
RX, validated (whitelist + anti-replay + HMAC), published to Mosquitto,
toggled the Shelly simulator, and the ACK was relayed back to TX, printing
`🎉 Status ACK Received via Meshtastic!`. The `--bad-sig` and `--replay`
flags were also confirmed to be silently dropped by the gateway (no ACK,
timeout message printed), and the existing test suite
(`.venv/bin/python3 -m unittest discover tests -v`) remained green since the
bridge lives entirely in `meshtasticd-config/` and requires Docker/
`meshtastic` only at runtime, not at test-collection time.

### Pointing `mqtt_bridge.py` at a physical ESP32/LAN MQTT broker

`mqtt_bridge.py` already supports connecting to any broker on the LAN
instead of the Dockerized `mosquitto-broker` via its `--mqtt-host` and
`--mqtt-port` arguments (defaults: `localhost` / `1883`). To point it at a
physical ESP32-hosted broker (or any Mosquitto/broker reachable on your
network), run e.g.:

```bash
.venv/bin/python3 meshtasticd-config/mqtt_bridge.py \
  --mesh-port 4404 \
  --mqtt-host <ESP32_IP> \
  --mqtt-port 1883
```

Replace `<ESP32_IP>` with the ESP32 hub's LAN address (e.g. `192.168.1.50`
or its SoftAP address `192.168.4.1`). No code changes are required - this
is purely a command-line configuration switch.

---

## 6. Hybrid Testing: Simulated Mesh + Physical ESP32 SoftAP Broker

You do not need **physical Meshtastic LoRa radio hardware** to test the ESP32 Gateway firmware. You can keep the Docker-based simulated mesh (`meshtasticd-rx`/`tx`, `sim-radio-bridge`) running to generate LoRa traffic, while testing your **real physical ESP32 running `firmware/esp32-gateway`** acting as the SoftAP broker and security engine at `192.168.4.1:1883`. This validates the ESP32's `TinyMqtt` broker, its native C++ HMAC/anti-replay firmware logic, and the physical Shelly relay wiring before deploying physical LoRa radios.

1. **Flash and power on the ESP32** running
   `firmware/esp32-gateway/src/main.cpp` (see
   [`../firmware/esp32-gateway/README.md`](../firmware/esp32-gateway/README.md) for flashing steps). Confirm over
   serial that it prints its SoftAP SSID (`ESP32-Hub`) and IP
   (`192.168.4.1`).
2. **Join the ESP32's Wi-Fi network** from the machine running the Python
   tooling (or route to it) so `192.168.4.1:1883` is reachable.
3. **Start the Docker simulated-mesh stack** as usual so `meshtasticd-rx`
   and `meshtasticd-tx` can exchange simulated LoRa packets:
   ```bash
   docker compose up -d
   docker compose stop mqtt-broker     # the ESP32 is the broker in this test
   .venv/bin/python3 meshtasticd-config/provision_nodes.py --sim
   ```
   (The bundled Mosquitto is stopped so nothing else listens on
   `localhost:1883` and you cannot accidentally talk to the wrong broker.
   Do **not** comment it out of `docker-compose.yaml` - the fully-simulated
   flow in §3 depends on it.)
4. **Point the Shelly simulator at the ESP32 broker** instead of Mosquitto:
   ```bash
   .venv/bin/python3 meshtasticd-config/shelly_simulator.py \
     --host 192.168.4.1 --port 1883 --id shelly1-sim01
   ```
   (Or skip this step entirely and connect a **real Shelly** to
   `192.168.4.1:1883` as described in
   [`../firmware/esp32-gateway/README.md`](../firmware/esp32-gateway/README.md) §"Connecting a Real Shelly".)
5. **Send a signed command through the simulated mesh** with
   `send_control_cmd.py` exactly as in the fully-simulated flow (the
   ESP32 only needs to be reachable as the MQTT broker; the mesh transport
   itself is still the Docker `sim-radio-bridge`):
   ```bash
   .venv/bin/python3 meshtasticd-config/send_control_cmd.py \
     --mesh-port 4406 --target shelly1-sim01 --action ON
   ```
6. Run `mqtt_bridge.py` against the ESP32 broker (Path A below) so the
   simulated RX node's packets are validated by Python and published to the
   ESP32-hosted broker:
   ```bash
   .venv/bin/python3 meshtasticd-config/mqtt_bridge.py \
     --mesh-port 4404 --mqtt-host 192.168.4.1 --mqtt-port 1883
   ```
   To exercise the ESP32's *own* verification (Path B) you need a physical
   gateway node whose native MQTT client publishes JSON uplink to the ESP32 -
   or, without any radio, publish a hand-crafted uplink envelope with
   `mosquitto_pub` as shown in
   [`../firmware/esp32-gateway/README.md`](../firmware/esp32-gateway/README.md) §7.

**Expected result** (two distinct paths - be clear about which one you are
validating):

* **Path A - Python bridge through the ESP32 broker** (`mqtt_bridge.py
  --mqtt-host 192.168.4.1`): the Python terminal logs the three security
  checks, publishes `<target>/command/switch:0`, and prints the ACK it sends
  via `sendText()`. The ESP32 serial monitor only shows `[MQTT RX]` traffic
  passing through its broker. *This is what Phase 4 verified.*
* **Path B - ESP32 native verification** (no `mqtt_bridge.py` running; the
  RX node's native MQTT client is pointed at `192.168.4.1` with
  `mqtt.json_enabled true` and `uplink_enabled` on the channel): the ESP32
  serial monitor itself logs `[Check 1/3: Whitelist]`, `[Check 2/3:
  Anti-Replay]`, `[Check 3/3: HMAC Signature]`, the `[MQTT Publish]` to
  `<target>/command/switch:0`, then `[MQTT State Event]` when the Shelly's
  `<target>/status/switch:0` arrives, and finally `[Mesh ACK] ->
  msh/<REGION>/2/json/mqtt/ : {...}`. *This path is **not** yet verified
  on hardware - see ROADMAP Phase 5.* Note that Path B **cannot** be fully
  exercised with the Docker simulated nodes: `meshtasticd -s` containers
  cannot reach the ESP32's SoftAP subnet unless the host routes it, and the
  JSON downlink requires a channel literally named `mqtt` on a physical
  gateway node.
