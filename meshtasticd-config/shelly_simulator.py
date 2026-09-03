#!/usr/bin/env python3
"""
Shelly Smart Relay Simulator
Emulates a physical Shelly 1 / Shelly Plus 1 / Shelly 1 Gen3-Gen4 relay
connected to an MQTT broker. Subscribes to all three Shelly command formats
and publishes real-time status updates on both Gen 1 and Gen 2+ topics:

  Gen 1        : shellies/<id>/relay/0/command   (payload: on|off|toggle)
  Gen 2+ RPC   : <id>/rpc                         (JSON-RPC Switch.Set/Toggle)
  Gen 2+ ctrl  : <id>/command/switch:0            (payload: on|off|toggle|status_update)

The last format ("MQTT control", enabled on real devices via the
`enable_control` MQTT setting) is the one used by `mqtt_bridge.py` and the
ESP32 gateway firmware since Phase 4.
"""

import sys
import json
import time
import argparse
import signal
import paho.mqtt.client as mqtt

# ANSI Colors for rich terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


class ShellySimulator:
    def __init__(self, host: str = "localhost", port: int = 1883, device_id: str = "shelly1-sim01"):
        self.host = host
        self.port = port
        self.device_id = device_id
        self.state = False  # False = OFF, True = ON
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"shelly-sim-{device_id}")

        # Configure callbacks
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def publish_state(self):
        state_str = "on" if self.state else "off"
        # Gen 1 status topic
        gen1_topic = f"shellies/{self.device_id}/relay/0"
        self.client.publish(gen1_topic, state_str, qos=1, retain=True)

        # Gen 2 / RPC status topic
        gen2_topic = f"{self.device_id}/status/switch:0"
        gen2_payload = json.dumps({"output": self.state, "source": "MQTT", "apower": 12.5 if self.state else 0.0})
        self.client.publish(gen2_topic, gen2_payload, qos=1, retain=True)

        badge = f"{GREEN}[🟢 ON]{RESET}" if self.state else f"{RED}[🔴 OFF]{RESET}"
        print(f"{CYAN}[Shelly Simulator]{RESET} Relay State Changed ➔ {badge} (Published to {gen1_topic} & {gen2_topic})")

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            print(f"{GREEN}✓ Connected to MQTT Broker at {self.host}:{self.port}{RESET}")
            # Subscribe to Gen 1 Command topic
            gen1_cmd_topic = f"shellies/{self.device_id}/relay/0/command"
            client.subscribe(gen1_cmd_topic)

            # Subscribe to Gen 2 RPC command topic
            gen2_rpc_topic = f"{self.device_id}/rpc"
            client.subscribe(gen2_rpc_topic)

            # Subscribe to Gen 2+/Gen3/Gen4 "MQTT control" command topic
            # (the canonical topic published by mqtt_bridge.py / ESP32 firmware)
            gen2_ctrl_topic = f"{self.device_id}/command/switch:0"
            client.subscribe(gen2_ctrl_topic)

            print(f"{CYAN}[Shelly Simulator]{RESET} Subscribed to topics:")
            print(f"  ├─ Gen 1 Command:  {BOLD}{gen1_cmd_topic}{RESET}")
            print(f"  ├─ Gen 2 RPC:      {BOLD}{gen2_rpc_topic}{RESET}")
            print(f"  └─ Gen 2+ Control: {BOLD}{gen2_ctrl_topic}{RESET}")

            # Initial state publication
            self.publish_state()
        else:
            print(f"{RED}✗ Failed to connect to MQTT broker, reason_code: {reason_code}{RESET}")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload_raw = msg.payload.decode("utf-8", errors="ignore").strip()
        print(f"\n{YELLOW}⚡ [Incoming MQTT Message]{RESET} Topic: {topic} | Payload: {payload_raw}")

        # Gen 1 command handler
        if topic.endswith("/relay/0/command"):
            cmd = payload_raw.lower()
            if cmd in ("on", "1", "true"):
                self.state = True
            elif cmd in ("off", "0", "false"):
                self.state = False
            elif cmd in ("toggle", "t"):
                self.state = not self.state
            else:
                print(f"{RED}[Warning] Unknown Gen 1 command: {cmd}{RESET}")
                return
            self.publish_state()

        # Gen 2+/Gen3/Gen4 "MQTT control" handler (<id>/command/switch:0)
        elif topic.endswith("/command/switch:0"):
            cmd = payload_raw.lower()
            if cmd == "on":
                self.state = True
            elif cmd == "off":
                self.state = False
            elif cmd == "toggle":
                self.state = not self.state
            elif cmd == "status_update":
                pass  # Real devices re-publish <id>/status/switch:0 unchanged
            else:
                print(f"{RED}[Warning] Unknown Gen 2+ control command: {cmd}{RESET}")
                return
            self.publish_state()

        # Gen 2 RPC handler
        elif topic.endswith("/rpc"):
            try:
                data = json.loads(payload_raw)
                method = data.get("method", "")
                params = data.get("params", {})

                if method == "Switch.Set":
                    self.state = bool(params.get("on", False))
                elif method == "Switch.Toggle":
                    self.state = not self.state
                elif method == "Switch.GetStatus":
                    pass  # Just report state
                else:
                    print(f"{RED}[Warning] Unsupported RPC method: {method}{RESET}")
                    return
                self.publish_state()
            except Exception as e:
                print(f"{RED}[Error parsing RPC JSON]: {e}{RESET}")

    def run(self):
        print(f"{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}  Shelly Smart Relay Simulator (Device ID: {self.device_id}){RESET}")
        print(f"{BOLD}{'='*60}{RESET}")
        try:
            self.client.connect(self.host, self.port, 60)
            self.client.loop_forever()
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Stopping Shelly Simulator...{RESET}")
            self.client.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate a Shelly Smart Relay over MQTT")
    parser.add_argument("--host", default="localhost", help="MQTT Broker hostname (default: localhost)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker port (default: 1883)")
    parser.add_argument("--id", default="shelly1-sim01", help="Device ID (default: shelly1-sim01)")
    args = parser.parse_args()

    simulator = ShellySimulator(host=args.host, port=args.port, device_id=args.id)
    simulator.run()
