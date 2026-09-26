import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.commands.registry import CommandRegistry
from app.config import GatewaySettings


class TestCommandRegistry(unittest.TestCase):
    def test_default_registry_uses_existing_action_structure(self):
        settings = GatewaySettings(target_device_id="relay-01")

        registry = CommandRegistry.from_settings(settings)
        commands = registry.list_commands()

        self.assertEqual([command.command for command in commands], ["ON", "OFF", "TOGGLE"])
        self.assertEqual([command.target for command in commands], ["relay-01", "relay-01", "relay-01"])

    def test_custom_registry_can_map_ui_names_to_existing_target_action(self):
        settings = GatewaySettings(
            commands_json='[{"command":"OPEN_GATE","label":"Open Gate","target":"gate-01","action":"ON"}]'
        )

        registry = CommandRegistry.from_settings(settings)
        resolved = registry.resolve("OPEN_GATE")

        self.assertEqual(resolved.target, "gate-01")
        self.assertEqual(resolved.action, "ON")


if __name__ == "__main__":
    unittest.main()
