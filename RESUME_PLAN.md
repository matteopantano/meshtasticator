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
   - ✅ **Docker is now installed** on this machine (confirmed by user in a
     prior session). Phase 2 below (simulated RF TCP cross-routing bridge,
     `meshtasticd-config/sim_rf_bridge.py`) can be fully implemented AND
     verified end-to-end with `docker compose up -d --build`. The full
     technical design (protocol, ports, exact protobuf fields) has been
     finalized this session - see the "Why UDP/multicast is a dead end",
     "Critical architecture correction", "Exact protobuf relay mechanics",
     and "Implementation steps" subsections under Phase 2 below. **Nothing
     has been implemented yet** (no `sim_rf_bridge.py` file exists, and
     `docker-compose.yaml` does not yet have the `sim-radio-bridge`
     service) - next session should go straight to Phase 2's
     "Implementation steps" and write the code.

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

### Phase 2 - ✅ DONE: Simulated RF TCP Cross-Routing Bridge for Docker Multi-Node Stack

**Goal**: Enable `meshtasticd-tx` and `meshtasticd-rx` (in separate Docker
containers) to exchange simulated LoRa RF traffic, which Docker's default
bridge network does not provide automatically since `meshtasticd -s`
(`SimRadio`) has no radio-layer networking of its own. Was tracked as
`🟡 In Debugging` in `MQTT_SHELLY_SIMULATION.md`; now `✅ Verified`.

**Status**: Completed and verified end-to-end this session.
`meshtasticd-config/sim_rf_bridge.py` was implemented exactly per the
"Exact protobuf relay mechanics" and "Implementation steps" design below,
and the `sim-radio-bridge` service was added to `docker-compose.yaml`. Full
verification was run with `docker compose up -d --build`,
`provision_nodes.py --sim`, `shelly_simulator.py --id shelly1-sim01`,
`mqtt_bridge.py --mesh-port 4404`, and `send_control_cmd.py --mesh-port
4406 --target shelly1-sim01 --action ON` - the TX packet was relayed over
the bridge to RX, the gateway validated it and published to Mosquitto, the
Shelly simulator toggled state, and the ACK was relayed back to TX,
printing `🎉 Status ACK Received via Meshtastic!`. `--bad-sig` and
`--replay` were confirmed to be silently dropped (timeout, no ACK). The
full test suite remained green: `.venv/bin/python3 -m unittest discover
tests -v` → **62 tests, OK**.

**Important bug found and fixed during verification**: the first
implementation attempt used two independent per-direction anti-loop caches
(`seen_tx_to_rx` / `seen_rx_to_tx`). This let a node's own normal
mesh-flood rebroadcast of an already-relayed packet id bounce straight back
to the original sender, causing the receiving gateway to see the same
command twice and reject the second copy as a replay (`seq <=
last_seen_seq`) - which silently ate the ACK path on the first end-to-end
run. The fix was to use a **single anti-loop cache shared across both
directions** in `sim_rf_bridge.py` (see the `seen` variable in `main()`),
so a given `(from, id)` is never relayed back the opposite way once it has
been relayed once, in either direction. `MQTT_SHELLY_SIMULATION.md`
section 5 documents this explicitly for future reference.

**Documentation updated**: `MQTT_SHELLY_SIMULATION.md` status table entry
changed to `✅ Verified`, plus a new "Section 5: Simulated RF TCP
Cross-Routing Bridge" was added there with the loop-prevention explanation
and instructions for pointing `mqtt_bridge.py` at a physical ESP32/LAN MQTT
broker via `--mqtt-host <ESP32_IP> --mqtt-port 1883` (no code changes
needed, already supported by existing `argparse` flags).

**Historical design notes below (kept for reference)** - all findings held
up during implementation, no design changes were needed:

**Files to create/modify**:
- `meshtasticd-config/sim_rf_bridge.py` (new - **use this name, not
  `udp_radio_bridge.py`**; there is no UDP involved, naming it that would be
  misleading)
- `docker-compose.yaml` (add a `sim-radio-bridge` service)
- `MQTT_SHELLY_SIMULATION.md` (update status table entry to `✅ Verified` once
  confirmed working, plus document how to point `mqtt_bridge.py` at a
  physical ESP32/LAN MQTT broker)

#### Why UDP/multicast is a dead end (confirmed this session, don't re-check)

`meshtasticd -s` uses `SimRadio` (`src/platform/portduino/SimRadio.{h,cpp}`),
confirmed via `curl` to raw.githubusercontent.com against
`meshtastic/firmware` master (prefer plain `curl` over the
`fetch_web_content` tool for raw GitHub file fetches - the tool's extraction
sometimes truncates/omits large code blocks silently, whereas `curl` gives
the full byte-exact file to grep/sed through). `SimRadio::startSend()` just
calls `service->sendToPhone(p)` - it loops the packet back out over the
**same node's own phone/API TCP connection only**, re-framed as a
`SIMULATOR_APP` packet (portnum 69). `SimRadio` has **zero UDP/socket code**.
The separate `UdpMulticastHandler` real-UDP-multicast feature (group
`224.0.0.69:4403`, gated by `#ifdef HAS_UDP_MULTICAST`) is completely
unrelated to `-s` sim mode - it's for physically separate real nodes on a LAN
and is never consulted by `SimRadio`. **Conclusion: there is no UDP mechanism
to investigate for this use case at all.** The only way to relay
`SIMULATOR_APP` events between two `meshtasticd -s` containers is an external
TCP-level relay that speaks the existing phone/API protobuf protocol on each
side - which is exactly what `sim_rf_bridge.py` must do.

#### Critical architecture correction: which TCP port to connect to (confirmed this session)

The original plan assumed the bridge would open two new raw TCP connections
straight to `meshtasticd-rx:4403` and `meshtasticd-tx:4403`. **This is wrong
and would conflict with the existing `ws-proxy-rx`/`ws-proxy-tx` containers.**
Confirmed via `curl` of `meshtastic/firmware`'s `src/mesh/api/ServerAPI.h`:

> `APIServerPort`... "we currently only allow **one open TCP connection at a
> time**, because we depend on the `loop()` call in this class to delegate to
> the worker. Once coroutines are implemented we can relax this restriction."

Each `meshtasticd -s` process's port `4403` accepts only **one** client
connection total. In the current `docker-compose.yaml`, that single slot on
`meshtasticd-rx:4403` is already permanently held by `ws-proxy-rx`'s
background `meshtastic_tcp_loop()` task (same for `meshtasticd-tx:4403` /
`ws-proxy-tx`). If `sim_rf_bridge.py` also tried to connect directly to
`:4403`, it would race/conflict with the proxy that's already connected.

**The fix**: `proxy.py` already solves exactly this "multiple TCP clients,
one upstream connection" problem for its own purposes - it exposes a **TCP
multiplexer on port 4404** (`TCPClientProtocol`/`tcp_clients` set in
`proxy.py`): any bytes written by a mux client are forwarded to the single
real upstream connection, and any raw framed bytes coming from the real
device are broadcast to **all** connected mux clients. This is precisely why
`mqtt_bridge.py` and `send_control_cmd.py` already connect to port
`4404`/`4406` (the *mux* ports) rather than `4403` directly.
`sim_rf_bridge.py` must do the same: on the Docker network, connect to
**`ws-proxy-rx:4404`** and **`ws-proxy-tx:4404`** (the container-internal mux
port both proxy containers listen on - not the host-mapped `4404`/`4406`,
those are only for host-side tools), never to `meshtasticd-rx:4403` /
`meshtasticd-tx:4403` directly.

#### Exact protobuf relay mechanics (confirmed this session)

Traced the full round-trip through `meshtastic/firmware` master via `curl`:

1. When a `meshtasticd -s` node transmits, `SimRadio::startSend()` builds a
   `meshtastic_Compressed` message (fields: `portnum`, `data`) containing the
   *original* portnum + payload bytes, serializes that into
   `p->decoded.payload`, sets `p->decoded.portnum = SIMULATOR_APP` (enum
   value **69** - confirmed via
   `.venv/bin/python3 -c "from meshtastic.protobuf import portnums_pb2; print(portnums_pb2.PortNum.SIMULATOR_APP)"` → `69`),
   then calls `service->sendToPhone(p)`. This arrives at whichever client is
   connected to that node's port 4403 (i.e. the corresponding `ws-proxy-*`
   container) as a framed `FromRadio` protobuf whose `.packet` is this
   `MeshPacket` (with `decoded.portnum == 69`).
2. To make the *other* node "receive" this over simulated RF, send a
   `ToRadio` protobuf (`toRadio.packet.CopyFrom(that_same_MeshPacket)`) into
   the other node's mux connection. `PhoneAPI::handleToRadio()` on that node
   receives it, calls `MeshService::handleToRadio(p)`, which contains exactly
   this gate (confirmed via `curl` of `src/mesh/MeshService.cpp`):
   ```cpp
   if (SimRadio::instance && p.decoded.portnum == meshtastic_PortNum_SIMULATOR_APP) {
       SimRadio::instance->unpackAndReceive(p);
   }
   ```
   `SimRadio::unpackAndReceive()` unwraps the `Compressed` payload back to
   the original portnum/payload and calls `startReceive()` - i.e. the other
   node genuinely believes it just received this packet over its LoRa chip
   (log line `"Lora RX"` from `SimRadio::handleReceiveInterrupt()`), and it
   flows into `deliverToReceiver()` → `Router` → `meshtastic.receive` pubsub
   → exactly what `mqtt_bridge.py`/`send_control_cmd.py` already listen for.
3. **Python-side field access** (already confirmed against the installed
   `meshtastic` package in `.venv`, no guesswork needed):
   - `mesh_pb2.FromRadio` has a `.packet` field of type
     `meshtastic.protobuf.MeshPacket` (same for `mesh_pb2.ToRadio.packet`).
   - Check `from_radio.packet.decoded.portnum == 69` (import
     `from meshtastic.protobuf import mesh_pb2, portnums_pb2` and compare to
     `portnums_pb2.PortNum.SIMULATOR_APP`). There is no
     `meshtastic_MeshPacket_encrypted_tag` check needed/relevant here - that
     was a wrong guess in the prior session's notes; simulated packets are
     always in the `decoded` oneof branch with portnum 69, never `encrypted`.
   - Relay by literally copying the whole `MeshPacket`:
     `to_radio = mesh_pb2.ToRadio(); to_radio.packet.CopyFrom(from_radio.packet)`,
     then `to_radio.SerializeToString()`, then wrap with the same 4-byte
     `START1(0x94) START2(0xC3) lenHi lenLo` header used everywhere else in
     this repo (`stream_interface.py` `START1`/`START2`/`HEADER_LEN`,
     mirrored already in `proxy.py`).
   - Framing/parsing loop: reuse the exact buffering algorithm already in
     `proxy.py`'s `meshtastic_tcp_loop()` (scan for `START1,START2`, read
     2-byte big-endian length, wait for full frame, slice it off) - do not
     reinvent it, just copy the pattern for each of the two mux connections.
4. **Loop-prevention caution**: `PhoneAPI::handleToRadio()` normally
   deduplicates repeated packet IDs from the phone via
   `wasSeenRecently(p.id)`, but that check is explicitly skipped when
   `SimRadio::instance != nullptr` (confirmed via `curl` grep of
   `PhoneAPI.cpp`: `"if the simulator, we should not ignore duplicate
   packets from the phone"`). This is correct for legitimate multi-hop
   rebroadcasts, but means `sim_rf_bridge.py` itself must track which
   `(from, id)` pairs it has already relayed *in which direction* and not
   immediately bounce a packet back to the node it just came from (a simple
   `set()` of recently seen `(from, id)` tuples per direction, expired after
   a few seconds, is sufficient - do not overthink this into full
   mesh-routing logic; the discrete-event simulator in `lib/` already does
   real RF simulation, this bridge only needs to be a dumb store-and-forward
   relay for the two-node Docker demo).

#### Implementation steps (ready to execute, no further research needed)

1. Write `meshtasticd-config/sim_rf_bridge.py`:
   - `asyncio`, module-level `START1 = 0x94`, `START2 = 0xC3`,
     `HEADER_LEN = 4` constants (copy from `proxy.py`).
   - Read target hostnames from env vars with sane defaults, e.g.
     `RX_MUX_HOST=ws-proxy-rx`, `RX_MUX_PORT=4404`, `TX_MUX_HOST=ws-proxy-tx`,
     `TX_MUX_PORT=4404` (all overridable so this also works if container
     names ever change).
   - Two long-lived `asyncio.open_connection()` tasks (one per node), each
     with the same reconnect-with-backoff pattern as
     `proxy.py::meshtastic_tcp_loop()`.
   - On receiving a complete framed `FromRadio` from node A's mux connection:
     decode with `mesh_pb2.FromRadio.FromString(payload)`; if
     `from_radio.HasField("packet")` and
     `from_radio.packet.decoded.portnum == portnums_pb2.PortNum.SIMULATOR_APP`,
     and `(getattr(from_radio.packet, "from"), from_radio.packet.id)` not
     already relayed recently from B→A (anti-loop), then build `ToRadio`,
     frame it, write it to node B's mux writer, and record `(from, id)` as
     relayed A→B.
   - Print clear stdout logs (`[SimRF Bridge] TX -> RX: packet id=... from=... portnum=...`)
     for observability while debugging via `docker compose logs`.
2. Add to `docker-compose.yaml`:
   ```yaml
   sim-radio-bridge:
     image: python:3.11-slim
     container_name: meshtastic-sim-radio-bridge
     restart: unless-stopped
     environment:
       - RX_MUX_HOST=ws-proxy-rx
       - RX_MUX_PORT=4404
       - TX_MUX_HOST=ws-proxy-tx
       - TX_MUX_PORT=4404
     command: sh -c "pip install meshtastic && python -u /app/sim_rf_bridge.py"
     volumes:
       - ./meshtasticd-config/sim_rf_bridge.py:/app/sim_rf_bridge.py:ro
     depends_on:
       - ws-proxy-rx
       - ws-proxy-tx
     networks:
       - meshtastic
   ```
   (`pip install meshtastic` at container start mirrors the existing
   `ws-proxy-*` services' `pip install tornado` pattern - keeps the image
   generic `python:3.11-slim` without a custom Dockerfile/build step. Only
   `meshtastic.protobuf` is actually needed at runtime, but installing the
   full `meshtastic` package is simplest and matches project convention of
   avoiding extra Dockerfiles.)
3. Verify success by tailing
   `docker compose logs -f meshtasticd-rx meshtasticd-tx sim-radio-bridge`
   while running `send_control_cmd.py` from the TX side, watching for
   `"Lora RX"` / `"enqueuing for send"` log lines from `meshtasticd-rx` to
   confirm the packet actually crossed over from TX to RX (not just looped
   back to itself), plus the bridge's own `"TX -> RX"` relay log line.

#### Hardware follow-up: pointing `mqtt_bridge.py` at a physical ESP32/LAN MQTT broker

Already supported today - no code changes needed here, only verify/document:
`mqtt_bridge.py`'s `argparse` already defines `--mqtt-host` (default
`localhost`) and `--mqtt-port` (default `1883`, type `int`). To point it at a
physical ESP32-hosted broker (or any Mosquitto/broker on the LAN) instead of
the Dockerized `mosquitto-broker`, run e.g.:
```bash
.venv/bin/python3 meshtasticd-config/mqtt_bridge.py \
  --mesh-port 4404 \
  --mqtt-host 192.168.1.50 \
  --mqtt-port 1883
```
This should be spelled out explicitly in `MQTT_SHELLY_SIMULATION.md` (see
Phase 2 files-to-modify list above) as part of closing out this phase.

**Verification steps**:
```bash
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
Finally run `.venv/bin/python3 -m unittest discover tests -v` to confirm the
existing 62 tests are unaffected by the Docker-only bridge addition (it lives
entirely in `meshtasticd-config/`, is not imported by any test, and requires
Docker/`meshtastic` package at runtime only, not at test-collection time).

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

Ask Cline: **"Read RESUME_PLAN.md and continue from Phase 3 (technical debt
refactor in the discrete radio simulator core)."** (Phase 1 - the unit test
suite for the MQTT bridge and Shelly simulator - and Phase 2 - the simulated
RF TCP cross-routing bridge - are both done; see their sections above.)

**Historical status (superseded - Phase 2 is now done, kept for context)**:
Docker is installed and confirmed working on this machine. The full Phase 2
design was finalized and implemented with zero remaining unknowns - no
firmware source research was needed. Key findings (all detailed in their own
subsections under Phase 2 above):
- `SimRadio` (`-s` sim mode) has **no UDP/multicast mechanism at all** - the
  previous session's UDP/multicast investigation was a dead end; skip it
  entirely (see "Why UDP/multicast is a dead end").
- `meshtasticd`'s TCP API port `4403` only accepts **one client connection**
  at a time (confirmed from `firmware/src/mesh/api/ServerAPI.h`), and that
  slot is already permanently occupied by `ws-proxy-rx`/`ws-proxy-tx`. The
  bridge must connect to each proxy's **TCP mux port `4404`**
  (`ws-proxy-rx:4404` / `ws-proxy-tx:4404` on the Docker network) instead of
  `meshtasticd-*:4403` directly (see "Critical architecture correction").
- The exact relay mechanics are fully traced end-to-end: `SIMULATOR_APP`
  portnum is `69`, `MeshService::handleToRadio()` has an explicit
  `SimRadio::instance->unpackAndReceive(p)` gate for it, and the bridge's job
  is simply to copy a received `FromRadio.packet` (with
  `decoded.portnum == 69`) into a `ToRadio.packet` sent to the *other* mux
  connection, framed with the standard `0x94 0xC3` + 2-byte length header
  (see "Exact protobuf relay mechanics").
- **Phase 2 is now fully implemented and verified** (see the "✅ DONE"
  status block at the top of the Phase 2 section above for the full
  end-to-end verification summary, including the shared-anti-loop-cache bug
  fix found during testing). Next session should move on to **Phase 3**
  (technical debt refactor in the discrete radio simulator core, see below).
