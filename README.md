# Meshtasticator

A comprehensive simulation, testbed, and IoT-integration suite for
[Meshtastic](https://meshtastic.org/) LoRa mesh networks.

## What's in this repo

| # | Capability | Quickstart | Full docs |
| :-- | :-- | :-- | :-- |
| 1 | 📡 **Discrete-Event Radio Simulator** — Python radio-layer simulation for mesh performance, reachability & scalability analysis | [Jump to §1](#-1-discrete-event-radio-simulator) | [docs/01_discrete_event_radio_simulator.md](docs/01_discrete_event_radio_simulator.md) |
| 2 | 📊 **Batch Simulation & Metrics** — run many simulations across parameter sweeps and plot results | [Jump to §2](#-2-batch-simulation--scalability-metrics) | [`batchSim.py`](batchSim.py), [`plotExample.py`](plotExample.py) |
| 3 | 🖥️ **Interactive Multi-Node Simulator** — runs real Meshtastic native binaries as separate processes over simulated LoRa links | [Jump to §3](#-3-interactive-multi-node-simulator) | [docs/03_interactive_multi_node_simulator.md](docs/03_interactive_multi_node_simulator.md) |
| 4 | 🌐 **Web UI & Daemon Simulator** — Dockerized `meshtasticd` + official `meshtastic-web` client | [Jump to §4](#-4-web-ui--daemon-simulator-meshtasticd--meshtastic-web) | [docs/04_web_ui_and_daemon_simulator.md](docs/04_web_ui_and_daemon_simulator.md) |
| 5 | 🔗 **Multi-Node Docker Testbed & IoT/MQTT Pipeline** — two-node mesh + secure Meshtastic ➔ MQTT ➔ Shelly relay control | [Jump to §5](#-5-multi-node-testbed--iotmqtt-integration) | [docs/05_multi_node_iot_mqtt_pipeline.md](docs/05_multi_node_iot_mqtt_pipeline.md) |
| 6 | 🔌 **Standalone ESP32 Gateway Firmware** — replaces the Python MQTT bridge on real hardware (SoftAP + embedded broker + native HMAC) | [Jump to §6](#-6-standalone-esp32-gateway-firmware) | [firmware/esp32-gateway/README.md](firmware/esp32-gateway/README.md) |
| 7 | 🔧 **Physical Hardware Deployment** — deploy the whole pipeline on real Meshtastic nodes + ESP32 + Shelly, zero cloud/computer required | [Jump to §7](#-7-physical-hardware-deployment) | [docs/07_physical_hardware_deployment.md](docs/07_physical_hardware_deployment.md) |
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

![](img/placement_schedule.png)

- **Full usage guide** (custom modem/pathloss/period configs, `--from-file`
  replay, etc.): [docs/01_discrete_event_radio_simulator.md](docs/01_discrete_event_radio_simulator.md)

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

![](img/reachability_hops.png)

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

![](img/route_plot2.png)

- **Full usage guide** (all commands, scripted mode, pathloss models):
  [docs/03_interactive_multi_node_simulator.md](docs/03_interactive_multi_node_simulator.md)

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

- **Detailed Technical Guide**: See [docs/04_web_ui_and_daemon_simulator.md](docs/04_web_ui_and_daemon_simulator.md) for proxy framing details and architecture notes.

---

## 🔗 5. Multi-Node Testbed & IoT/MQTT Integration

`docker-compose.yaml` runs a full **two-node simulated mesh testbed** (`meshtasticd-rx` +
`meshtasticd-tx`, each with its own `ws-proxy`/Web UI) bridged by a
simulated RF cross-routing service (`sim-radio-bridge`), plus an embedded Mosquitto
MQTT broker. This demonstrates and tests a secure Meshtastic ➔ MQTT ➔
Shelly smart-relay control pipeline: HMAC-SHA256 signed commands,
anti-replay (monotonic sequence) protection, and sender-Node-ID
whitelisting.

> [!IMPORTANT]
> **Prerequisites**: Make sure your Python virtual environment is activated (`source .venv/bin/activate`) and the Docker stack is running before provisioning nodes or running Python bridges.

### Step-by-Step Quickstart

1. **Copy Environment & Start the Docker Multi-Node Stack**:
   ```bash
   cp .env.example .env
   docker compose up -d
   ```
   *(This launches both mesh nodes on ports `4404`/`4406`, the RF bridge, the MQTT broker on `1883`, and Web UIs on `http://localhost:8080` & `http://localhost:8081`)*

2. **Auto-Provision the Simulated Mesh Nodes**:
   ```bash
   python3 meshtasticd-config/provision_nodes.py --sim
   ```
   *(Sets node owners, LoRa regions, and native MQTT client pointing to the broker)*

3. **Start the Shelly Relay Simulator & Meshtastic-to-MQTT Bridge** (in separate terminals):
   ```bash
   # Terminal 1 - Run Shelly smart relay emulator:
   python3 meshtasticd-config/shelly_simulator.py --id shelly1-sim01

   # Terminal 2 - Run Meshtastic-to-MQTT security bridge:
   python3 meshtasticd-config/mqtt_bridge.py --mesh-port 4404
   ```

4. **Send a Signed Control Command from the TX Node**:
   ```bash
   python3 meshtasticd-config/send_control_cmd.py \
     --mesh-port 4406 --target shelly1-sim01 --action ON
   ```
   *(Watch the RF bridge relay the packet from TX to RX, verify HMAC & sequence, publish to MQTT, toggle the Shelly relay, and relay the signed status ACK back to TX!)*

- **Full pipeline design, security spec, and hybrid-hardware testing guide**: see [docs/05_multi_node_iot_mqtt_pipeline.md](docs/05_multi_node_iot_mqtt_pipeline.md).

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
computer required at runtime**: it hosts its own Wi-Fi SoftAP (`ESP32-Hub` @
`192.168.4.1`), runs an embedded `TinyMqtt` broker on port `1883`, and
executes the HMAC-SHA256 signature verification directly in C++ on the
microcontroller.

Provision an RX node over USB to join the ESP32 Hub:
```bash
python3 meshtasticd-config/provision_nodes.py \
  --serial /dev/ttyUSB0 --role rx --wifi-ssid "ESP32-Hub" \
  --wifi-pass "YourSecureWifiPass123" --mqtt-host "192.168.4.1"
```

3. **Connect Shelly Relay**: Join a real Shelly relay to the ESP32's Wi-Fi (`ESP32-Hub`) and point its MQTT client at `192.168.4.1:1883`.

- **Full bill of materials, wiring diagram, and step-by-step guide**: see
  [docs/07_physical_hardware_deployment.md](docs/07_physical_hardware_deployment.md).

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
