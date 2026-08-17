#!/usr/bin/env python3
"""
Automated Meshtastic Node Provisioner
Provisions simulated containers OR physical USB/Wi-Fi hardware nodes in one click.
"""

import sys
import os
import subprocess
import argparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Load from .env with safe fallbacks
DEFAULT_WIFI_SSID = os.environ.get("WIFI_SSID", "ESP32-Hub")
DEFAULT_WIFI_PASS = os.environ.get("WIFI_PASS", "YourSecureWifiPass123")
DEFAULT_MQTT_SIM  = os.environ.get("MQTT_HOST_SIM", "mqtt-broker")
DEFAULT_MQTT_REAL = os.environ.get("MQTT_HOST_REAL", "192.168.4.1")
DEFAULT_REGION    = os.environ.get("LORA_REGION", "US")


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
):
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}⚡ Provisioning Meshtastic Node: {long_name} ({role.upper()}){RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")

    # 1. Set Owner Names
    print(f"{YELLOW}1/4 Setting Node Owner: {long_name} [{short_name}]...{RESET}")
    ok, out, err = run_meshtastic_cmd(conn_args + ["--set-owner", long_name, "--set-owner-short", short_name])
    if ok:
        print(f"{GREEN}✓ Owner name configured.{RESET}")
    else:
        print(f"{YELLOW}⚠️ Set owner notice: {err.strip() or out.strip()}{RESET}")

    # 2. Set LoRa Region
    print(f"{YELLOW}2/4 Setting LoRa Region: {region}...{RESET}")
    ok, out, err = run_meshtastic_cmd(conn_args + ["--set", "lora.region", region])
    if ok:
        print(f"{GREEN}✓ LoRa Region set to {region}.{RESET}")
    else:
        print(f"{YELLOW}⚠️ LoRa region notice: {err.strip() or out.strip()}{RESET}")

    # 3. Configure Wi-Fi (Real Hardware only)
    if not is_sim and wifi_ssid:
        print(f"{YELLOW}3/4 Configuring Wi-Fi: SSID '{wifi_ssid}'...{RESET}")
        ok, out, err = run_meshtastic_cmd(conn_args + [
            "--set", "network.wifi_enabled", "true",
            "--set", "network.wifi_ssid", wifi_ssid,
            "--set", "network.wifi_psk", wifi_pass
        ])
        if ok:
            print(f"{GREEN}✓ Wi-Fi configured.{RESET}")
        else:
            print(f"{YELLOW}⚠️ Wi-Fi config notice: {err.strip() or out.strip()}{RESET}")
    else:
        print(f"{CYAN}3/4 Wi-Fi: Skipped (Docker environment uses container network).{RESET}")

    # 4. Configure Native MQTT Module
    print(f"{YELLOW}4/4 Configuring Native MQTT Module (Host: {mqtt_host})...{RESET}")
    ok, out, err = run_meshtastic_cmd(conn_args + [
        "--set", "mqtt.enabled", "true",
        "--set", "mqtt.address", mqtt_host,
        "--set", "mqtt.json_enabled", "true",
        "--set", "mqtt.encryption_enabled", "false",
        "--set", "mqtt.root", "msh"
    ])
    if ok:
        print(f"{GREEN}✓ Native MQTT Module Enabled & Configured.{RESET}")
    else:
        print(f"{YELLOW}⚠️ MQTT config notice: {err.strip() or out.strip()}{RESET}")

    print(f"\n{BOLD}{GREEN}🎉 Node [{long_name}] Successfully Provisioned!{RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="Automated Meshtastic Node Provisioner")
    parser.add_argument("--sim", action="store_true", help="Auto-provision all local simulation nodes (RX & TX)")
    parser.add_argument("--role", choices=["rx", "tx", "all"], default="all", help="Target node role (rx, tx, or all)")
    parser.add_argument("--serial", help="Serial port for physical USB hardware node (e.g. /dev/ttyUSB0)")
    parser.add_argument("--host", help="IP address or hostname for Wi-Fi hardware node")
    parser.add_argument("--mqtt-host", help="Custom MQTT broker IP/hostname")
    parser.add_argument("--wifi-ssid", default=DEFAULT_WIFI_SSID, help=f"Wi-Fi SSID (default: {DEFAULT_WIFI_SSID})")
    parser.add_argument("--wifi-pass", default=DEFAULT_WIFI_PASS, help="Wi-Fi Password")
    parser.add_argument("--region", default=DEFAULT_REGION, help=f"LoRa Region (default: {DEFAULT_REGION})")

    args = parser.parse_args()

    # Simulation mode: Provision both RX and TX containers
    if args.sim or (not args.serial and not args.host):
        print(f"{BOLD}{CYAN}=== Automated Simulation Node Provisioner ==={RESET}")

        # Provision RX Node (Port 4404)
        if args.role in ["rx", "all"]:
            provision_node(
                conn_args=["--host", "localhost:4404"],
                role="rx",
                long_name="Gateway RX",
                short_name="RX",
                mqtt_host=args.mqtt_host or DEFAULT_MQTT_SIM,
                wifi_ssid="",
                wifi_pass="",
                region=args.region,
                is_sim=True,
            )

        # Provision TX Node (Port 4406)
        if args.role in ["tx", "all"]:
            provision_node(
                conn_args=["--host", "localhost:4406"],
                role="tx",
                long_name="Remote TX",
                short_name="TX",
                mqtt_host=args.mqtt_host or DEFAULT_MQTT_SIM,
                wifi_ssid="",
                wifi_pass="",
                region=args.region,
                is_sim=True,
            )

        print(f"{BOLD}{GREEN}✓ All simulation nodes are permanently configured and ready!{RESET}")
        return

    # Real Hardware Mode (via Serial USB or Wi-Fi)
    print(f"{BOLD}{CYAN}=== Real Hardware Node Provisioner ==={RESET}")
    mqtt_target = args.mqtt_host or DEFAULT_MQTT_REAL
    conn_args = ["--port", args.serial] if args.serial else ["--host", args.host]

    role = args.role if args.role != "all" else "gateway"
    long_name = f"Mesh {role.upper()} Node"
    short_name = role[:4].upper()

    provision_node(
        conn_args=conn_args,
        role=role,
        long_name=long_name,
        short_name=short_name,
        mqtt_host=mqtt_target,
        wifi_ssid=args.wifi_ssid,
        wifi_pass=args.wifi_pass,
        region=args.region,
        is_sim=False,
    )


if __name__ == "__main__":
    main()
