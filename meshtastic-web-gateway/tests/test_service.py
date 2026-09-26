import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.commands.registry import CommandRegistry, RegisteredCommand
from app.commands.service import CommandService


class FakeAdapter:
    def __init__(self):
        self.sent = []

    def send_command(self, command: RegisteredCommand):
        self.sent.append(command)
        return {"success": True, "status": "ack", "command": command.command}

    def get_status(self):
        return {"connected": True, "device": "/dev/ttyACM0", "mock_mode": False}


class TestCommandService(unittest.TestCase):
    def test_service_dispatches_known_command(self):
        registry = CommandRegistry([
            RegisteredCommand(command="OPEN_GATE", label="Open Gate", target="gate-01", action="ON")
        ])
        adapter = FakeAdapter()
        service = CommandService(registry, adapter)

        response = service.send("OPEN_GATE")

        self.assertTrue(response["success"])
        self.assertEqual(response["status"], "ack")
        self.assertEqual(adapter.sent[0].target, "gate-01")
        self.assertEqual(adapter.sent[0].action, "ON")

    def test_service_rejects_unknown_command(self):
        registry = CommandRegistry([
            RegisteredCommand(command="ON", label="Relay ON", target="relay-01", action="ON")
        ])
        service = CommandService(registry, FakeAdapter())

        with self.assertRaises(KeyError):
            service.send("DOES_NOT_EXIST")


if __name__ == "__main__":
    unittest.main()
