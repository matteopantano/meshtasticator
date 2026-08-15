# Secure Meshtastic to MQTT (Shelly Smart Relay) Control & Simulation Guide

This guide outlines the data structures, end-to-end security model (encryption, authentication, anti-replay), status feedback loop, and a local Docker/Python simulation setup in **Meshtasticator** for controlling a Shelly smart relay via Meshtastic and an ESP32 MQTT broker.

---

## 1. System Architecture & Component Flow

```
┌───────────────────────────────────────┐
│     Node A (Transmitter)              │
│  - Encrypts via AES-256 Private PSK   │
│  - Generates Nonce + HMAC Signature   │
└──────────────────┬────────────────────┘
                   │
                   │ 1. LoRa Packet (Private Channel Payload)
                   ▼
┌───────────────────────────────────────┐
│     Node B (Gateway / MQTT Gateway)   │
│  - Decrypts packet                    │
│  - Verifies Sender Node ID            │
│  - Verifies Nonce & HMAC Signature    │
└──────────────────┬────────────────────┘
                   │
                   │ 2. Publishes MQTT Command (shelly/command)
                   ▼
┌───────────────────────────────────────┐
│  MQTT Broker (ESP32 / Mosquitto)      │
└────────┬──────────────────────▲───────┘
         │                      │
         │ 3. Delivers Command  │ 4. Publishes Status Change
         ▼                      │
┌───────────────────────────────┴───────┐
│  Shelly Smart Relay (Gen1 / Gen2)     │
│  - Toggles relay state (ON / OFF)     │
└───────────────────────────────────────┘
                   │
                   │ 5. MQTT Broker sends relay status to Node B
                   ▼
┌───────────────────────────────────────┐
│     Node B (Gateway / MQTT Gateway)   │
│  - Formats encrypted status response  │
└──────────────────┬────────────────────┘
                   │
                   │ 6. LoRa Status ACK Packet
                   ▼
┌───────────────────────────────────────┐
│     Node A (Transmitter)              │
│  - Receives & confirms state change   │
└───────────────────────────────────────┘
```

---

## 2. Technical Requirements & Security Design

### A. Data Structure (Payload Specification)
To keep LoRa payload sizes minimal (< 200 bytes) while enabling full validation and feedback, use compact JSON structures over a private channel (e.g. `SERIAL_APP` or `TEXT_MESSAGE_APP`).

#### Command Payload (Node A ➔ Node B)
```json
{
  "ver": 1,
  "target": "shelly_relay_01",
  "action": "OFF",
  "seq": 1042,
  "sig": "e4b9c1d2"
}
```
* **`ver`**: Protocol version integer.
* **`target`**: Identifier of target device connected to MQTT broker.
* **`action`**: `ON`, `OFF`, or `TOGGLE`.
* **`seq`**: Monotonic counter / timestamp for anti-replay verification.
* **`sig`**: Truncated hex HMAC signature computed over `target + action + seq` with a shared secret key.

#### Status Feedback Payload (Node B ➔ Node A)
```json
{
  "ver": 1,
  "device": "shelly_relay_01",
  "state": "OFF",
  "ack_seq": 1042,
  "status": "OK"
}
```

---

### B. Encryption (Over-The-Air Security)
1. **Meshtastic Layer (AES-256-CTR)**:
   - Configure a dedicated private secondary channel (e.g., name `HomeControl`).
   - Generate a custom 256-bit key (`psk`).
   - Only nodes possessing this key (Node A and Node B) can decrypt packet contents. Unauthenticated nodes on the public mesh see only ciphertext.

---

### C. Sender Verification & Access Control (Authentication & Authorization)
To prevent unauthorized commands or spoofed packets:

1. **Sender Node ID Whitelist**:
   - Gateway verifies `FromRadio.from` equals Node A's exact 32-bit Node ID (e.g., `!1a2b3c4d`).
2. **HMAC Signature (Cryptographic Authorization)**:
   - Node A and Gateway share a secret key `CONTROL_SECRET`.
   - Node A computes `sig = Truncate8(HMAC_SHA256(CONTROL_SECRET, "shelly_relay_01:OFF:1042"))`.
   - Node B recalculates HMAC and drops request if signatures do not match.
3. **Anti-Replay Protection (Nonce / Sequence Tracking)**:
   - Node B stores `last_seen_seq` per Node ID.
   - If `seq <= last_seen_seq`, packet is rejected as a duplicate or replay attack.

---

### D. Shelly Smart Relay MQTT Integration

#### Shelly Standard Topics:
* **Shelly Gen 1 (e.g. Shelly 1/1PM)**:
  * Command Topic: `shellies/shelly1-<device_id>/relay/0/command` (Payload: `on` or `off`)
  * State Topic: `shellies/shelly1-<device_id>/relay/0` (Payload: `on` or `off`)
* **Shelly Gen 2 / Plus Series (RPC Protocol)**:
  * Command Topic: `<device_id>/rpc`
    * Payload: `{"id": 1, "src": "meshtastic_gw", "method": "Switch.Set", "params": {"id": 0, "on": false}}`
  * State Topic: `<device_id>/status/switch:0`

---

## 3. Local Simulation Architecture in Meshtasticator

To simulate and test this workflow on your Mac before flashing an ESP32:

1. **Mosquitto MQTT Broker**: Add Mosquitto container service to `docker-compose.yaml`.
2. **Gateway Bridge Daemon**: Python script in `meshtasticd-config/mqtt_bridge.py` connecting to `meshtasticd` TCP port 4403/4404 and MQTT broker port 1883.
3. **Shelly Relay Simulator**: Python script simulating a physical Shelly switch responding to `shellies/shelly1-01/relay/0/command` and publishing state updates.
4. **Transmitter Simulator Script**: Python script generating encrypted signed Meshtastic packets to trigger relay toggling and verify status ACK.
