from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.commands.registry import CommandRegistry


class CommandService:
    def __init__(self, registry: CommandRegistry, adapter, logger: Optional[logging.Logger] = None):
        self.registry = registry
        self.adapter = adapter
        self.logger = logger or logging.getLogger(__name__)
        self.last_command: Optional[str] = None
        self.last_command_status: str = "idle"
        self.last_command_result: Optional[Dict[str, Any]] = None

    def send(self, command_name: str) -> Dict[str, Any]:
        command = self.registry.resolve(command_name)
        self.logger.info("Command requested: %s -> target=%s action=%s", command.command, command.target, command.action)
        result = self.adapter.send_command(command)
        self.last_command = command.command
        self.last_command_status = result["status"]
        self.last_command_result = result
        return {
            "success": result["success"],
            "command": command.command,
            "status": result["status"],
            "detail": result,
        }

    def get_status(self) -> Dict[str, Any]:
        transport = self.adapter.get_status()
        return {
            "meshtastic": transport,
            "last_command": self.last_command,
            "last_command_status": self.last_command_status,
            "available_commands": [command.model_dump() for command in self.registry.list_commands()],
        }
