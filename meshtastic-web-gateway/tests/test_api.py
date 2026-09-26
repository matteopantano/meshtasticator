import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import create_app


class FakeAdapter:
    def refresh_connection_status(self):
        return True


class FakeService:
    def __init__(self):
        self.adapter = FakeAdapter()
        self.sent = []

    def get_status(self):
        return {
            "meshtastic": {"connected": True, "device": "/dev/ttyACM0", "mock_mode": False},
            "last_command": self.sent[-1] if self.sent else None,
            "last_command_status": "ack" if self.sent else "idle",
            "available_commands": [
                {"command": "OPEN_GATE", "label": "Open Gate", "target": "gate-01", "action": "ON", "variant": "success"}
            ],
        }

    def send(self, command_name: str):
        if command_name != "OPEN_GATE":
            raise KeyError("Unknown command")
        self.sent.append(command_name)
        return {"success": True, "command": command_name, "status": "ack", "detail": {"success": True}}


class TestApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(command_service=FakeService()))

    def test_status_endpoint(self):
        response = self.client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["meshtastic"]["connected"])

    def test_command_endpoint(self):
        response = self.client.post("/api/commands", json={"command": "OPEN_GATE"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ack")

    def test_invalid_command_returns_400(self):
        response = self.client.post("/api/commands", json={"command": "NOPE"})

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
