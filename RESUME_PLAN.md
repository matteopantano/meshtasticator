# Meshtasticator - Development Resumption Plan

This file documents the current progress of the ongoing development phase and the
step-by-step roadmap to resume work in a new Cline session/window. Give this file
to Cline and ask it to "read RESUME_PLAN.md and continue from Phase 1" to pick up
exactly where the previous session left off.

---

## 1. Environment & Setup Already Completed

1. **Environment Config (`.env`)**:
   - `.env` has been created from `.env.example` with standard development
     defaults (`WIFI_SSID`, `CONTROL_SECRET`, `MQTT_HOST_SIM`, `LORA_REGION`, etc.).
   - `.env` is git-ignored; never commit real secrets into it.

2. **Python Virtual Environment (`.venv`)**:
   - Created at `/home/matteo/meshtasticator/.venv` using Python 3.12.
   - NOTE: `python3-venv`'s `ensurepip` was not available on this system, so pip
     had to be bootstrapped manually via `get-pip.py`
     (`curl -sSL -o /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py && .venv/bin/python3 /tmp/get-pip.py`).
     If recreating the venv from scratch on a similar machine, repeat this
     bootstrap step if `python3 -m venv .venv` fails with an `ensurepip` error.
   - All dependencies from `requirements.txt` are installed in `.venv`
     (`meshtastic`, `numpy`, `matplotlib`, `pandas`, `PyPubSub`, `simpy`,
     `PyYAML`, `protobuf`, `paho-mqtt`, `python-dotenv`).

3. **Baseline Test Verification**:
   - Confirmed all 31 existing tests in `tests/` pass cleanly via:
     ```bash
     cd /home/matteo/meshtasticator
     .venv/bin/python3 -m unittest discover tests
     ```

4. **Docker**:
   - Docker / Docker Compose are **NOT installed** on this machine yet. Phase 2
     below (simulated RF UDP relay) requires Docker to actually run and verify;
     until Docker is installed, that phase can only be implemented/reviewed as
     code, not executed end-to-end.
     Install with (requires sudo password, which was not available in the prior
     session): `sudo apt install docker.io` (or `docker-ce` via the official
     Docker repo).

5. **Web UI NGINX Proxy Fix (`meshtasticd-config/nginx.conf`)** - DONE:
   - Fixed a bug where `proxy_pass` pointed to a non-existent upstream name
     `meshtastic-ws-proxy`. Updated it to `ws-proxy-rx:4403` to match the actual
     service/container name defined in `docker-compose.yaml`. This was required
     for the unified Web UI (port 8080) to correctly reach the RX node's
     WebSocket/HTTP proxy.

6. **Code-Server / iPad Access Notes** (informational, no code changes needed):
   - User accesses this machine's code-server over **self-signed HTTPS** from an
     **iPad Safari web app**. Browser clipboard API (`navigator.clipboard`) is
     blocked in this context, causing "Unable to read from the browser
     clipboard" warnings from VS Code's UI (unrelated to Cline's own file/tool
     operations, which never use the browser clipboard).
   - Workarounds: use native iOS tap-and-hold copy/paste, a Bluetooth keyboard
     with Cmd+C/Cmd+V, or trust the self-signed cert on the iPad
     (Settings > General > About > Certificate Trust Settings).
   - **Important instruction for Cline**: do not rely on or invoke any browser
     clipboard read/write functionality; all edits must go through the file
     editor / terminal tools only.

---

## 2. Roadmap for Remaining Work

### Phase 1 - ✅ DONE: Unit Test Suite for IoT Security Gateway & Shelly Simulator

**Status**: Completed. `tests/test_mqtt_bridge.py` (31 tests: `compute_hmac_sig`,
`extract_text_from_packet` across all 4 payload shapes, the full
`on_meshtastic_receive` security pipeline - whitelist / anti-replay / HMAC /
missing-fields rejection paths - and `on_mqtt_message` Gen1/Gen2 status ACK
feedback) and `tests/test_shelly_simulator.py` (Gen 1 command handling and
Gen 2 RPC handling, including malformed-JSON and unsupported-method safety)
were added. Both dynamically load their modules via
`importlib.util.spec_from_file_location`, matching the pattern in
`tests/test_interactive.py`. Full suite verified green:
`.venv/bin/python3 -m unittest discover tests -v` → **62 tests, OK** (31
pre-existing + 31 new). Next step to resume: **Phase 2** below.

**Goal**: Add regression-safe unit tests for the security-critical MQTT/Shelly
control pipeline, runnable entirely in `.venv` without Docker, brokers, or
hardware.

**Files to create**:
- `tests/test_mqtt_bridge.py`
- `tests/test_shelly_simulator.py`

**Implementation notes**:
- `meshtasticd-config/` is not a Python package (no `__init__.py`, and the
  directory name contains a dash so it can't be imported normally). Load
  `mqtt_bridge.py` and `shelly_simulator.py` in tests using
  `importlib.util.spec_from_file_location` + `module_from_spec`, similar to the
  existing pattern in `tests/test_interactive.py` (`load_interactive_sim()`).
- Both scripts import `paho.mqtt.client` and (for `mqtt_bridge.py`) `meshtastic`,
  `meshtastic.tcp_interface`, and `pubsub`. These are all installed in `.venv`
  already, so plain imports should work; no need to mock them out at import
  time. Only mock/stub the *runtime* MQTT/mesh connections (do not call
  `.run()`, `mqtt_client.connect()`, or open TCP interfaces in tests).

**`tests/test_mqtt_bridge.py` should cover**:
1. `compute_hmac_sig(secret, target, action, seq)`:
   - Known input/output vector, e.g.
     `compute_hmac_sig("MeshShellySecret2026", "shelly1-sim01", "ON", 1042)`
     should equal `hmac.new(b"MeshShellySecret2026", b"shelly1-sim01:ON:1042",
     hashlib.sha256).hexdigest()[:8]` (compute expected value in the test using
     `hmac`/`hashlib` directly rather than hardcoding a magic string).
   - Case-insensitivity of the `action` parameter (`"on"` vs `"ON"` produce the
     same signature).
2. `extract_text_from_packet(packet)`:
   - Direct `decoded.text` string.
   - Base64-encoded simulated payload under `decoded.simulator.data`, encoding a
     serialized `mesh_pb2.Data` protobuf with a JSON `payload`.
   - Raw `decoded.payload` bytes containing a serialized `mesh_pb2.Data` with a
     JSON payload.
   - Raw `decoded.payload` bytes that are NOT protobuf but contain a `{...}`
     JSON substring embedded in noise (fallback substring-extraction path).
   - Empty/missing decoded payload returns `""`.
3. `MeshtasticMQTTBridge.on_meshtastic_receive` security pipeline (instantiate
   the class directly - its `__init__` does not open any network connections,
   only constructs an MQTT client object and dicts):
   - Valid signed command with correct whitelist, sequence, and HMAC is
     accepted: assert `mqtt_client.publish` is called with topic
     `shellies/<target>/relay/0/command` and payload `on`/`off`/`toggle`
     (mock/stub `bridge.mqtt_client.publish` and `bridge.mesh_iface` before
     calling `on_meshtastic_receive`).
   - Sender not in `allowed_nodes` whitelist is rejected (publish not called).
   - Replayed/stale `seq` (<= `last_seen_seq`) is rejected.
   - Tampered/incorrect `sig` is rejected.
   - Missing required fields (`target`, `action`, `seq`, `sig`) is rejected.
   - Successful command updates `self.last_seen_seq[from_id]` and
     `self.pending_requests[target]`.
4. `MeshtasticMQTTBridge.on_mqtt_message` (status feedback path):
   - Gen 1 topic `shellies/<id>/relay/0` with payload `on`/`off` resolves
     `target`/`state` correctly and, if there is a pending request for that
     target, calls `mesh_iface.sendText` with a JSON ACK payload containing
     `ack_seq` matching the pending request's `seq`.
   - Gen 2 topic `<id>/status/switch:0` with JSON payload `{"output": true}`
     resolves state to `"ON"`.
   - No pending request for the target: no `sendText` call happens (no crash).

**`tests/test_shelly_simulator.py` should cover**:
1. Gen 1 command handling via `on_message` with topic
   `shellies/<id>/relay/0/command`:
   - `"on"`, `"1"`, `"true"` set `self.state = True`.
   - `"off"`, `"0"`, `"false"` set `self.state = False`.
   - `"toggle"`/`"t"` flips `self.state`.
   - Unknown command leaves state unchanged and does not raise.
   - Each valid command triggers a call to `publish_state()` (mock/patch
     `self.client.publish` and verify topics/payloads: Gen 1 topic
     `shellies/<id>/relay/0` with `on`/`off` string, Gen 2 topic
     `<id>/status/switch:0` with JSON containing `"output"` boolean).
2. Gen 2 RPC handling via `on_message` with topic `<id>/rpc`:
   - `{"method": "Switch.Set", "params": {"on": true}}` sets state True.
   - `{"method": "Switch.Toggle"}` flips state.
   - `{"method": "Switch.GetStatus"}` does not change state but still
     re-publishes.
   - Unsupported method does not raise and does not call `publish_state()`.
   - Malformed JSON payload does not raise.

**Verification commands**:
```bash
cd /home/matteo/meshtasticator
.venv/bin/python3 -m unittest discover tests -v
```
All existing 31 tests plus the new tests should pass. Pay attention to any
`paho-mqtt` version warnings (project pins `paho-mqtt~=2.1.0`, callback API
version 2) - use `mqtt.CallbackAPIVersion.VERSION2` consistently as the existing
scripts do, and construct `mqtt.Client(...)` objects the same way the source
files do to avoid deprecation warnings/errors.

---

### Phase 2: Simulated RF UDP Cross-Routing Bridge for Docker Multi-Node Stack

**Goal**: Enable `meshtasticd-tx` and `meshtasticd-rx` (in separate Docker
containers) to exchange simulated LoRa RF traffic over UDP, which Docker's
default bridge network does not allow for broadcast packets between
containers. Currently tracked as `🟡 In Debugging` in
`MQTT_SHELLY_SIMULATION.md`.

**Files to create/modify**:
- `meshtasticd-config/udp_radio_bridge.py` (new)
- `docker-compose.yaml` (add a `sim-radio-bridge` service)
- `MQTT_SHELLY_SIMULATION.md` (update status table entry to `✅ Verified` once
  confirmed working)

**Implementation notes**:
- Research exactly how `meshtasticd`'s Portduino `SimRadio` sends/receives UDP
  packets (port, whether it is broadcast vs. multicast vs. unicast to a
  configured peer list) before finalizing the relay design - check
  `meshtasticd` startup logs/config options (e.g. `Lora.Module` /
  `SimRadio` config in Portduino, and whether there's a `--sim-udp-port` or
  similar flag/config key) since the details determine whether the bridge needs
  to be a broadcast reflector, a unicast relay with a static peer list, or a
  multicast relay.
- `udp_radio_bridge.py` should open a UDP socket bound to `0.0.0.0` on the
  relevant port, set `SO_REUSEADDR` (and `SO_BROADCAST` if broadcast relay is
  needed), and forward/reflect received datagrams to the other known
  container(s) on the `meshtastic` Docker network (e.g. by resolving
  `meshtasticd-rx` / `meshtasticd-tx` hostnames via Docker's embedded DNS).
- Add the new service to `docker-compose.yaml` (adjust based on the actual UDP
  port/protocol discovered above):
  ```yaml
  sim-radio-bridge:
    image: python:3.11-slim
    container_name: meshtastic-sim-radio-bridge
    restart: unless-stopped
    command: sh -c "python -u /app/udp_radio_bridge.py"
    volumes:
      - ./meshtasticd-config/udp_radio_bridge.py:/app/udp_radio_bridge.py:ro
    networks:
      - meshtastic
    depends_on:
      - meshtasticd-rx
      - meshtasticd-tx
  ```

**Verification steps** (requires Docker installed first - see Section 1 above):
```bash
# Install Docker if not already present
sudo apt install docker.io docker-compose-plugin

# Launch stack
cd /home/matteo/meshtasticator
docker compose up -d --build

# Provision both simulated nodes
.venv/bin/python3 meshtasticd-config/provision_nodes.py --sim

# Terminal 1: Shelly simulator
.venv/bin/python3 meshtasticd-config/shelly_simulator.py --id shelly1-sim01

# Terminal 2: MQTT bridge on RX node (port 4404)
.venv/bin/python3 meshtasticd-config/mqtt_bridge.py --mesh-port 4404

# Terminal 3: Signed command from TX node (port 4406)
.venv/bin/python3 meshtasticd-config/send_control_cmd.py --mesh-port 4406 --target shelly1-sim01 --action ON
```
Confirm: TX packet is relayed over simulated RF to RX -> `mqtt_bridge.py`
validates HMAC + sequence -> publishes to Mosquitto -> `shelly_simulator.py`
toggles state -> ACK is relayed back to TX -> `send_control_cmd.py` prints
"🎉 Status ACK Received via Meshtastic!". Also test failure paths with
`--bad-sig` and `--replay` flags on `send_control_cmd.py` to confirm the
gateway silently drops them (no ACK received, timeout message printed).

---

### Phase 3: Technical Debt Refactor in Discrete Radio Simulator Core

**Goal**: Address long-standing `TODO`s that affect maintainability and
correctness of the discrete-event simulator (not blocking, lower priority than
Phases 1-2).

**Files to modify**:
- `lib/phy.py`:
  - Refactor `zero_link_budget(dist)` and `zero_link_budget_with_gain(dist,
    gain)` (and `MAXRANGE = rootFinder(zero_link_budget, 1500)` at module load
    time) to accept an explicit `conf` parameter instead of relying on the
    module-global `conf = CONFIG` set at import time. This matters because
    tests/scripts that mutate a `Config()` instance separately from the global
    `CONFIG` singleton currently get incorrect results from these functions.
  - Implement the `wide_lora` region bandwidth adjustment noted in the TODO at
    `lib/config.py:318` (the `bw` parameter should change based on the
    region's `wide_lora` setting; currently unimplemented).
- `lib/discrete_event_sim.py`:
  - Optimize the O(packets * nodes) collision/sensed counting loops (around
    line 67-68) to use per-node counters accumulated during the simulation
    instead of a full post-hoc scan.

**Verification**:
```bash
cd /home/matteo/meshtasticator
.venv/bin/python3 -m unittest discover tests -v
```
Pay special attention to `tests/test_discrete_event_sim.py` -
`test_discrete_sim_ten_nodes` and `test_sim_does_not_change_config`, which
assert exact hardcoded simulation result values and that `Config` objects are
not mutated by a simulation run. If refactoring changes any computed values,
either it's an unintended regression (fix it) or an intentional correction
(update the hardcoded expected values in the test with a clear comment
explaining why).

---

## 3. Quick Reference: Resuming Work

```bash
cd /home/matteo/meshtasticator
source .venv/bin/activate       # or just call .venv/bin/python3 / .venv/bin/pip directly
python -m unittest discover tests -v
```

Ask Cline: **"Read RESUME_PLAN.md and implement Phase 2 (simulated RF UDP
cross-routing bridge for the Docker multi-node stack)."** (Phase 1 - the unit
test suite for the MQTT bridge and Shelly simulator - is already done; see
the Phase 1 section above.)
