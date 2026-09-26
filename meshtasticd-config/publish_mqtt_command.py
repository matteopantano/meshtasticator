import os
import json
import hmac
import hashlib
import time

from dotenv import load_dotenv
import paho.mqtt.publish as publish

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

target = "shelly1-01"
action = "OFF"
seq = int(time.time())
secret = os.getenv("CONTROL_SECRET")
if not secret:
    raise RuntimeError("CONTROL_SECRET missing")

sig = hmac.new(
    secret.encode("utf-8"),
    f"{target}:{action}:{seq}".encode("utf-8"),
    hashlib.sha256,
).hexdigest()[:8]

msg = {
    "from": 468366631,
    "type": "text",
    "payload": {
        "text": json.dumps({
            "ver": 1,
            "target": target,
            "action": action,
            "seq": seq,
            "sig": sig,
        })
    }
}

region = os.getenv("LORA_REGION", "EU_868")
topic = f"msh/{region}/2/json/LongFast/test"
host = os.getenv("MQTT_HOST_REAL", "192.168.4.1")
port = int(os.getenv("MQTT_PORT", "1883"))

publish.single(topic, payload=json.dumps(msg), hostname=host, port=port)
print("PUBLISHED", topic)
print(json.dumps(msg))
