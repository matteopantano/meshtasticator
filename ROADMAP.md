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

## Phase 4 - 🔲 TODO: Technical Debt Refactor in Discrete Radio Simulator Core

**Goal**: Address long-standing `TODO`s that affect maintainability and
correctness of the discrete-event simulator core (not blocking, lower
priority).

**Files to modify**:
- `lib/phy.py`:
  - Refactor `zero_link_budget(dist)` / `zero_link_budget_with_gain(dist,
    gain)` (and the module-load-time `MAXRANGE = rootFinder(zero_link_budget,
    1500)`) to accept an explicit `conf` parameter instead of relying on the
    module-global `conf = CONFIG` singleton, so tests/scripts that mutate a
    separate `Config()` instance get correct results.
  - Implement the `wide_lora` region bandwidth adjustment noted in the TODO
    at `lib/config.py:318` (`bw` should change based on the region's
    `wide_lora` setting; currently unimplemented).
- `lib/discrete_event_sim.py`:
  - Optimize the O(packets * nodes) collision/sensed counting loops (around
    line 67-68) to use per-node counters accumulated during the simulation
    instead of a full post-hoc scan.

**Verification**:
```bash
.venv/bin/python3 -m unittest discover tests -v
```
Pay special attention to `tests/test_discrete_event_sim.py` -
`test_discrete_sim_ten_nodes` and `test_sim_does_not_change_config`, which
assert exact hardcoded simulation result values and that `Config` objects
are not mutated by a simulation run. If refactoring changes any computed
values, either it's an unintended regression (fix it) or an intentional
correction (update the hardcoded expected values with a comment explaining
why).

---

## Quick Reference

```bash
source .venv/bin/activate       # or call .venv/bin/python3 / .venv/bin/pip directly
python3 -m unittest discover tests -v
```
