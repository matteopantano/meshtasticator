import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.commands.registry import RegisteredCommand
from app.config import GatewaySettings
from app.meshtastic.adapter import ExistingMeshtasticAdapter


class FakeSender:
    last_init_kwargs = None
    last_send_kwargs = None

    def __init__(self, **kwargs):
        type(self).last_init_kwargs = kwargs

    def send_command(self, **kwargs):
        type(self).last_send_kwargs = kwargs
        return {"success": True, "status": "ack", "ack": {"ack_seq": 99}}

    def close(self):
        return None


class FailingSender:
    def __init__(self, **kwargs):
        raise RuntimeError("radio unavailable")


class TestExistingMeshtasticAdapter(unittest.TestCase):
    def test_mock_mode_avoids_hardware(self):
        settings = GatewaySettings(mock_meshtastic=True)
        adapter = ExistingMeshtasticAdapter(settings, sender_module=SimpleNamespace(MeshtasticSender=FakeSender))

        result = adapter.send_command(
            RegisteredCommand(command="ON", label="Relay ON", target="relay-01", action="ON")
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "mock-sent")

    def test_real_mode_uses_existing_sender_over_serial(self):
        settings = GatewaySettings(
            meshtastic_use_serial=True,
            meshtastic_device="/dev/ttyACM9",
            control_secret="secret-1",
            meshtastic_destination="!abcd1234",
            command_timeout_seconds=3,
        )
        adapter = ExistingMeshtasticAdapter(settings, sender_module=SimpleNamespace(MeshtasticSender=FakeSender))

        result = adapter.send_command(
            RegisteredCommand(command="OPEN_GATE", label="Open Gate", target="gate-01", action="ON")
        )

        self.assertTrue(result["success"])
        self.assertEqual(FakeSender.last_init_kwargs["serial_port"], "/dev/ttyACM9")
        self.assertEqual(FakeSender.last_send_kwargs["target"], "gate-01")
        self.assertEqual(FakeSender.last_send_kwargs["action"], "ON")
        self.assertEqual(FakeSender.last_send_kwargs["secret"], "secret-1")
        self.assertEqual(FakeSender.last_send_kwargs["dest"], "!abcd1234")

    def test_connection_failure_is_reported(self):
        settings = GatewaySettings(mock_meshtastic=False)
        adapter = ExistingMeshtasticAdapter(settings, sender_module=SimpleNamespace(MeshtasticSender=FailingSender))

        status = adapter.get_status()

        self.assertFalse(status["connected"])
        self.assertIn("radio unavailable", status["last_error"])


if __name__ == "__main__":
    unittest.main()
