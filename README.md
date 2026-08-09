# Meshtasticator

A comprehensive simulation suite for [Meshtastic](https://meshtastic.org/). 

Meshtasticator supports **two complementary types of simulators**:
1. 📡 **Discrete-Event & Interactive Radio Simulator**: Python-based radio layer simulation for analyzing mesh network performance, node reachability, hop limits, and packet schedules.
2. 🌐 **Web Simulator & Interactive Web UI**: Docker-based simulation running the real native `meshtasticd` daemon with a full interactive Meshtastic Web Client (`meshtastic-web`).

---

## 📡 1. Discrete-Event & Radio Simulator

The discrete-event simulator mimics the LoRa radio section of device software in order to understand its working, assess performance scenarios, and evaluate protocol scalability.

- **Discrete-Event Guide**: See [DISCRETE_EVENT_SIM.md](DISCRETE_EVENT_SIM.md) for usage instructions.
- **Interactive Guide**: See [INTERACTIVE_SIM.md](INTERACTIVE_SIM.md) for multi-node hardware simulation.

### Capabilities
- **Schedule & Placement Plots**: Generates visual plots of node placements and overlapping packet schedules.
- **Scalability Metrics**: Analyzes packet reachability and usefulness over hundreds of simulation runs with varying hop limits.

![](/img/placement_schedule.png)

---

## 🌐 2. Web UI & Daemon Simulator (`meshtasticd` + `meshtastic-web`)

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

## 🧪 Tests & Setup

### Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running Unit Tests
```bash
python3 -m unittest
```

---

## 📄 License & References
Part of the source code is based on the work in [1], which eventually stems from [2]. The LoRaSim library from [2] can be found [here](https://www.lancaster.ac.uk/scc/sites/lora/lorasim.html).

This work is licensed under a [Creative Commons Attribution 4.0 International License](https://creativecommons.org/licenses/by/4.0/). 

### References
1. [S. Spinsante, L. Gioacchini and L. Scalise, "A novel experimental-based tool for the design of LoRa networks," 2019 II Workshop on Metrology for Industry 4.0 and IoT (MetroInd4.0&IoT), 2019, pp. 317-322, doi: 10.1109/METROI4.2019.8792833.](https://ieeexplore.ieee.org/document/8792833)
2. [Martin C. Bor, Utz Roedig, Thiemo Voigt, and Juan M. Alonso, "Do LoRa Low-Power Wide-Area Networks Scale?", In Proceedings of the 19th ACM International Conference on Modeling, Analysis and Simulation of Wireless and Mobile Systems (MSWiM '16), 2016.](https://doi.org/10.1145/2988287.2989163)
