#!/usr/bin/env python3
"""
Meshtastic to MQTT Gateway Bridge
Connects to meshtasticd and an MQTT broker to provide secure control of Shelly relays.
Enforces:
  1. Sender Node ID Whitelisting
  2. Monotonic Sequence Number Verification (Anti-Replay)
  3. HMAC-SHA256 Cryptographic Signature Verification
  4. Bidirectional Status Feedback over Meshtastic
"""

import sys
import os
import time
import json
import hmac
import hashlib
import argparse
from pubsub import pub
import paho.mqtt.client as mqtt
import meshtastic
import meshtastic.tcp_interface

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ANSI Color Codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
RESET = "\033[0m"


def compute_hmac_sig(secret: str, target: str, action: str, seq: int) -> str:
    """Computes a truncated 8-character hex HMAC-SHA256 signature."""
    canonical = f"{target}:{action.upper()}:{seq}"
    digest = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:8]


def extract_text_from_packet(packet) -> str:
    """Extracts text payload across both real hardware and simulated radio modes."""
    decoded = packet.get("decoded", {})
    if decoded.get("text"):
        return decoded["text"]

    sim = decoded.get("simulator", {})
    if isinstance(sim, dict):
        data_b64 = sim.get("data")
        if data_b64:
            import base64
            try:
                from meshtastic.protobuf import mesh_pb2
                raw = base64.b64decode(data_b64)
                d = mesh_pb2.Data.FromString(raw)
                return d.payload.decode("utf-8", errors="ignore")
            except Exception:
                pass
        raw_obj = sim.get("raw")
        if hasattr(raw_obj, "data") and raw_obj.data:
            return raw_obj.data

    payload = decoded.get("payload")
    if isinstance(payload, bytes):
        try:
            from meshtastic.protobuf import mesh_pb2
            d = mesh_pb2.Data.FromString(payload)
            if d.payload:
                return d.payload.decode("utf-8", errors="ignore")
        except Exception:
            pass
        s = payload.decode("utf-8", errors="ignore")
        if "{" in s and "}" in s:
            return s[s.find("{"):s.rfind("}") + 1]
    return ""



class MeshtasticMQTTBridge:
    def __init__(
        self,
        mesh_host: str = "localhost",
        mesh_port: int = 4404,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        secret: str = "MeshShellySecret2026",
        allowed_nodes: list = None,
    ):
        self.mesh_host = mesh_host
        self.mesh_port = mesh_port
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.secret = secret
        self.allowed_nodes = allowed_nodes or ["*"]  # "*" allows any node ID for simulation

        # Security Tracking: sender_id -> last_seen_seq
        self.last_seen_seq = {}

        # Pending Requests: target -> {"from_id": str, "seq": int, "timestamp": float}
        self.pending_requests = {}

        # MQTT Client setup
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="meshtastic-mqtt-bridge")
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message

        self.mesh_iface = None

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            print(f"{GREEN}✓ Bridge connected to MQTT Broker at {self.mqtt_host}:{self.mqtt_port}{RESET}")
            # Subscribe to all Shelly relay state topics
            client.subscribe("shellies/+/relay/0")
            client.subscribe("+/status/switch:0")
            print(f"{CYAN}[MQTT Bridge]{RESET} Subscribed to status topics: {BOLD}shellies/+/relay/0{RESET} & {BOLD}+/status/switch:0{RESET}")
        else:
            print(f"{RED}✗ Bridge failed to connect to MQTT broker, reason_code: {reason_code}{RESET}")

    def on_mqtt_message(self, client, userdata, msg):
        topic = msg.topic
        payload_raw = msg.payload.decode("utf-8", errors="ignore").strip()

        # Parse target device name and state
        target = None
        state = None

        if topic.startswith("shellies/") and topic.endswith("/relay/0"):
            # Gen 1 format: shellies/<device_id>/relay/0
            parts = topic.split("/")
            if len(parts) >= 2:
                target = parts[1]
                state = payload_raw.upper()

        elif topic.endswith("/status/switch:0"):
            # Gen 2 format: <device_id>/status/switch:0
            target = topic.split("/")[0]
            try:
                data = json.loads(payload_raw)
                state = "ON" if data.get("output") else "OFF"
            except Exception:
                state = "UNKNOWN"

        if not target or not state:
            return

        print(f"\n{CYAN}📥 [MQTT State Event]{RESET} Target: {BOLD}{target}{RESET} | State: {BOLD}{state}{RESET}")

        # Check if there is a pending Meshtastic request for this device
        pending = self.pending_requests.get(target)
        if pending and self.mesh_iface:
            from_id = pending["from_id"]
            seq = pending["seq"]
            ack_payload = {
                "ver": 1,
                "device": target,
                "state": state,
                "ack_seq": seq,
                "status": "OK"
            }
            ack_json = json.dumps(ack_payload)
            print(f"{MAGENTA}📤 [Meshtastic LoRa ACK]{RESET} Sending status to {BOLD}{from_id}{RESET}: {ack_json}")
            try:
                self.mesh_iface.sendText(ack_json, destinationId=from_id)
                print(f"{GREEN}✓ Meshtastic ACK transmitted successfully.{RESET}")
            except Exception as e:
                print(f"{RED}✗ Error sending Meshtastic ACK: {e}{RESET}")

    def on_meshtastic_receive(self, packet, interface):
        try:
            from_id = packet.get("fromId", packet.get("from", "UNKNOWN"))
            decoded = packet.get("decoded", {})
            text = extract_text_from_packet(packet)

            print(f"\n{YELLOW}{'='*60}{RESET}")
            print(f"{YELLOW}⚡ [Meshtastic Packet Received]{RESET} From: {BOLD}{from_id}{RESET} | Portnum: {decoded.get('portnum')} | Text: {text!r}")
            print(f"Decoded: {decoded}")

            if not text:
                return


            # 1. Parse JSON Payload
            try:
                cmd_data = json.loads(text)
            except Exception:
                # Not a JSON command (could be another mesh message)
                return


            target = cmd_data.get("target")
            action = str(cmd_data.get("action", "")).upper()
            seq = cmd_data.get("seq")
            sig = cmd_data.get("sig", "")

            if not target or not action or seq is None or not sig:
                print(f"{RED}🛡️ [Validation FAILED] Missing required fields (target, action, seq, sig).{RESET}")
                return

            # 2. Whitelist Check
            if "*" not in self.allowed_nodes and str(from_id) not in self.allowed_nodes:
                print(f"{RED}🛡️ [Security DENIED] Sender {from_id} is NOT in allowed whitelist: {self.allowed_nodes}{RESET}")
                return
            print(f"{GREEN}🛡️ [Check 1/3: Whitelist] Sender {from_id} Authorized ✓{RESET}")

            # 3. Anti-Replay Check (Monotonic Sequence)
            last_seq = self.last_seen_seq.get(from_id, -1)
            if seq <= last_seq:
                print(f"{RED}🛡️ [Security REJECTED: Replay Attack] Received seq={seq} <= last_seen_seq={last_seq} for {from_id}!{RESET}")
                return
            print(f"{GREEN}🛡️ [Check 2/3: Anti-Replay] Sequence {seq} > {last_seq} Verified ✓{RESET}")

            # 4. HMAC Signature Verification
            expected_sig = compute_hmac_sig(self.secret, target, action, seq)
            if not hmac.compare_digest(sig.lower(), expected_sig.lower()):
                print(f"{RED}🛡️ [Security REJECTED: Bad Signature] Received sig='{sig}' != Expected '{expected_sig}'!{RESET}")
                return
            print(f"{GREEN}🛡️ [Check 3/3: HMAC Signature] Cryptographic Signature Verified ✓{RESET}")

            # All security checks passed! Update sequence number
            self.last_seen_seq[from_id] = seq
            self.pending_requests[target] = {
                "from_id": from_id,
                "seq": seq,
                "timestamp": time.time()
            }

            # 5. Publish Command to MQTT Broker for Shelly
            mqtt_cmd_topic = f"shellies/{target}/relay/0/command"
            mqtt_payload = action.lower()
            print(f"{CYAN}📤 [MQTT Publish]{RESET} Topic: {BOLD}{mqtt_cmd_topic}{RESET} | Payload: {BOLD}{mqtt_payload}{RESET}")
            self.mqtt_client.publish(mqtt_cmd_topic, mqtt_payload, qos=1)

        except Exception as e:
            print(f"{RED}[Bridge Handler Error]: {e}{RESET}")

    def run(self):
        print(f"{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}  Meshtastic ➔ MQTT Gateway Bridge{RESET}")
        print(f"{BOLD}  Mesh Host: {self.mesh_host}:{self.mesh_port} | MQTT: {self.mqtt_host}:{self.mqtt_port}{RESET}")
        print(f"{BOLD}{'='*60}{RESET}")

        # Connect MQTT
        self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
        self.mqtt_client.loop_start()

        # Connect Meshtastic
        print(f"{CYAN}Connecting to meshtasticd at {self.mesh_host}:{self.mesh_port}...{RESET}")
        try:
            self.mesh_iface = meshtastic.tcp_interface.TCPInterface(
                hostname=self.mesh_host,
                portNumber=self.mesh_port
            )
            print(f"{GREEN}✓ Connected to meshtasticd TCP interface.{RESET}")
        except Exception as e:
            print(f"{RED}✗ Failed to connect to meshtasticd: {e}{RESET}")
            print(f"{YELLOW}Ensure meshtasticd container is running on port {self.mesh_port}.{RESET}")
            sys.exit(1)

        # Subscribe to incoming packets
        pub.subscribe(self.on_meshtastic_receive, "meshtastic.receive")
        print(f"{GREEN}✓ Listening for secure Meshtastic control packets...{RESET}\n")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Shutting down bridge...{RESET}")
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            if self.mesh_iface:
                self.mesh_iface.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Meshtastic-to-MQTT Bridge")
    parser.add_argument("--mesh-host", default="localhost", help="meshtasticd host (default: localhost)")
    parser.add_argument("--mesh-port", type=int, default=4404, help="meshtasticd port (default: 4404)")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT host (default: localhost)")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT port (default: 1883)")
    parser.add_argument("--secret", default=os.getenv("CONTROL_SECRET", "MeshShellySecret2026"), help="HMAC Secret Key")
    parser.add_argument("--allowed-nodes", nargs="*", default=["*"], help="Allowed sender node IDs (default: '*')")
    args = parser.parse_args()

    bridge = MeshtasticMQTTBridge(
        mesh_host=args.mesh_host,
        mesh_port=args.mesh_port,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        secret=args.secret,
        allowed_nodes=args.allowed_nodes
    )
    bridge.run()
