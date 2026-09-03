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
tests, OK** at the time (69 after the Phase 4 clean-up).

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
  - Bridges validated commands to the Shelly command topic (Gen 1 at the time;
    Gen 2+ `<target>/command/switch:0` since Phase 4) and republishes ACKs
    (unsigned) back onto the mesh downlink topic (`msh/<REGION>/2/json/mqtt/`)
- `firmware/esp32-gateway/README.md` - comprehensive deployment guide, wiring,
  and hybrid simulation testing instructions.

**Verified**: Fully implemented in `firmware/esp32-gateway/src/main.cpp`, compiles
with PlatformIO (`esp32dev` env), and reviewed against the shared cryptographic
signing specification and payload schemas. *(Desk-checked only at this stage -
runtime verification of the firmware's own security path is the subject of
Phase 5.)*

---

## Phase 4 - ✅ DONE (partially verified): Hybrid Docker + ESP32-as-Broker + Real Shelly Bring-Up

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

- `docker-compose.yaml`
  - The `mqtt-broker` (Mosquitto) service was commented out during the hybrid
    test so the ESP32 could be the only broker on `:1883`. **This was a local
    testing artifact that got committed** - it broke the fully-simulated flow
    (`mqtt_bridge.py` / `shelly_simulator.py` default to `localhost:1883`,
    `provision_nodes.py --sim` points nodes at `mqtt-broker`). Restored in the
    Phase 4 clean-up below; use `docker compose stop mqtt-broker` instead.
- `.env.example`: `LORA_REGION` changed from `US` to `EU_868` (uncommitted at
  the time of the clean-up; now documented as the value that must match the
  gateway node's MQTT topic region).

**Phase 4 clean-up (post-hoc, this revision)**:

- `tests/test_mqtt_bridge.py` - two tests still asserted the Gen 1 topic and
  were failing after the Phase 4 change; updated to
  `<target>/command/switch:0`.
- `meshtasticd-config/shelly_simulator.py` - now also subscribes to and
  handles the Gen 2+ MQTT-control topic `<id>/command/switch:0`
  (`on|off|toggle|status_update`), so the simulated stack works with the
  Phase 4 gateway again. New `TestGen2MqttControlHandling` test class
  (7 tests).
- `docker-compose.yaml` - Mosquitto service restored with a comment on how to
  stop it for hybrid tests.
- Documentation brought in line with the code (see "Documentation impact"
  below).
- Suite: `.venv/bin/python3 -m unittest discover tests -v` → **69 tests, OK**.

**Validation status - what was actually exercised** (be precise: the ESP32
was used *only as a Wi-Fi AP + MQTT broker* in these tests; the Python
bridge did the security work):

| Item | Status | Evidence / how |
| :-- | :-- | :-- |
| PlatformIO build + upload (`esp32dev`, Windows host) | ✅ | `pio run -t upload` succeeded after the toolchain workarounds |
| ESP32 SoftAP `ESP32-Hub` @ `192.168.4.1` + `TinyMqtt` broker on `:1883` | ✅ | Serial banner; Shelly and laptop connected as MQTT clients |
| Simulated mesh TX → RX packet flow (Docker, `sim-radio-bridge`) | ✅ | `send_control_cmd.py --mesh-port 4406` → RX node received |
| Whitelist / anti-replay / HMAC checks **in `mqtt_bridge.py`** (`--mqtt-host 192.168.4.1`) | ✅ | Python runtime logs `Check 1/3 … 3/3` |
| `<target>/command/switch:0` publish toggles a **real Shelly 1 Gen4** through the ESP32 broker | ✅ | Relay actuated; `<target>/status/switch:0` observed |
| ACK relayed back to TX **by `mqtt_bridge.py`** (`sendText`) | ✅ | `send_control_cmd.py` printed the ACK |
| **ESP32 firmware native verification** (`processMeshCommand()`: whitelist, anti-replay, HMAC) | ❌ **Not tested** | No JSON uplink ever reached the ESP32's own client - the simulated `meshtasticd` nodes cannot reach the SoftAP subnet |
| **ESP32 firmware ACK downlink** (`sendMeshAck()` → `msh/<REGION>/2/json/mqtt/`) | ❌ **Not tested** | Requires a physical gateway node with a `mqtt` downlink channel |
| `GATEWAY_NODE_ID` / `MESH_LORA_REGION` compile-time injection correctness at runtime | ❌ **Not tested** | Only the boot warning path was observed |
| Physical Meshtastic radios (LoRa TX → LoRa RX → native MQTT client) | ❌ **Not tested** | No physical nodes in the Phase 4 setup |
| `provision_nodes.py --serial` against a physical node | ❌ **Not tested** | |
| Negative tests (`--replay`, `--bad-sig`) against the **firmware** | ❌ **Not tested** | Only verified against the Python bridge (Phase 2) |

**Documentation impact of Phase 4 (found during the clean-up and fixed)**:

- `docs/05_multi_node_iot_mqtt_pipeline.md`: §2A ACK schema used `target`
  instead of the actual `device` field and had a wrong sample `sig`; §2C
  did not list the Gen 2+ `command/switch:0` topic nor the `status_ntf`
  requirement; §4 verification table over-claimed the firmware as
  "Verified"; §6 hybrid test still described the Gen 1 topic and told users
  the Mosquitto service was optional (it was removed instead). All fixed, and
  the hybrid test now distinguishes *Path A* (Python bridge through the ESP32
  broker - what Phase 4 did) from *Path B* (firmware native verification -
  Phase 5).
- `docs/07_physical_hardware_deployment.md`: contained a stale, simplified
  inline sketch (single global `seq`, no whitelist, Gen 1 topic, non-existent
  `broker.publish()` API) that diverged from `main.cpp`; listed the nRF52
  T-Echo as a possible Wi-Fi gateway; Shelly section described Gen 1 UI
  paths; sample `sig` `e0e2e92c` was wrong (`ccb1d0e1`). Replaced the sketch
  with a behaviour table + boot log, fixed BOM, Shelly Gen 2+ settings
  (incl. *Generic status update over MQTT*), added the manual channel
  `uplink_enabled` / `mqtt` downlink steps the provisioner does not do, and a
  "known limitations" section (unsigned ACK, RAM-only anti-replay, open
  broker, `seq` wrap in `send_control_cmd.py`).
- `firmware/esp32-gateway/README.md`: still said `shellies/<id>/relay/0/command`;
  added the toolchain workaround table, Shelly Gen 2+ settings, expected
  serial log for the `mosquitto_pub` self-test (with the correct `sig`
  `5fcfbf0c`), whitelist / `GATEWAY_NODE_ID` production notes, and nRF52 /
  region / Bluetooth gotchas.
- `README.md`: SoftAP name typo (`Mesh-Gateway` → `ESP32-Hub`), test count,
  Phase 4 topic note, firmware verification status, hardware quickstart steps.
- `docs/04_web_ui_and_daemon_simulator.md` §5: port typo (TX mux is `4406`),
  broker note, simulator/bridge descriptions.
- `.env.example`: explained `LORA_REGION` / `GATEWAY_NODE_ID` coupling with
  the firmware.

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

5. **Gen 1 Shelly devices are no longer controllable**  
   Only the Gen 2+ command topic is published. Gen 1 status is still parsed.

6. **`provision_nodes.py` does not configure channels**  
   `uplink_enabled` on channel 0 and the `mqtt` downlink channel must be set
   manually (documented in docs/07 §4).

7. **`send_control_cmd.py` `seq` wraps** (`int(time.time() % 1_000_000)`,
   ~11.6 days) which the gateway will then reject as a replay until reboot.

8. **Anti-replay state is RAM-only** on both gateways; the ACK is unsigned;
   the embedded broker is unauthenticated (SoftAP password is the only gate).

The "recommended next improvements" originally listed here (provisioner
MQTT/topic options, topic-profile flag, smoke-test script, docs update) are
now tracked as Phase 5 deliverables / Phase 6 backlog.

---

## Phase 5 - 🔲 TODO: Real Meshtastic Hardware Validation & ESP32 Firmware Verification

**Goal**: Close the verification gap left by Phase 4 by running the complete
pipeline on **physical Meshtastic radios** with the **ESP32 firmware doing
the security work** (no Python bridge in the loop), then harden the tooling
based on what is learned. Every step below states what is being proven and
what log line / observable constitutes a pass, so the phase produces an
auditable test record rather than "reported working".

**Hardware needed**: 1x ESP32 dev board (hub), 1x ESP32-based Meshtastic node
with Wi-Fi (RX gateway, e.g. Heltec V3 / T-Beam), 1x Meshtastic node (TX -
any board, or a phone paired to one), 1x Shelly Gen 2+ (the Shelly 1 Gen4
from Phase 4), a laptop with the repo `.venv` and `mosquitto-clients`.

### 5.0 - Pre-flight (no radios yet)

- [ ] `cp .env.example .env`; set a real `WIFI_PASS`, a fresh `CONTROL_SECRET`,
      `LORA_REGION` (the region you will use on the nodes, e.g. `EU_868`),
      and `GATEWAY_NODE_ID` (**after** step 5.2 reveals it - rebuild then).
- [ ] `pio run` on **this Linux machine** (Phase 4 built only on Windows) →
      confirm the `load_env.py` / `-std=gnu++17` / `-include utility`
      workarounds hold; note the exact `TinyMqtt` commit resolved from Git
      (pin it in `platformio.ini` if the build breaks).
- [ ] Flash, open `pio device monitor`, expect the boot banner from docs/07 §3
      **without** the `MESH_GATEWAY_NODE_ID is not configured` warning once
      5.2 is done.
- [ ] Docker stack on the laptop stays **down** for this phase (or at least
      `docker compose stop mqtt-broker`) so `localhost:1883` cannot be
      confused with `192.168.4.1:1883`.

### 5.1 - ESP32 firmware native security path (no radios, `mosquitto_pub`)

Proves the code path Phase 4 never reached. Laptop joined to `ESP32-Hub`.

- [ ] **Positive**: publish the uplink envelope from firmware README §7 with a
      valid `sig` → serial shows `[Check 1/3 …]`, `[Check 2/3 …]`,
      `[Check 3/3 …]`, `[MQTT Publish] Topic: <target>/command/switch:0`.
- [ ] **Shelly actuation from firmware**: with the real Shelly joined
      (docs/07 §5, *Generic status update* ON) the relay clicks and serial
      shows `[MQTT State Event] Target: <target> | State: ON`.
- [ ] **ACK downlink emitted**: serial shows
      `[Mesh ACK] -> msh/<REGION>/2/json/mqtt/ : {"from":<GATEWAY_NODE_ID>,"to":<sender>,"type":"sendtext",...}`
      and `mosquitto_sub -t 'msh/#' -v` on the laptop receives it. Verify
      `<REGION>` equals `LORA_REGION` and `from` is non-zero.
- [ ] **Replay**: re-publish the identical envelope → `[Security REJECTED:
      Replay Attack]`, no publish, no ACK.
- [ ] **Bad signature**: flip one hex digit → `[Security REJECTED: Bad
      Signature]`.
- [ ] **Whitelist**: set `ALLOWED_NODES = {"!a1b2c3d4"}`, rebuild, publish
      with `from` of a different node → `[Security DENIED]`; with the listed
      node → accepted. Confirm `decimalNodeIdToHex()` formatting (lower-case,
      8 digits, zero-padded) against `meshtastic --info` output.
- [ ] **Case / envelope robustness**: `"action":"on"` (lower-case) is
      accepted with a signature computed over `ON`; envelope with
      `"payload":"<string>"` (older firmware) and `"payload":{"text":...}`
      both parse; non-`text` types (`position`, `nodeinfo`) are ignored
      silently.
- [ ] **Pending-request timeout**: send a valid command for a `target`
      that does not exist → no ACK, and after 30 s the slot is reclaimed
      (a following valid command still gets its ACK).
- [ ] **Cross-implementation check**: publish the same `target/action/seq`
      vectors used in `tests/test_mqtt_bridge.py` - the firmware must reach
      identical accept/reject decisions to `compute_hmac_sig()`.

### 5.2 - Physical RX gateway node bring-up

- [ ] `meshtastic --port /dev/ttyUSB0 --info` → record Node ID `!xxxxxxxx`
      and firmware version; put it in `.env` `GATEWAY_NODE_ID` and rebuild /
      reflash the ESP32 (5.0).
- [ ] `provision_nodes.py --serial /dev/ttyUSB0 --role rx` → node reboots,
      `--info` shows `wifi_ssid ESP32-Hub`, `mqtt.address 192.168.4.1`,
      `json_enabled true`, `encryption_enabled false`, `lora.region` =
      `LORA_REGION`. Note: Bluetooth is off once Wi-Fi is on.
- [ ] Manual channel steps (docs/07 §4 warning box): `uplink_enabled` on
      channel 0; `--ch-add mqtt` + `downlink_enabled true`. Record the index.
- [ ] ESP32 serial shows the node's MQTT client connecting; `mosquitto_sub
      -t 'msh/#' -v` shows `msh/<REGION>/2/json/LongFast/!xxxxxxxx` traffic
      (nodeinfo/position) → confirms the topic `REGION` string matches
      `LORA_REGION`.

### 5.3 - Physical TX node + end-to-end over LoRa

- [ ] `provision_nodes.py --serial /dev/ttyUSB1 --role tx`; make sure TX has
      the same primary channel PSK **and** the same `mqtt` channel (name +
      PSK) as RX so ACKs are decryptable.
- [ ] Send a signed command from TX: either `send_control_cmd.py --mesh-host
      <tx-ip> --mesh-port 4403 --target <prefix> --action ON` (TX on home
      Wi-Fi) or paste the JSON from docs/07 §6 in the app.
- [ ] Observe the full chain: TX radio → RX radio → RX MQTT uplink → ESP32
      `[Check 1..3]` → Shelly clicks → `[MQTT State Event]` → `[Mesh ACK]`
      → RX node transmits on `mqtt` channel → ACK visible on TX
      (`send_control_cmd.py` prints `Status ACK Received`, or a text message
      appears in the app).
- [ ] Repeat `OFF`, `TOGGLE`; then `--replay` and `--bad-sig` → no ACK,
      firmware logs the rejection.
- [ ] **Range / hops**: move TX out of Wi-Fi range; if a third node is
      available, confirm relaying still yields an ACK (hop limit ≥ 2).
- [ ] **Reboot behaviours**: power-cycle the ESP32 → first command after
      reboot is accepted with any `seq` (documents the RAM-only anti-replay
      limitation); power-cycle the RX node → its MQTT client reconnects to
      the ESP32 without re-provisioning; power-cycle the Shelly → it
      re-joins and republishes retained status.
- [ ] **Soak**: leave running ≥ 2 h sending a command every 10 min; record
      any ESP32 reset, `TinyMqtt` disconnects, or missed ACKs.

### 5.4 - Record results

- [ ] Fill a results table (date, firmware versions, board models, each
      checkbox above with PASS/FAIL + the serial/CLI excerpt) in
      `docs/08_hardware_validation_report.md` (new) and link it from
      `docs/07` and the README status table.
- [ ] Update the "Verification status" tables in `docs/05` §4 and
      `firmware/esp32-gateway/README.md` §1 from "Not yet verified" to the
      real outcome.

### 5.5 - Hardening driven by the results (code)

Implement only after 5.1-5.3 so fixes target observed problems:

- [ ] `meshtasticd-config/provision_nodes.py`: add `--mqtt-port`,
      `--uplink` (sets `--ch-index 0 --ch-set uplink_enabled true`) and
      `--downlink-channel mqtt` (adds the channel + `downlink_enabled`), plus
      a `--verify` that re-reads `--info` and prints a PASS/FAIL checklist.
- [ ] `meshtasticd-config/send_control_cmd.py`: make `seq` non-wrapping
      (`int(time.time())`) - both gateways store `seq` as `long`/`int`; add
      `--serial` so a USB-attached TX can be used without Wi-Fi
      (`meshtastic.serial_interface.SerialInterface`).
- [ ] Topic-profile flag: `--shelly-profile gen1|gen2|both` in
      `mqtt_bridge.py` and `SHELLY_PROFILE` macro in the firmware (default
      `gen2`), logging the selected route; extend `tests/test_mqtt_bridge.py`
      for both profiles.
- [ ] Optional (if the 5.3 reboot test is judged unacceptable): persist
      `last_seen_seq` per sender to ESP32 NVS (`Preferences`) and to a small
      JSON file for `mqtt_bridge.py`.
- [ ] Optional: HMAC-sign the ACK (`sig` over `device:STATE:ack_seq`) and
      verify it in `send_control_cmd.py`.
- [ ] New `meshtasticd-config/smoke_test.py`: connects to a broker, checks
      `<target>/status/switch:0` is retained/visible, publishes
      `status_update`, and (optionally) injects a signed uplink envelope and
      waits for the `msh/<REGION>/2/json/mqtt/` ACK - a scripted version of
      §5.1 usable in CI against Mosquitto + `shelly_simulator.py`.

**Files to modify**: `ROADMAP.md`, `docs/08_hardware_validation_report.md`
(new), `docs/05_multi_node_iot_mqtt_pipeline.md` §4,
`docs/07_physical_hardware_deployment.md`, `firmware/esp32-gateway/README.md`,
`firmware/esp32-gateway/src/main.cpp` (`ALLOWED_NODES`, optional
`SHELLY_PROFILE` / NVS), `firmware/esp32-gateway/platformio.ini` (pin
TinyMqtt), `meshtasticd-config/provision_nodes.py`,
`meshtasticd-config/send_control_cmd.py`, `meshtasticd-config/mqtt_bridge.py`,
`meshtasticd-config/smoke_test.py` (new), `tests/test_mqtt_bridge.py`,
`tests/test_send_control_cmd.py` (new, for `seq`/signing helpers).

**Verification**:

- All 5.1 checkboxes PASS with serial excerpts recorded (this is the primary
  exit criterion - it is what Phase 4 could not show).
- 5.3 end-to-end ACK observed on the TX side over LoRa at least 3 times
  consecutively, plus `--replay` / `--bad-sig` rejected.
- `.venv/bin/python3 -m unittest discover tests -v` green after 5.5 changes.
- `docker compose up -d` + `provision_nodes.py --sim` + `shelly_simulator.py`
  + `mqtt_bridge.py` + `send_control_cmd.py` still produce an ACK (no
  regression of the fully-simulated flow from Phase 2).

**Out of scope / Phase 6 backlog**: Mosquitto with authentication instead
of `TinyMqtt`; TLS to the Shelly; multi-relay (`switch:1`) targets; OTA
updates of the ESP32; Home Assistant integration.

---

## Quick Reference

```bash
source .venv/bin/activate       # or call .venv/bin/python3 / .venv/bin/pip directly
python3 -m unittest discover tests -v
```
