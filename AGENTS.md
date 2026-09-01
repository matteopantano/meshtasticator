# AGENTS.md - Antigravity Instructions for Meshtasticator

This repository is **Meshtasticator**: a multi-node simulator, real-time web UI, and hardware deployment suite for Meshtastic LoRa mesh networks and IoT integrations (including Shelly Smart Relay MQTT control).

---

## 1. Security & Secrets Policy (Strict)

> [!IMPORTANT]
> **This repository is public.** Never commit or log real credentials, passwords, PSKs, or private keys.

1. **Environment Variables**: All sensitive credentials (Wi-Fi passwords, private MQTT credentials, HMAC secrets) are loaded dynamically via `.env` (using `python-dotenv`).
2. **Template File**: Only `.env.example` should be committed. Actual `.env`, `*.key`, `*.psk`, and `*.local.yaml` files are excluded by `.gitignore`.
3. **Safe Defaults**: Example scripts use mock IDs (e.g. `shelly1-sim01`) and fallback development keys.

---

## 2. Project Architecture & Components

```
Meshtasticator/
├── docker-compose.yaml             # Docker multi-container stack (RX, TX, RF bridge, ws-proxies, web UI, mosquitto)
├── requirements.txt               # Python package dependencies
├── .env.example                   # Environment configuration template
├── README.md                      # Main project entrypoint and quick reference
│
├── docs/                          # Detailed architecture & feature documentation
│   ├── discrete_event_sim.md      # Python radio-layer discrete event simulator
│   ├── interactive_sim.md         # Interactive multi-process native binary simulator
│   ├── webui_sim.md               # Web UI & Docker meshtasticd architecture
│   ├── mqtt_shelly_simulation.md  # Payload specification, security checks, and simulator documentation
│   ├── hardware_deployment_guide.md # Physical ESP32 + Meshtastic + Shelly deployment guide
│   └── resume_plan.md             # Project status, verification notes, and roadmap
│
├── firmware/
│   └── esp32-gateway/             # Standalone ESP32 C++ Gateway (SoftAP + TinyMqtt + native HMAC)
│
├── meshtasticd-config/
│   ├── config.yaml                # meshtasticd configuration (LoRa region US, generated MAC)
│   ├── mosquitto.conf             # Mosquitto MQTT broker configuration
│   ├── proxy.py                   # Tornado WebSocket / HTTP to meshtasticd TCP bridge + TCP mux (port 4404)
│   ├── sim_rf_bridge.py           # Simulated RF cross-routing bridge between simulated nodes
│   ├── mqtt_bridge.py             # Meshtastic-to-MQTT security gateway (HMAC + anti-replay + ACK)
│   ├── provision_nodes.py         # 1-Click node provisioner (simulated containers or physical USB/Wi-Fi)
│   ├── send_control_cmd.py        # Secure HMAC signed command transmitter client
│   ├── shelly_simulator.py        # Gen 1 & Gen 2 Shelly smart relay emulator over MQTT
│   └── nginx.conf                 # meshtastic-web NGINX reverse-proxy
│
├── lib/                           # Core discrete event simulator library
├── tests/                         # Unit test suite for simulator core & IoT security pipeline
├── batchSim.py                    # Batch simulation runner
├── interactiveSim.py              # Interactive visual GUI simulator
└── loraMesh.py                    # CLI simulator runner
```

---

## 3. Quick Start on a New Machine

### Step 1: Environment Setup
```bash
# 1. Create and activate Python virtual environment (Python 3.10+)
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy environment template
cp .env.example .env
```

### Step 2: Start the Simulation Stack
```bash
# Start RX & TX nodes, RF bridge, WebSocket proxies, Web UI, and Mosquitto MQTT broker
docker compose up -d
```

### Step 3: Web UI Access & Ports
- **Unified Web UI (RX Node)**: `http://localhost:8080` (or `http://127.0.0.1:8080`)
- **Web UI / Proxy (TX Node)**: `http://localhost:8081` (or via proxy port `4405` / `4406`)
- **MQTT Broker**: `localhost:1883`

### Step 4: 1-Click Provisioning & Simulation Scripts
```bash
# Auto-provision simulated nodes (sets names, region, and native MQTT client)
python3 meshtasticd-config/provision_nodes.py --sim

# In separate terminals:
# 1. Run the Shelly smart relay simulator:
python3 meshtasticd-config/shelly_simulator.py --id shelly1-sim01

# 2. Run the Meshtastic-to-MQTT security bridge:
python3 meshtasticd-config/mqtt_bridge.py --mesh-port 4404

# 3. Transmit a signed command:
python3 meshtasticd-config/send_control_cmd.py --mesh-port 4406 --target shelly1-sim01 --action ON
```

---

## 4. Testing & Validation

```bash
# Run unit tests
python3 -m unittest discover tests -v
```

---

## 5. Development Conventions
- **Formatting & Style**: Follow PEP 8 for Python. Use descriptive naming and clean type annotations where helpful.
- **Git Commits**: Commit changes with clear, concise messages. Ensure `git status` is clean and no secrets or local artifacts are staged.
