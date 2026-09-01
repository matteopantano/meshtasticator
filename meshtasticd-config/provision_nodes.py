#!/usr/bin/env python3
"""
Automated Meshtastic Node Provisioner
Provisions simulated containers OR physical USB/Wi-Fi hardware nodes in one click.
"""

import sys
import os
import time
import subprocess
import argparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Load from .env with safe fallbacks
DEFAULT_WIFI_SSID_RX = os.environ.get("WIFI_SSID_RX", os.environ.get("WIFI_SSID", "ESP32-Hub"))
DEFAULT_WIFI_PASS_RX = os.environ.get("WIFI_PASS_RX", os.environ.get("WIFI_PASS", "YourSecureWifiPass123"))
DEFAULT_WIFI_SSID_TX = os.environ.get("WIFI_SSID_TX", "YourHomeWifi")
DEFAULT_WIFI_PASS_TX = os.environ.get("WIFI_PASS_TX", "YourHomeWifiPassword")
DEFAULT_MQTT_SIM     = os.environ.get("MQTT_HOST_SIM", "mqtt-broker")
DEFAULT_MQTT_REAL    = os.environ.get("MQTT_HOST_REAL", "192.168.4.1")
DEFAULT_REGION       = os.environ.get("LORA_REGION", "US")


GREEN  = "\033[92m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def run_meshtastic_cmd(args_list):
    venv_meshtastic = os.path.join(os.path.dirname(__file__), "..", ".venv", "bin", "meshtastic")
    if not os.path.exists(venv_meshtastic):
        venv_meshtastic = "meshtastic"

    cmd = [venv_meshtastic] + args_list
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.returncode == 0, res.stdout, res.stderr


def provision_node(
    conn_args: list,
    role: str,
    long_name: str,
    short_name: str,
    mqtt_host: str,
    wifi_ssid: str,
    wifi_pass: str,
    region: str = "US",
    is_sim: bool = False,
    enable_mqtt: bool = True,
):
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}⚡ Provisioning Meshtastic Node: {long_name} ({role.upper()}){RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")

    # Build combined configuration arguments for atomic application
    cmd_args = list(conn_args)
    cmd_args += ["--set-owner", long_name, "--set-owner-short", short_name]
    cmd_args += ["--set", "lora.region", region]

    if not is_sim and wifi_ssid:
        cmd_args += [
            "--set", "network.wifi_enabled", "true",
            "--set", "network.wifi_ssid", wifi_ssid,
            "--set", "network.wifi_psk", wifi_pass
        ]

    if enable_mqtt:
        cmd_args += [
            "--set", "mqtt.enabled", "true",
            "--set", "mqtt.address", mqtt_host,
            "--set", "mqtt.json_enabled", "true",
            "--set", "mqtt.encryption_enabled", "false",
            "--set", "mqtt.root", "msh"
        ]
    elif not is_sim:
        cmd_args += [
            "--set", "mqtt.enabled", "false"
        ]

    if is_sim:
        # Broadcast NodeInfo every 5 minutes in simulation for fast mesh discovery
        cmd_args += ["--set", "device.node_info_broadcast_secs", "300"]

    summary_wifi = f", Wi-Fi: '{wifi_ssid}'" if wifi_ssid else ""
    summary_mqtt = f", MQTT: '{mqtt_host}'" if enable_mqtt else ", MQTT: Disabled"
    print(f"{YELLOW}Applying configuration (Owner: '{long_name}', Region: '{region}'{summary_wifi}{summary_mqtt})...{RESET}")

    # Retry up to 3 times with backoff in case the node is recovering from a previous reboot
    max_retries = 3
    ok, out, err = False, "", ""
    for attempt in range(1, max_retries + 1):
        ok, out, err = run_meshtastic_cmd(cmd_args)
        if ok:
            break
        if attempt < max_retries:
            time.sleep(2)

    if ok:
        print(f"{GREEN}✓ Owner name, LoRa region ({region}), and network/module settings applied.{RESET}")
        print(f"\n{BOLD}{GREEN}🎉 Node [{long_name}] Successfully Provisioned!{RESET}\n")
        return True
    else:
        print(f"{RED}⚠️ Configuration failed: {err.strip() or out.strip()}{RESET}")
        print(f"\n{BOLD}{RED}❌ Provisioning [{long_name}] encountered errors.{RESET}")
        if is_sim:
            print(f"{YELLOW}💡 Is the Docker stack running? Start it first with: {BOLD}docker compose up -d{RESET}\n")
        return False


def main():
    parser = argparse.ArgumentParser(description="Automated Meshtastic Node Provisioner")
    parser.add_argument("--sim", action="store_true", help="Auto-provision all local simulation nodes (RX & TX)")
    parser.add_argument("--role", choices=["rx", "tx", "all"], default="all", help="Target node role (rx, tx, or all)")
    parser.add_argument("--serial", help="Serial port for physical USB hardware node (e.g. /dev/ttyUSB0)")
    parser.add_argument("--host", help="IP address or hostname for Wi-Fi hardware node")
    parser.add_argument("--mqtt-host", help="Custom MQTT broker IP/hostname")
    parser.add_argument("--wifi-ssid", help="Wi-Fi SSID (defaults to WIFI_SSID_RX for RX, WIFI_SSID_TX for TX)")
    parser.add_argument("--wifi-pass", help="Wi-Fi Password (defaults to WIFI_PASS_RX for RX, WIFI_PASS_TX for TX)")
    parser.add_argument("--region", default=DEFAULT_REGION, help=f"LoRa Region (default: {DEFAULT_REGION})")

    args = parser.parse_args()

    overall_success = True

    # Simulation mode: Provision both RX and TX containers
    if args.sim or (not args.serial and not args.host):
        print(f"{BOLD}{CYAN}=== Automated Simulation Node Provisioner ==={RESET}")

        # Provision RX Node (Port 4404)
        if args.role in ["rx", "all"]:
            success = provision_node(
                conn_args=["--host", "localhost:4404"],
                role="rx",
                long_name="Gateway RX",
                short_name="RX",
                mqtt_host=args.mqtt_host or DEFAULT_MQTT_SIM,
                wifi_ssid="",
                wifi_pass="",
                region=args.region,
                is_sim=True,
                enable_mqtt=True,
            )
            if not success:
                overall_success = False

        # Provision TX Node (Port 4406)
        if args.role in ["tx", "all"]:
            success = provision_node(
                conn_args=["--host", "localhost:4406"],
                role="tx",
                long_name="Remote TX",
                short_name="TX",
                mqtt_host=args.mqtt_host or DEFAULT_MQTT_SIM,
                wifi_ssid="",
                wifi_pass="",
                region=args.region,
                is_sim=True,
                enable_mqtt=True,
            )
            if not success:
                overall_success = False

        if overall_success:
            print(f"{BOLD}{GREEN}✓ All simulation nodes are permanently configured and ready!{RESET}")
        else:
            print(f"{BOLD}{RED}❌ Some nodes failed to provision. Please ensure 'docker compose up -d' is running.{RESET}")
            sys.exit(1)
        return

    # Real Hardware Mode (via Serial USB or Wi-Fi)
    print(f"{BOLD}{CYAN}=== Real Hardware Node Provisioner ==={RESET}")
    conn_args = ["--port", args.serial] if args.serial else ["--host", args.host]

    role = args.role if args.role != "all" else "rx"
    long_name = f"Mesh {role.upper()} Node"
    short_name = role[:4].upper()

    if role == "rx":
        wifi_ssid = args.wifi_ssid or DEFAULT_WIFI_SSID_RX
        wifi_pass = args.wifi_pass or DEFAULT_WIFI_PASS_RX
        mqtt_target = args.mqtt_host or DEFAULT_MQTT_REAL
        enable_mqtt = True
    else:  # role == "tx"
        wifi_ssid = args.wifi_ssid or DEFAULT_WIFI_SSID_TX
        wifi_pass = args.wifi_pass or DEFAULT_WIFI_PASS_TX
        mqtt_target = ""
        enable_mqtt = False

    provision_node(
        conn_args=conn_args,
        role=role,
        long_name=long_name,
        short_name=short_name,
        mqtt_host=mqtt_target,
        wifi_ssid=wifi_ssid,
        wifi_pass=wifi_pass,
        region=args.region,
        is_sim=False,
        enable_mqtt=enable_mqtt,
    )


if __name__ == "__main__":
    main()
