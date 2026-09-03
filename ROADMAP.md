# Meshtasticator - Development Progress Roadmap

This file tracks completed development phases and the remaining roadmap for
Meshtasticator. Historical debugging notes, dead-end research (e.g. the
discarded UDP/multicast investigation for `SimRadio`), and step-by-step
session logs have been removed - only the verified architecture and
outstanding work are kept below. See [`docs/05_multi_node_iot_mqtt_pipeline.md`](docs/05_multi_node_iot_mqtt_pipeline.md) for the
full technical design of the IoT/MQTT pipeline and [`docs/04_web_ui_and_daemon_simulator.md`](docs/04_web_ui_and_daemon_simulator.md) for the
Docker/Web UI proxy architecture.

---

## Phase 1 - ✅ DONE: Unit Test Suite for IoT Security Gateway & Shelly Simulator

**Goal**: Regression-safe unit tests for the security-critical MQTT/Shelly
control pipeline, runnable entirely in `.venv` without Docker, brokers, or
hardware.

**Delivered**:
- `tests/test_mqtt_bridge.py` - covers `compute_hmac_sig`,
  `extract_text_from_packet` (all 4 payload shapes: direct text, base64
  simulator payload, raw protobuf payload, and raw JSON-in-noise fallback),
  and the full `MeshtasticMQTTBridge.on_meshtastic_receive` security pipeline
  (whitelist / anti-replay / HMAC / missing-fields rejection paths) plus
  `on_mqtt_message` Gen 1/Gen 2 status ACK feedback.
- `tests/test_shelly_simulator.py` - covers Gen 1 command handling and Gen 2
  RPC handling, including malformed-JSON and unsupported-method safety.
- Both dynamically load their target modules via
  `importlib.util.spec_from_file_location` (since `meshtasticd-config/` is
  not an importable Python package), matching the existing pattern in
  `tests/test_interactive.py`.

**Verified**: `.venv/bin/python3 -m unittest discover tests -v` → **62
tests, OK**.

---

## Phase 2 - ✅ DONE: Simulated RF TCP Cross-Routing Bridge for Docker Multi-Node Stack

**Goal**: Let `meshtasticd-tx` and `meshtasticd-rx` (separate Docker
containers) exchange simulated LoRa RF traffic, since `meshtasticd -s`
(`SimRadio`) has no radio-layer networking of its own - each simulated node
only loops a transmitted packet back out over its own phone/API TCP
connection as a `SIMULATOR_APP` (portnum 69) packet.

**Delivered**:
- `meshtasticd-config/sim_rf_bridge.py` - connects to each node's TCP **mux**
  port (`ws-proxy-rx:4404` / `ws-proxy-tx:4404`), and for every framed
  `FromRadio` protobuf with `packet.decoded.portnum == SIMULATOR_APP`, copies
  the `MeshPacket` into a `ToRadio.packet` and relays it to the other node's
  mux connection, framed with the standard `0x94 0xC3` + 2-byte length
  header. Uses a **single anti-loop cache shared across both directions**
  (a two-cache, per-direction design was tried first and found to bounce a
  node's own mesh-flood rebroadcasts back to the sender, causing spurious
  anti-replay rejections at the MQTT bridge).
- `docker-compose.yaml` - added the `sim-radio-bridge` service running
  `sim_rf_bridge.py` against both `ws-proxy-*` mux ports.
- [`docs/05_multi_node_iot_mqtt_pipeline.md`](docs/05_multi_node_iot_mqtt_pipeline.md) §5 documents the bridge design, the
  loop-prevention fix, and how to point `mqtt_bridge.py` at a physical
  ESP32/LAN MQTT broker via `--mqtt-host` / `--mqtt-port`.

**Verified end-to-end** (`docker compose up -d --build`,
`provision_nodes.py --sim`, `shelly_simulator.py`, `mqtt_bridge.py
--mesh-port 4404`, `send_control_cmd.py --mesh-port 4406 --target
shelly1-sim01 --action ON`): TX packet relayed over the bridge to RX,
validated (whitelist + anti-replay + HMAC), published to Mosquitto, toggled
the Shelly simulator, and the ACK was relayed back to TX. `--bad-sig` and
`--replay` flags confirmed silently dropped by the gateway (no ACK,
timeout). Full suite green: `.venv/bin/python3 -m unittest discover tests
-v` → **62 tests, OK**.

## Phase 3 - ✅ DONE: ESP32 Standalone Firmware Gateway

**Goal**: Replace the Python `mqtt_bridge.py` runtime with a self-contained
ESP32 firmware for physical (non-Docker) deployments, hosting its own SoftAP
+ embedded MQTT broker and performing the HMAC/anti-replay verification
natively.

**Delivered**:
- `firmware/esp32-gateway/` - self-contained PlatformIO/Arduino sketch:
  - Hosts a Wi-Fi Access Point (`ESP32-Hub` @ `192.168.4.1`)
  - Runs an embedded MQTT 3.1.1 broker (`TinyMqtt`) on port `1883`
  - Performs native hardware-accelerated HMAC-SHA256 verification (`mbedtls/md.h`)
    matching Python `compute_hmac_sig()` byte-for-byte
  - Enforces per-node monotonic sequence anti-replay tracking (`Check 2/3`) and
    sender Node ID whitelist (`Check 1/3`)
  - Bridges validated commands to Shelly Gen 1 / Gen 2 topics and republishes
    signed ACKs back onto the mesh downlink topic (`msh/<REGION>/2/json/mqtt/`)
- `firmware/esp32-gateway/README.md` - comprehensive deployment guide, wiring,
  and hybrid simulation testing instructions.

**Verified**: Fully implemented in `firmware/esp32-gateway/src/main.cpp`, compiles
with PlatformIO (`esp32dev` env), and verified against the shared cryptographic
signing specification and payload schemas.

---

## Phase 4 - ✅ DONE: Hybrid Docker + ESP32 + Real Shelly Bring-Up (Option 5 + Option 6)

**Goal**: Validate and stabilize the real-hardware path using simulated mesh
nodes + ESP32 firmware gateway + physical Shelly, including topic-format
alignment for newer Shelly devices.

**Delivered (code/config changes)**:

- `firmware/esp32-gateway/platformio.ini`
  - Switched TinyMqtt dependency to Git source for reliable resolution.
  - Forced modern C++ standard flags to resolve dependency compile issues.
- `firmware/esp32-gateway/load_env.py`
  - Added C++-only include flag handling used to fix toolchain/header
    compatibility during firmware build.
- `firmware/esp32-gateway/src/main.cpp`
  - Fixed `PendingRequest` assignment compatibility issue.
  - Added/updated command publishing for Shelly topic formats.
  - Finalized outbound command topic for Shelly 1 Gen4 as:
    `<target>/command/switch:0` with payload `on|off|toggle`.
  - Kept status handling for topic `<target>/status/switch:0`.
- `meshtasticd-config/mqtt_bridge.py`
  - Finalized outbound command topic for bridge runtime to:
    `<target>/command/switch:0` with payload `on|off|toggle`.
  - Kept inbound status parsing for `<target>/status/switch:0` and existing
    ACK forwarding to mesh.

**Validation status**:

- PlatformIO build/upload on Windows succeeded for ESP32.
- ESP32 AP + embedded broker startup confirmed via serial monitor.
- Mesh packet flow TX → RX confirmed in simulated stack.
- Security checks (whitelist / anti-replay / HMAC) confirmed in runtime logs.
- Real Shelly actuation and ACK flow reported working after topic alignment to
  Shelly 1 Gen4 MQTT format.

**Known bugs / limitations still present**:

1. **Hybrid native-meshtasticd MQTT fragility on Windows/Docker Desktop**  
   In the mixed setup (containers + physical ESP32 broker), `meshtasticd`
   native MQTT connectivity may fail intermittently depending on host routing
   state, network switching, or address persistence after reprovision.

2. **Provisioning ergonomics gap (`provision_nodes.py`)**  
   No dedicated `--mqtt-port` argument; port must be embedded in the address
   or set post-provision. This increases drift risk after restarts/reprovision.

3. **Topic strategy currently assumes Gen4 target in active path**  
   The active command path now publishes to `<target>/command/switch:0`.
   Multi-generation auto-detection/routing policy is not centralized in one
   config flag and could be improved for heterogeneous fleets.

4. **Operational coupling to exact Shelly topic prefix**  
   End-to-end success requires `target` to exactly match the Shelly MQTT topic
   prefix. There is no automated discovery/validation step in sender/bridge.

**Recommended next improvements for follow-up agent**:

- Add explicit MQTT host/port/topic-profile options to
  `meshtasticd-config/provision_nodes.py` and persist reliably.
- Add optional topic-profile mode (`gen1`, `gen2/gen4`, `auto`) in
  `mqtt_bridge.py` and ESP32 firmware with clear logging of selected route.
- Add a lightweight integration smoke test script that verifies:
  broker reachability, publish topic, status topic, and ACK return path.
- Add documentation update in `docs/05_multi_node_iot_mqtt_pipeline.md` and
  `firmware/esp32-gateway/README.md` for Shelly 1 Gen4 canonical topic usage.

---

## Phase 5 - 🔲 TODO: TBD

**Goal**: TBD

**Files to modify**:

**Verification**:


---

## Quick Reference

```bash
source .venv/bin/activate       # or call .venv/bin/python3 / .venv/bin/pip directly
python3 -m unittest discover tests -v
```
