"""Unit tests for meshtasticd-config/mqtt_bridge.py.

These tests exercise the security-critical MQTT/Shelly control pipeline
entirely in-process: no real MQTT broker, meshtasticd TCP connection, or
Docker container is required. The module under test is loaded dynamically
via importlib because `meshtasticd-config` is not an importable Python
package (dashed directory name, no `__init__.py`), following the same
pattern used in tests/test_interactive.py.
"""

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import unittest
from unittest.mock import MagicMock

from meshtastic.protobuf import mesh_pb2


def load_mqtt_bridge():
    module_name = "_mqtt_bridge_under_test"
    module_path = os.path.join(
        os.path.dirname(__file__), "..", "meshtasticd-config", "mqtt_bridge.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mqtt_bridge = load_mqtt_bridge()
compute_hmac_sig = mqtt_bridge.compute_hmac_sig
extract_text_from_packet = mqtt_bridge.extract_text_from_packet
MeshtasticMQTTBridge = mqtt_bridge.MeshtasticMQTTBridge


def make_data_payload_bytes(payload_dict: dict) -> bytes:
    """Serialize a mesh_pb2.Data protobuf whose `payload` is JSON bytes."""
    data = mesh_pb2.Data()
    data.payload = json.dumps(payload_dict).encode("utf-8")
    return data.SerializeToString()


class TestComputeHmacSig(unittest.TestCase):
    def test_known_vector_matches_direct_hmac_computation(self):
        secret = "MeshShellySecret2026"
        target = "shelly1-sim01"
        action = "ON"
        seq = 1042

        expected = hmac.new(
            secret.encode("utf-8"),
            f"{target}:{action}:{seq}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:8]

        self.assertEqual(compute_hmac_sig(secret, target, action, seq), expected)

    def test_action_case_insensitive(self):
        secret = "MeshShellySecret2026"
        target = "shelly1-sim01"
        seq = 7

        sig_lower = compute_hmac_sig(secret, target, "on", seq)
        sig_upper = compute_hmac_sig(secret, target, "ON", seq)
        sig_mixed = compute_hmac_sig(secret, target, "On", seq)

        self.assertEqual(sig_lower, sig_upper)
        self.assertEqual(sig_lower, sig_mixed)


class TestExtractTextFromPacket(unittest.TestCase):
    def test_direct_decoded_text(self):
        packet = {"decoded": {"text": "hello world"}}
        self.assertEqual(extract_text_from_packet(packet), "hello world")

    def test_simulator_base64_protobuf_data(self):
        payload_dict = {"target": "shelly1-sim01", "action": "ON", "seq": 1, "sig": "abcd1234"}
        raw = make_data_payload_bytes(payload_dict)
        encoded = base64.b64encode(raw).decode("ascii")
        packet = {"decoded": {"simulator": {"data": encoded}}}

        result = extract_text_from_packet(packet)
        self.assertEqual(json.loads(result), payload_dict)

    def test_raw_payload_bytes_protobuf(self):
        payload_dict = {"target": "shelly1-sim01", "action": "OFF", "seq": 2, "sig": "deadbeef"}
        raw = make_data_payload_bytes(payload_dict)
        packet = {"decoded": {"payload": raw}}

        result = extract_text_from_packet(packet)
        self.assertEqual(json.loads(result), payload_dict)

    def test_raw_payload_bytes_json_substring_fallback(self):
        noisy = b"\x01\x02garbage{\"target\": \"shelly1-sim01\"}moregarbage\x03"
        packet = {"decoded": {"payload": noisy}}

        result = extract_text_from_packet(packet)
        self.assertEqual(json.loads(result), {"target": "shelly1-sim01"})

    def test_empty_decoded_returns_empty_string(self):
        self.assertEqual(extract_text_from_packet({"decoded": {}}), "")
        self.assertEqual(extract_text_from_packet({}), "")


class TestOnMeshtasticReceiveSecurity(unittest.TestCase):
    def setUp(self):
        self.secret = "TestSecret123"
        self.bridge = MeshtasticMQTTBridge(secret=self.secret, allowed_nodes=["*"])
        self.bridge.mqtt_client = MagicMock()
        self.bridge.mesh_iface = MagicMock()

    def make_packet(self, from_id, target, action, seq, sig=None):
        if sig is None:
            sig = compute_hmac_sig(self.secret, target, action, seq)
        cmd = {"target": target, "action": action, "seq": seq, "sig": sig}
        return {"fromId": from_id, "decoded": {"text": json.dumps(cmd)}}

    def test_valid_signed_command_is_accepted(self):
        packet = self.make_packet("!aaaa1111", "shelly1-sim01", "ON", 1)
        self.bridge.on_meshtastic_receive(packet, interface=None)

        self.bridge.mqtt_client.publish.assert_called_once_with(
            "shellies/shelly1-sim01/relay/0/command", "on", qos=1
        )
        self.assertEqual(self.bridge.last_seen_seq["!aaaa1111"], 1)
        self.assertEqual(
            self.bridge.pending_requests["shelly1-sim01"]["from_id"], "!aaaa1111"
        )
        self.assertEqual(self.bridge.pending_requests["shelly1-sim01"]["seq"], 1)

    def test_valid_command_toggle_lowercase_payload(self):
        packet = self.make_packet("!aaaa1111", "shelly1-sim01", "TOGGLE", 5)
        self.bridge.on_meshtastic_receive(packet, interface=None)
        self.bridge.mqtt_client.publish.assert_called_once_with(
            "shellies/shelly1-sim01/relay/0/command", "toggle", qos=1
        )

    def test_sender_not_in_whitelist_is_rejected(self):
        self.bridge.allowed_nodes = ["!bbbb2222"]
        packet = self.make_packet("!aaaa1111", "shelly1-sim01", "ON", 1)
        self.bridge.on_meshtastic_receive(packet, interface=None)

        self.bridge.mqtt_client.publish.assert_not_called()
        self.assertNotIn("!aaaa1111", self.bridge.last_seen_seq)

    def test_replayed_stale_sequence_is_rejected(self):
        self.bridge.last_seen_seq["!aaaa1111"] = 10
        packet = self.make_packet("!aaaa1111", "shelly1-sim01", "ON", 10)
        self.bridge.on_meshtastic_receive(packet, interface=None)
        self.bridge.mqtt_client.publish.assert_not_called()

        packet_lower = self.make_packet("!aaaa1111", "shelly1-sim01", "ON", 5)
        self.bridge.on_meshtastic_receive(packet_lower, interface=None)
        self.bridge.mqtt_client.publish.assert_not_called()

    def test_tampered_signature_is_rejected(self):
        packet = self.make_packet(
            "!aaaa1111", "shelly1-sim01", "ON", 1, sig="deadbeef"
        )
        self.bridge.on_meshtastic_receive(packet, interface=None)
        self.bridge.mqtt_client.publish.assert_not_called()

    def test_missing_required_fields_is_rejected(self):
        base = {"target": "shelly1-sim01", "action": "ON", "seq": 1,
                "sig": compute_hmac_sig(self.secret, "shelly1-sim01", "ON", 1)}
        for missing_field in ("target", "action", "seq", "sig"):
            cmd = dict(base)
            del cmd[missing_field]
            packet = {"fromId": "!aaaa1111", "decoded": {"text": json.dumps(cmd)}}
            self.bridge.on_meshtastic_receive(packet, interface=None)
            self.bridge.mqtt_client.publish.assert_not_called()

    def test_non_json_text_is_ignored_without_crash(self):
        packet = {"fromId": "!aaaa1111", "decoded": {"text": "just a chat message"}}
        self.bridge.on_meshtastic_receive(packet, interface=None)
        self.bridge.mqtt_client.publish.assert_not_called()

    def test_empty_text_is_ignored_without_crash(self):
        packet = {"fromId": "!aaaa1111", "decoded": {}}
        self.bridge.on_meshtastic_receive(packet, interface=None)
        self.bridge.mqtt_client.publish.assert_not_called()


class TestOnMqttMessageFeedback(unittest.TestCase):
    def setUp(self):
        self.bridge = MeshtasticMQTTBridge(secret="TestSecret123", allowed_nodes=["*"])
        self.bridge.mesh_iface = MagicMock()

    def make_msg(self, topic, payload):
        msg = MagicMock()
        msg.topic = topic
        msg.payload = payload.encode("utf-8")
        return msg

    def test_gen1_status_topic_sends_ack_when_pending(self):
        self.bridge.pending_requests["shelly1-sim01"] = {
            "from_id": "!aaaa1111",
            "seq": 3,
            "timestamp": 0.0,
        }
        msg = self.make_msg("shellies/shelly1-sim01/relay/0", "on")
        self.bridge.on_mqtt_message(None, None, msg)

        self.bridge.mesh_iface.sendText.assert_called_once()
        args, kwargs = self.bridge.mesh_iface.sendText.call_args
        ack = json.loads(args[0])
        self.assertEqual(ack["device"], "shelly1-sim01")
        self.assertEqual(ack["state"], "ON")
        self.assertEqual(ack["ack_seq"], 3)
        self.assertEqual(kwargs.get("destinationId"), "!aaaa1111")

    def test_gen2_status_topic_resolves_on_state(self):
        self.bridge.pending_requests["shelly1-sim01"] = {
            "from_id": "!aaaa1111",
            "seq": 9,
            "timestamp": 0.0,
        }
        msg = self.make_msg(
            "shelly1-sim01/status/switch:0", json.dumps({"output": True})
        )
        self.bridge.on_mqtt_message(None, None, msg)

        self.bridge.mesh_iface.sendText.assert_called_once()
        args, _ = self.bridge.mesh_iface.sendText.call_args
        ack = json.loads(args[0])
        self.assertEqual(ack["state"], "ON")
        self.assertEqual(ack["ack_seq"], 9)

    def test_gen2_status_topic_resolves_off_state(self):
        self.bridge.pending_requests["shelly1-sim01"] = {
            "from_id": "!aaaa1111",
            "seq": 9,
            "timestamp": 0.0,
        }
        msg = self.make_msg(
            "shelly1-sim01/status/switch:0", json.dumps({"output": False})
        )
        self.bridge.on_mqtt_message(None, None, msg)

        args, _ = self.bridge.mesh_iface.sendText.call_args
        ack = json.loads(args[0])
        self.assertEqual(ack["state"], "OFF")

    def test_no_pending_request_does_not_send_text(self):
        msg = self.make_msg("shellies/shelly1-sim01/relay/0", "on")
        self.bridge.on_mqtt_message(None, None, msg)
        self.bridge.mesh_iface.sendText.assert_not_called()


if __name__ == "__main__":
    unittest.main()
