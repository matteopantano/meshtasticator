# Web UI & Daemon Simulator Documentation

This document explains the architecture, issues encountered, solutions applied, and instructions for running `meshtasticd` alongside `meshtastic-web` using Docker Compose.

---

## 1. System Architecture Overview

The system consists of three main components defined in `docker-compose.yaml`:

```
┌───────────────────────────────┐       HTTP (Static Files)     ┌──────────────────────────────────┐
│  Host Browser                 │ <───────────────────────────> │  meshtastic-web (NGINX:8080)     │
│  (http://localhost:8080)      │                               │  - Serves static Web App         │
│                               │       CORS / REST / WS        │  - Reverse-proxies /api/v1/      │
│                               │ <───────────────────────────> └─────────────────┬────────────────┘
└───────────────┬───────────────┘                                                 │
                │                                                                 │
                └─────────────────────────┐                                       │
                                          ▼                                       ▼
                               ┌─────────────────────────────────────────────────────┐
                               │  ws-proxy (Python / Tornado on port 4403)           │
                               │  - Handles CORS preflights (OPTIONS, GET, POST, PUT)│
                               │  - Manages HTTP polling queue (/api/v1/fromradio)  │
                               │  - Bridges WebSockets (/api/v1/ws)                  │
                               │  - Strips/Appends 4-byte TCP Header (0x94 0xc3 len)  │
                               └──────────────────────────┬──────────────────────────┘
                                                          │
                                                          │ Raw TCP (Port 4403)
                                                          ▼
                               ┌─────────────────────────────────────────────────────┐
                               │  meshtasticd (Meshtastic C++ Daemon)                │
                               │  - Simulated radio node (-s)                        │
                               │  - Port 4404 exposed for Python CLI management      │
                               └─────────────────────────────────────────────────────┘
```

---

## 2. Root Cause Analysis & Technical Solutions

### Problem 1: Protocol & Security Mismatch (Raw TCP vs Browser WebSockets/HTTP)
- **Root Cause**: `meshtasticd` exposes port `4403` as a **raw TCP binary socket**. Web browsers executing JavaScript (`meshtastic-web`) cannot open raw TCP sockets due to browser security sandboxing; they require WebSockets (`ws://`) or HTTP REST calls.
- **Solution**: Implemented `ws-proxy` using Python Tornado. It accepts WebSocket upgrades and HTTP requests on port `4403` and bridges them to `meshtasticd`'s TCP socket.

### Problem 2: TCP Packet Framing (`0x94 0xc3 <length>`)
- **Root Cause**: `meshtasticd`'s TCP stream expects and sends every Protobuf packet with a **4-byte header**:
  - Byte 0: `0x94` (`START1`)
  - Byte 1: `0xc3` (`START2`)
  - Bytes 2-3: `length` (2-byte big-endian integer)
  - Bytes 4+: Raw `FromRadio` or `ToRadio` Protobuf payload.
  
  `meshtastic-web` expects and sends **unframed** Protobuf payloads over WebSockets/HTTP.
- **Solution**: `proxy.py` parses and strips the 4-byte header from incoming `meshtasticd` TCP packets before sending to the browser, and prepends the 4-byte header to outgoing browser messages before writing to `meshtasticd`.

### Problem 3: CORS & Preflight (`OPTIONS` and `PUT` methods)
- **Root Cause**: `meshtastic-web` uses `PUT /api/v1/toradio` and CORS preflight `OPTIONS` requests. Browsers block requests if `PUT` is missing from `Access-Control-Allow-Methods`.
- **Solution**: Added explicit `PUT`, `POST`, `GET`, `OPTIONS`, `DELETE`, `PATCH` CORS handlers in `proxy.py` returning `204 No Content` with `Access-Control-Allow-Origin: *`.

### Problem 4: HTTP Polling vs WebSocket Streaming Queue
- **Root Cause**: `meshtastic-web` uses HTTP REST polling (`GET /api/v1/fromradio`) during initialization. Returning an empty HTTP response caused the UI to get stuck on a loading spinner.
- **Solution**: Added an asynchronous queue in `proxy.py`. A persistent background loop reads `FromRadio` packets from `meshtasticd` and feeds both the HTTP polling queue and active WebSockets.

### Problem 5: LoRa Region Uninitialized (`UNSET`)
- **Root Cause**: `meshtasticd` defaults to `region: UNSET`. When unconfigured, Meshtastic nodes block packet transmissions and config downloads.
- **Solution**: Set `Region: US` in `meshtasticd-config/config.yaml` and exposed port `4404` for direct CLI configuration using `meshtastic --host localhost:4404 --set lora.region US`.

---

## 3. Configuration Files

- [`docker-compose.yaml`](../docker-compose.yaml): Services definition (`meshtasticd`, `ws-proxy`, `web`).
- [`meshtasticd-config/config.yaml`](../meshtasticd-config/config.yaml): Daemon config setting `MACAddressSource: generate` and `Lora.Region: US`.
- [`meshtasticd-config/nginx.conf`](../meshtasticd-config/nginx.conf): NGINX configuration for `meshtastic-web` reverse-proxying `/api/v1/` to `ws-proxy:4403`.
- [`meshtasticd-config/proxy.py`](../meshtasticd-config/proxy.py): Tornado proxy bridging CORS, REST API, WebSockets, and TCP header framing.

---

## 4. How to Run

1. **Start the containers**:
   ```bash
   docker compose up -d
   ```

2. **Open the Web UI**:
   Navigate to **`http://localhost:8080`** (or `http://127.0.0.1:8080`) in your browser.

3. **CLI Management (Optional)**:
   You can manage the simulated daemon using the Python CLI via port 4404:
   ```bash
   .venv/bin/meshtastic --host localhost:4404 --info
   .venv/bin/meshtastic --host localhost:4404 --set lora.region US
   ```

---

## 5. MQTT & Shelly Smart Relay Integration

Full details, JSON payload schemas, security specs, and simulation steps are described in [`mqtt_shelly_simulation.md`](mqtt_shelly_simulation.md).

### Quick Architecture Summary:
- **Radio Link Encryption**: AES-256-CTR over dedicated secondary private channel (`HomeControl`).
- **Data Payload**: Compact JSON over `SERIAL_APP` / `TEXT_MESSAGE_APP` containing `ver`, `target`, `action`, `seq`, `sig`.
- **Security & Authorization**: Gateway checks sender Node ID whitelist, verifies `HMAC-SHA256(CONTROL_SECRET, ...)` signature, and enforces monotonic `seq` to prevent replay attacks.
- **Shelly MQTT Integration**: 
  - **Meshtastic RX (Gateway / Receiver)**: `meshtasticd-rx` daemon (TCP 4404 via proxy `ws-proxy-rx`, Web UI on `http://localhost:8080`).
  - **Meshtastic TX (Controller / Transmitter)**: `meshtasticd-tx` daemon (TCP 4405 via proxy `ws-proxy-tx`, Web UI on `http://localhost:8081`).
  - **MQTT Broker**: `mosquitto-broker` (Eclipse Mosquitto 2.0 on port 1883).
  - **Shelly Smart Relay Simulator**: `meshtasticd-config/shelly_simulator.py` (simulates Gen1/Gen2 Shelly topics).
  - **Gateway Bridge**: `meshtasticd-config/mqtt_bridge.py` (receives signed packets from RX node, validates HMAC-SHA256 and sequence counter, forwards to MQTT, sends ACK).
  - **Transmitter Test Client**: `meshtasticd-config/send_control_cmd.py` (sends signed packets to TX node).

---

## 6. Public Repository Security & Secrets Prevention Rules

> [!IMPORTANT]
> **This repository is public.** Under NO circumstances should real secrets, private keys, or sensitive credentials be committed or pushed.

### Strict Security Rules:
1. **No Real Cryptographic Keys or PSKs**:
   - In sample configs, code examples, or test scripts, always use generic placeholders (e.g. `"YOUR_HMAC_SECRET_KEY"`, `"YOUR_BASE64_AES256_PSK_KEY=="`) or load them dynamically from environment variables.
2. **No Real Network Credentials**:
   - Never commit Wi-Fi SSIDs/passwords, real MQTT broker user/password credentials, or private server endpoints.
3. **Environment Variable & `.env` Isolation**:
   - Keep actual keys and local passwords in `.env` or `config.local.yaml` (both excluded in `.gitignore`).
4. **Git Status & Pre-commit Verification**:
   - Always run `git status` and verify changes before committing to ensure no unintended data files, credentials, or logs are staged.
