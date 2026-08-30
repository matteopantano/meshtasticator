"""Unit tests for meshtasticd-config/shelly_simulator.py.

These tests exercise the Gen 1 and Gen 2 (RPC) Shelly command handling and
status publication logic entirely in-process: no real MQTT broker
connection is made. The module under test is loaded dynamically via
importlib because `meshtasticd-config` is not an importable Python package
(dashed directory name, no `__init__.py`), following the same pattern used
in tests/test_interactive.py.
"""

import importlib.util
import json
import os
import unittest
from unittest.mock import MagicMock


def load_shelly_simulator():
    module_name = "_shelly_simulator_under_test"
    module_path = os.path.join(
        os.path.dirname(__file__), "..", "meshtasticd-config", "shelly_simulator.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shelly_simulator = load_shelly_simulator()
ShellySimulator = shelly_simulator.ShellySimulator


def make_msg(topic, payload):
    msg = MagicMock()
    msg.topic = topic
    msg.payload = payload.encode("utf-8")
    return msg


class TestGen1CommandHandling(unittest.TestCase):
    def setUp(self):
        self.sim = ShellySimulator(device_id="shelly1-sim01")
        self.sim.client = MagicMock()
        self.topic = "shellies/shelly1-sim01/relay/0/command"

    def test_on_variants_set_state_true(self):
        for cmd in ("on", "1", "true"):
            self.sim.state = False
            self.sim.on_message(None, None, make_msg(self.topic, cmd))
            self.assertTrue(self.sim.state, f"command {cmd!r} should set state True")

    def test_off_variants_set_state_false(self):
        for cmd in ("off", "0", "false"):
            self.sim.state = True
            self.sim.on_message(None, None, make_msg(self.topic, cmd))
            self.assertFalse(self.sim.state, f"command {cmd!r} should set state False")

    def test_toggle_variants_flip_state(self):
        self.sim.state = False
        self.sim.on_message(None, None, make_msg(self.topic, "toggle"))
        self.assertTrue(self.sim.state)
        self.sim.on_message(None, None, make_msg(self.topic, "t"))
        self.assertFalse(self.sim.state)

    def test_unknown_command_leaves_state_unchanged_no_raise(self):
        self.sim.state = True
        self.sim.on_message(None, None, make_msg(self.topic, "banana"))
        self.assertTrue(self.sim.state)

    def test_valid_command_publishes_state(self):
        self.sim.state = False
        self.sim.on_message(None, None, make_msg(self.topic, "on"))

        calls = self.sim.client.publish.call_args_list
        self.assertEqual(len(calls), 2)

        gen1_call = calls[0]
        self.assertEqual(gen1_call.args[0], "shellies/shelly1-sim01/relay/0")
        self.assertEqual(gen1_call.args[1], "on")

        gen2_call = calls[1]
        self.assertEqual(gen2_call.args[0], "shelly1-sim01/status/switch:0")
        payload = json.loads(gen2_call.args[1])
        self.assertTrue(payload["output"])

    def test_unknown_command_does_not_publish(self):
        self.sim.state = False
        self.sim.on_message(None, None, make_msg(self.topic, "banana"))
        self.sim.client.publish.assert_not_called()


class TestGen2RpcHandling(unittest.TestCase):
    def setUp(self):
        self.sim = ShellySimulator(device_id="shelly1-sim01")
        self.sim.client = MagicMock()
        self.topic = "shelly1-sim01/rpc"

    def test_switch_set_on_true(self):
        self.sim.state = False
        payload = json.dumps({"method": "Switch.Set", "params": {"on": True}})
        self.sim.on_message(None, None, make_msg(self.topic, payload))
        self.assertTrue(self.sim.state)
        self.sim.client.publish.assert_called()

    def test_switch_set_on_false(self):
        self.sim.state = True
        payload = json.dumps({"method": "Switch.Set", "params": {"on": False}})
        self.sim.on_message(None, None, make_msg(self.topic, payload))
        self.assertFalse(self.sim.state)

    def test_switch_toggle_flips_state(self):
        self.sim.state = False
        payload = json.dumps({"method": "Switch.Toggle"})
        self.sim.on_message(None, None, make_msg(self.topic, payload))
        self.assertTrue(self.sim.state)
        self.sim.on_message(None, None, make_msg(self.topic, payload))
        self.assertFalse(self.sim.state)

    def test_switch_get_status_does_not_change_state_but_republishes(self):
        self.sim.state = True
        payload = json.dumps({"method": "Switch.GetStatus"})
        self.sim.on_message(None, None, make_msg(self.topic, payload))
        self.assertTrue(self.sim.state)
        self.sim.client.publish.assert_called()

    def test_unsupported_method_does_not_raise_and_does_not_publish(self):
        self.sim.state = False
        payload = json.dumps({"method": "Switch.FooBar"})
        self.sim.on_message(None, None, make_msg(self.topic, payload))
        self.assertFalse(self.sim.state)
        self.sim.client.publish.assert_not_called()

    def test_malformed_json_payload_does_not_raise(self):
        self.sim.state = False
        try:
            self.sim.on_message(None, None, make_msg(self.topic, "{not valid json"))
        except Exception as e:  # pragma: no cover - explicit failure path
            self.fail(f"on_message raised unexpectedly on malformed JSON: {e}")
        self.assertFalse(self.sim.state)
        self.sim.client.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
