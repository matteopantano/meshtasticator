# Meshtasticator

A comprehensive simulation, testbed, and IoT-integration suite for
[Meshtastic](https://meshtastic.org/) LoRa mesh networks.

## What's in this repo

| # | Capability | Quickstart | Full docs |
| :-- | :-- | :-- | :-- |
| 1 | 📡 **Discrete-Event Radio Simulator** — Python radio-layer simulation for mesh performance, reachability & scalability analysis | [Jump to §1](#-1-discrete-event-radio-simulator) | [DISCRETE_EVENT_SIM.md](DISCRETE_EVENT_SIM.md) |
| 2 | 📊 **Batch Simulation & Metrics** — run many simulations across parameter sweeps and plot results | [Jump to §2](#-2-batch-simulation--scalability-metrics) | [`batchSim.py`](batchSim.py), [`plotExample.py`](plotExample.py) |
| 3 | 🖥️ **Interactive Multi-Node Simulator** — runs real Meshtastic native binaries as separate processes over simulated LoRa links | [Jump to §3](#-3-interactive-multi-node-simulator) | [INTERACTIVE_SIM.md](INTERACTIVE_SIM.md) |
| 4 | 🌐 **Web UI & Daemon Simulator** — Dockerized `meshtasticd` + official `meshtastic-web` client | [Jump to §4](#-4-web-ui--daemon-simulator-meshtasticd--meshtastic-web) | [CLAUDE.md](CLAUDE.md) |
| 5 | 🔗 **Multi-Node Docker Testbed & IoT/MQTT Pipeline** — two-node mesh + secure Meshtastic ➔ MQTT ➔ Shelly relay control | [Jump to §5](#-5-multi-node-testbed--iotmqtt-integration) | [MQTT_SHELLY_SIMULATION.md](MQTT_SHELLY_SIMULATION.md) |
| 6 | 🔌 **Standalone ESP32 Gateway Firmware** — replaces the Python MQTT bridge on real hardware (SoftAP + embedded broker + native HMAC) | [Jump to §6](#-6-standalone-esp32-gateway-firmware) | [firmware/esp32-gateway/README.md](firmware/esp32-gateway/README.md) |
| 7 | 🔧 **Physical Hardware Deployment** — deploy the whole pipeline on real Meshtastic nodes + ESP32 + Shelly, zero cloud/computer required | [Jump to §7](#-7-physical-hardware-deployment) | [HARDWARE_DEPLOYMENT_GUIDE.md](HARDWARE_DEPLOYMENT_GUIDE.md) |
| 8 | 🧪 **Test Suite** — 62 unit tests covering the simulator core and the IoT security pipeline | [Jump to §8](#-8-tests--environment-setup) | [`tests/`](tests/) |

---

## 📡 1. Discrete-Event Radio Simulator

Mimics the LoRa radio section of the Meshtastic device software (based on
Meshtastic 2.1) to analyze mesh network performance, node reachability,
hop limits, and packet schedules — entirely in Python, no hardware or
Docker required.

### Quickstart
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Randomly place 10 nodes and run one simulation:
python3 loraMesh.py 10

# Or place nodes interactively on a plot (no argument):
python3 loraMesh.py

# Headless/CI mode (no Tk/Matplotlib GUI):
python3 loraMesh.py 10 --no-gui
```
Generates visual plots of node placement and overlapping packet schedules.

![](/img/placement_schedule.png)

- **Full usage guide** (custom modem/pathloss/period configs, `--from-file`
  replay, etc.): [DISCRETE_EVENT_SIM.md](DISCRETE_EVENT_SIM.md)

---

## 📊 2. Batch Simulation & Scalability Metrics

Runs many repetitions of the discrete-event simulator across a set of
parameters (e.g. number of nodes) and plots aggregated metrics like packet
reachability and usefulness vs. hop limit.

### Quickstart
```bash
python3 batchSim.py
```
Results are saved under `out/report/` for later analysis; see
[`plotExample.py`](plotExample.py) for a sample plotting script. Edit
`batchSim.py` directly to sweep your own parameters.

![](/img/reachability_hops.png)

---

## 🖥️ 3. Interactive Multi-Node Simulator

Runs the real [Linux native Meshtastic firmware](https://meshtastic.org/docs/software/linux-native)
as multiple OS processes, connected over simulated LoRa links based on
each node's simulated position and the configured pathloss model — a
closer-to-real-firmware alternative to the pure-Python discrete-event
simulator.

### Quickstart
```bash
# Using Docker to fetch the native firmware image (simplest):
pip3 install docker
python3 interactiveSim.py 3 -d

# Or using a locally-built PlatformIO 'native' binary:
python3 interactiveSim.py 3 -p /path/to/firmware/.pio/build/native/
```
Then send commands interactively, e.g. `broadcast 0 "hello mesh"`,
`traceroute 0 1`, `plot` to visualize routes and airtime.

![](/img/route_plot2.png)

- **Full usage guide** (all commands, scripted mode, pathloss models):
  [INTERACTIVE_SIM.md](INTERACTIVE_SIM.md)

---

## 🌐 4. Web UI & Daemon Simulator (`meshtasticd` + `meshtastic-web`)

Run the official native C++ Meshtastic daemon (`meshtasticd`) in simulation mode paired with an interactive Web UI (`meshtastic-web`).

### Architecture Overview

```
┌───────────────────────────┐       HTTP (Port 8080)     ┌──────────────────────────────────┐
│  Web Browser              │ <────────────────────────> │  meshtastic-web (NGINX:8080)     │
│  http://localhost:8080    │                            │  - Static Web App                │
│                           │       CORS / REST / WS     │  - Reverse Proxy /api/v1/         │
│                           │ <────────────────────────> └─────────────────┬────────────────┘
└───────────────────────────┘                                              │
                                                                           ▼
                                                         ┌──────────────────────────────────┐
                                                         │  ws-proxy (Tornado on Port 4403) │
                                                         │  - Translates 4-byte TCP Headers │
                                                         │  - CORS & REST/WS Queue Bridge   │
                                                         └─────────────────┬────────────────┘
                                                                           │
                                                                           ▼
                                                         ┌──────────────────────────────────┐
                                                         │  meshtasticd (Port 4404 CLI)     │
                                                         │  - Native Linux Meshtastic Daemon│
                                                         └──────────────────────────────────┘
```

### Quickstart (Web Simulator)

1. **Launch the Docker Stack**:
   ```bash
   docker compose up -d
   ```

2. **Open the Web UI**:
   Navigate to **`http://localhost:8080`** in your browser. The Web UI connects automatically to the simulated node.

3. **Manage via Python CLI**:
   Interact directly with the simulated node using the included Python CLI on port `4404`:
   ```bash
   .venv/bin/meshtastic --host localhost:4404 --info
   .venv/bin/meshtastic --host localhost:4404 --set lora.region US
   ```

- **Detailed Technical Guide**: See [CLAUDE.md](CLAUDE.md) for proxy framing details and architecture notes.

---

## 🔗 5. Multi-Node Testbed & IoT/MQTT Integration

`docker-compose.yaml` also runs a **two-node mesh testbed** (`meshtasticd-rx` +
`meshtasticd-tx`, each with its own `ws-proxy`/Web UI) bridged by a
simulated RF cross-routing service (`sim-radio-bridge`), plus a Mosquitto
MQTT broker. This demonstrates and tests a secure Meshtastic ➔ MQTT ➔
Shelly smart-relay control pipeline: HMAC-SHA256 signed commands,
anti-replay (monotonic sequence) protection, and sender-Node-ID
whitelisting.

### Quickstart
```bash
# 1. Launch the full stack (2 mesh nodes, RF bridge, MQTT broker, Web UIs):
cp .env.example .env
docker compose up -d

# 2. Auto-provision both simulated nodes (names, region, native MQTT client):
.venv/bin/python3 meshtasticd-config/provision_nodes.py --sim

# 3. In separate terminals, start the Shelly simulator and the security bridge:
.venv/bin/python3 meshtasticd-config/shelly_simulator.py --id shelly1-sim01
.venv/bin/python3 meshtasticd-config/mqtt_bridge.py --mesh-port 4404

# 4. Send a signed control command from the TX node and watch the ACK:
.venv/bin/python3 meshtasticd-config/send_control_cmd.py \
  --mesh-port 4406 --target shelly1-sim01 --action ON
```
Web UIs: RX node at `http://localhost:8080`, TX node at `http://localhost:8081`.

- **Full pipeline design, security spec, and hybrid-hardware testing
  guide**: see [MQTT_SHELLY_SIMULATION.md](MQTT_SHELLY_SIMULATION.md).

---

## 🔌 6. Standalone ESP32 Gateway Firmware

`firmware/esp32-gateway/` is a self-contained Arduino/PlatformIO sketch
that replaces the Python `mqtt_bridge.py` runtime for physical, non-Docker
deployments: it hosts its own Wi-Fi SoftAP (`Mesh-Gateway` @
`192.168.4.1`), an embedded MQTT broker (`TinyMqtt`), and performs the same
HMAC-SHA256 + anti-replay + whitelist security checks natively via
`mbedtls`.

### Quickstart
```bash
cd firmware/esp32-gateway
pio run                  # build
pio run -t upload        # flash to an ESP32 over USB
pio device monitor       # serial monitor at 115200 baud
```

- **Full wiring, config, flashing & real-Shelly connection guide**: see
  [firmware/esp32-gateway/README.md](firmware/esp32-gateway/README.md).

---

## 🔧 7. Physical Hardware Deployment

Deploy the entire secure control pipeline on real Meshtastic radios, an
ESP32 hub, and a real Shelly relay — with **zero cloud services and zero
computer required at runtime** once provisioned.

### Quickstart
```bash
# 1. Flash firmware/esp32-gateway/ to your ESP32 hub (see §6 above).

# 2. Provision your physical Meshtastic nodes over USB in one command each:
.venv/bin/python3 meshtasticd-config/provision_nodes.py \
  --serial /dev/ttyUSB0 --role rx --wifi-ssid "Mesh-Gateway" \
  --wifi-pass "YourSecureWifiPass123" --mqtt-host "192.168.4.1"

.venv/bin/python3 meshtasticd-config/provision_nodes.py --serial /dev/ttyUSB1 --role tx

# 3. Join a real Shelly relay to the ESP32's Wi-Fi and point its MQTT
#    client at 192.168.4.1:1883 (see the full guide for exact steps).
```

- **Full bill of materials, wiring diagram, and step-by-step guide**: see
  [HARDWARE_DEPLOYMENT_GUIDE.md](HARDWARE_DEPLOYMENT_GUIDE.md).

---

## 🧪 8. Tests & Environment Setup

### Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running Unit Tests
```bash
python3 -m unittest discover tests -v
```
62 tests cover the discrete-event simulator core (physics/PHY, MAC,
routing, node behavior) as well as the IoT security pipeline
(`tests/test_mqtt_bridge.py`, `tests/test_shelly_simulator.py`) — the
latter run with pure Python mocks, so no Docker/MQTT broker/hardware is
required to validate the HMAC/anti-replay logic.

---

## 📄 License & References
Part of the source code is based on the work in [1], which eventually stems from [2]. The LoRaSim library from [2] can be found [here](https://www.lancaster.ac.uk/scc/sites/lora/lorasim.html).

This work is licensed under a [Creative Commons Attribution 4.0 International License](https://creativecommons.org/licenses/by/4.0/). 

### References
1. [S. Spinsante, L. Gioacchini and L. Scalise, "A novel experimental-based tool for the design of LoRa networks," 2019 II Workshop on Metrology for Industry 4.0 and IoT (MetroInd4.0&IoT), 2019, pp. 317-322, doi: 10.1109/METROI4.2019.8792833.](https://ieeexplore.ieee.org/document/8792833)
2. [Martin C. Bor, Utz Roedig, Thiemo Voigt, and Juan M. Alonso, "Do LoRa Low-Power Wide-Area Networks Scale?", In Proceedings of the 19th ACM International Conference on Modeling, Analysis and Simulation of Wireless and Mobile Systems (MSWiM '16), 2016.](https://doi.org/10.1145/2988287.2989163)
