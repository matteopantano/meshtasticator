"""
PlatformIO pre-build script to automatically inject .env configuration
into C++ preprocessor defines.

Single source of truth: Keeps Wi-Fi credentials, HMAC secret, and LoRa region
synchronized between the Python testbed and the ESP32 gateway firmware.
"""

import os

Import("env")  # Provided by PlatformIO/SCons execution environment

# Look for .env in repository root or local firmware directory
project_dir = env.get("PROJECT_DIR", os.getcwd())
candidates = [
    os.path.abspath(os.path.join(project_dir, "..", "..", ".env")),
    os.path.abspath(os.path.join(project_dir, ".env")),
]

env_file = None
for path in candidates:
    if os.path.exists(path):
        env_file = path
        break

env_vars = {}
if env_file:
    print(f"[load_env.py] Loading configuration from {env_file}")
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            env_vars[key] = val
else:
    print("[load_env.py] Notice: No .env found; using default fallback definitions in main.cpp.")

# Map .env keys to C++ preprocessor macros
macro_mappings = {
    "WIFI_SSID": "AP_SSID",
    "WIFI_PASS": "AP_PASS",
    "CONTROL_SECRET": "CONTROL_SECRET",
    "LORA_REGION": "MESH_LORA_REGION",
    "GATEWAY_NODE_ID": "MESH_GATEWAY_NODE_ID",
}

cpp_defines = []
for env_key, macro_name in macro_mappings.items():
    if env_key in env_vars and env_vars[env_key]:
        val = env_vars[env_key]
        if macro_name == "MESH_GATEWAY_NODE_ID":
            try:
                node_id_val = int(val, 0)
                cpp_defines.append((macro_name, node_id_val))
            except ValueError:
                pass
        else:
            # String macro definitions for C++ preprocessor
            cpp_defines.append((macro_name, f'\\"{val}\\"'))

if cpp_defines:
    env.Append(CPPDEFINES=cpp_defines)
    print(f"[load_env.py] Successfully injected defines: {[d[0] for d in cpp_defines]}")

# TinyConsole (pulled by TinyMqtt) uses std::exchange but misses <utility>
# on some toolchains. Apply the include only to C++ compilation units.
env.Append(CXXFLAGS=["-include", "utility"])
