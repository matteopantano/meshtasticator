# AGENTS.md - Antigravity Instructions for Meshtasticator

This repository is **Meshtasticator**: a multi-node simulator, real-time web UI, hardware deployment suite, and serial/web control toolkit for Meshtastic LoRa mesh networks and IoT integrations (including Shelly Smart Relay MQTT control).

---

## 1. Security & Secrets Policy (Strict)

> [!IMPORTANT]
> **This repository is public.** Never commit or log real credentials, passwords, PSKs, or private keys.

1. **Environment Variables**: All sensitive credentials (Wi-Fi passwords, private MQTT credentials, HMAC secrets) are loaded dynamically via `.env` (using `python-dotenv`).
2. **Template File**: Only `.env.example` should be committed. Actual `.env`, `*.key`, `*.psk`, and `*.local.yaml` files are excluded by `.gitignore`.
3. **Safe Defaults**: Example scripts use mock IDs (e.g. `shelly1-sim01`) and fallback development keys.
4. **Shared Config Source**: The repository root `.env` is the shared source of truth for common settings (`CONTROL_SECRET`, `LORA_REGION`, node defaults). Subprojects such as `meshtastic-web-gateway/` may carry a local `.env` only for overrides like `MESHTASTIC_DEVICE` or `WEB_PORT`.

---

## 2. Project Architecture & Components

```
Meshtasticator/
├── docker-compose.yaml             # Docker multi-container stack (RX, TX, RF bridge, ws-proxies, web UI, mosquitto)
├── requirements.txt               # Python package dependencies
├── .env.example                   # Environment configuration template
├── README.md                      # Main project entrypoint and quick reference
├── ROADMAP.md                     # Project status, verification notes, and roadmap
├── meshtastic-web-gateway/        # FastAPI web UI for USB/serial-connected Meshtastic nodes
│
├── docs/                          # Detailed architecture & feature documentation
│   ├── 01_discrete_event_radio_simulator.md   # Python radio-layer discrete event simulator
│   ├── 03_interactive_multi_node_simulator.md # Interactive multi-process native binary simulator
│   ├── 04_web_ui_and_daemon_simulator.md      # Web UI & Docker meshtasticd architecture
│   ├── 05_multi_node_iot_mqtt_pipeline.md     # Payload specification, security checks, and simulator documentation
│   └── 07_physical_hardware_deployment.md     # Physical ESP32 + Meshtastic + Shelly deployment guide
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
│   ├── send_control_cmd.py        # Secure HMAC signed command transmitter client (TCP or serial)
│   ├── shelly_simulator.py        # Shelly relay emulator (Gen 1, Gen 2 RPC & Gen 2+ command/switch:0 topics)
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

### Step 5: Serial Web Gateway (optional)
```bash
# Lightweight FastAPI UI for a USB/serial-connected Meshtastic node
pip install -r meshtastic-web-gateway/requirements.txt
uvicorn app.main:app --app-dir meshtastic-web-gateway --host 0.0.0.0 --port 8000
```

---

## 4. Testing & Validation

```bash
# Run unit tests
python3 -m unittest discover tests -v

# Run web gateway tests
python3 -m pytest meshtastic-web-gateway/tests -q
```

### Current hardware validation status
- Phase 5 verified the **ESP32 firmware path on real hardware**: signed commands were accepted by the firmware and successfully actuated a real Shelly device without `mqtt_bridge.py` in the loop.
- Full LoRa TX → RX → ACK-back validation with the final physical node mix remains follow-up work.
- nRF52-based nodes such as the RAK4630/RAK4631 family should be treated as **non-Wi-Fi** boards for deployment planning.

---

## 5. Development Conventions
- **Formatting & Style**: Follow PEP 8 for Python. Use descriptive naming and clean type annotations where helpful.
- **Git Commits**: Commit changes with clear, concise messages. Ensure `git status` is clean and no secrets or local artifacts are staged.
