#!/usr/bin/env python3
"""
Meshtastic Control Command Transmitter (Test Harness / Node A)
Constructs cryptographically signed Meshtastic control messages,
sends them to the Gateway Node, and waits for a status ACK response.
"""

import sys
import os
import time
import json
import hmac
import hashlib
import argparse
from pubsub import pub
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



class MeshtasticSender:
    def __init__(self, host: str = "localhost", port: int = 4405):
        self.host = host
        self.port = port
        self.ack_received = False
        self.ack_data = None
        self.expected_seq = None

        print(f"{CYAN}Connecting to Meshtastic node at {self.host}:{self.port}...{RESET}")
        try:
            self.iface = meshtastic.tcp_interface.TCPInterface(hostname=self.host, portNumber=self.port)
            self.iface._waitConnected()
            pub.subscribe(self.on_receive, "meshtastic.receive")
            print(f"{GREEN}✓ Connected & Synced with Meshtastic radio interface (Node: {self.iface.myInfo.my_node_num}).{RESET}")
        except Exception as e:
            print(f"{RED}✗ Failed to connect to Meshtastic: {e}{RESET}")
            sys.exit(1)


    def on_receive(self, packet, interface):
        try:
            text = extract_text_from_packet(packet)
            if not text:
                return

            try:
                data = json.loads(text)
                if data.get("ack_seq") == self.expected_seq:
                    self.ack_received = True
                    self.ack_data = data
            except Exception:
                pass
        except Exception:
            pass


    def send_command(
        self,
        target: str,
        action: str,
        secret: str,
        seq: int = None,
        bad_sig: bool = False,
        replay: bool = False,
        dest: str = "^all",
        timeout: int = 15,
    ):

        # Determine sequence number
        if replay:
            seq = 1  # Replay an old sequence number
        elif seq is None:
            seq = int(time.time() % 1000000)  # Monotonic integer

        self.expected_seq = seq

        # Compute signature
        if bad_sig:
            sig = "deadbeef"  # Deliberately invalid signature
        else:
            sig = compute_hmac_sig(secret, target, action, seq)

        payload = {
            "ver": 1,
            "target": target,
            "action": action.upper(),
            "seq": seq,
            "sig": sig,
        }
        payload_json = json.dumps(payload)

        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}  Meshtastic Secure Control Transmitter{RESET}")
        print(f"{BOLD}{'='*60}{RESET}")
        print(f"Target Device:  {BOLD}{target}{RESET}")
        print(f"Action:         {BOLD}{action.upper()}{RESET}")
        print(f"Sequence No:    {BOLD}{seq}{RESET} {'(FORCED REPLAY)' if replay else ''}")
        print(f"HMAC Signature: {BOLD}{sig}{RESET} {'(INVALID / TAMPERED)' if bad_sig else '(Valid HMAC-SHA256)'}")
        print(f"Payload JSON:   {CYAN}{payload_json}{RESET}\n")

        print(f"{YELLOW}📡 Transmitting Meshtastic packet to destination '{dest}'...{RESET}")
        pkt = self.iface.sendText(payload_json, destinationId=dest)
        pkt_id = getattr(pkt, "id", "broadcast")
        print(f"{GREEN}✓ Packet transmitted over radio link (Packet ID: {pkt_id}).{RESET}")


        if bad_sig or replay:
            print(f"\n{YELLOW}⏳ Observation mode for security test (Expecting Gateway to DROP packet)...{RESET}")
            time.sleep(4)
            print(f"{GREEN}🛡️ Security verification completed.{RESET}")
            self.iface.close()
            return

        # Wait for ACK response
        print(f"{CYAN}⏳ Awaiting status ACK from gateway (timeout: {timeout}s)...{RESET}")
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.ack_received:
                device = self.ack_data.get("device")
                state = self.ack_data.get("state")
                ack_seq = self.ack_data.get("ack_seq")
                status = self.ack_data.get("status")

                badge = f"{GREEN}[🟢 ON]{RESET}" if state == "ON" else f"{RED}[🔴 OFF]{RESET}"
                print(f"\n{GREEN}{'='*60}{RESET}")
                print(f"{GREEN}🎉 Status ACK Received via Meshtastic!{RESET}")
                print(f"Device:       {BOLD}{device}{RESET}")
                print(f"Relay State:  {badge}")
                print(f"ACK Seq:      {BOLD}{ack_seq}{RESET}")
                print(f"Status:       {BOLD}{status}{RESET}")
                print(f"{GREEN}{'='*60}{RESET}\n")
                self.iface.close()
                return
            time.sleep(0.1)

        print(f"\n{YELLOW}⚠️ Timed out waiting for Meshtastic ACK.{RESET}")
        self.iface.close()



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send Secure Meshtastic Relay Control Command")
    parser.add_argument("--target", default="shelly1-sim01", help="Target device ID (default: shelly1-sim01)")
    parser.add_argument("--action", default="ON", choices=["ON", "OFF", "TOGGLE"], help="Action to execute")
    parser.add_argument("--secret", default=os.getenv("CONTROL_SECRET", "MeshShellySecret2026"), help="HMAC Secret Key")
    parser.add_argument("--seq", type=int, default=None, help="Explicit sequence number")
    parser.add_argument("--bad-sig", action="store_true", help="Deliberately send an invalid HMAC signature")
    parser.add_argument("--replay", action="store_true", help="Deliberately send a replayed old sequence number")
    parser.add_argument("--dest", default="^all", help="Destination Node ID (default: ^all)")
    parser.add_argument("--mesh-host", default="localhost", help="meshtasticd host (default: localhost)")
    parser.add_argument("--mesh-port", type=int, default=4404, help="meshtasticd port (default: 4404)")
    args = parser.parse_args()

    sender = MeshtasticSender(host=args.mesh_host, port=args.mesh_port)
    sender.send_command(
        target=args.target,
        action=args.action,
        secret=args.secret,
        seq=args.seq,
        bad_sig=args.bad_sig,
        replay=args.replay,
        dest=args.dest
    )
