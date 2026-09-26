from __future__ import annotations

import json
from typing import Dict, Iterable, List, Literal

from pydantic import BaseModel, Field, field_validator

from app.config import GatewaySettings


class RegisteredCommand(BaseModel):
    command: str = Field(min_length=1)
    label: str = Field(min_length=1)
    target: str = Field(min_length=1)
    action: Literal["ON", "OFF", "TOGGLE"]
    variant: str = "primary"

    @field_validator("command", "label", "target")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("action")
    @classmethod
    def _normalize_action(cls, value: str) -> str:
        return value.upper()


class CommandRegistry:
    def __init__(self, commands: Iterable[RegisteredCommand]):
        self._commands: Dict[str, RegisteredCommand] = {
            command.command: command for command in commands
        }
        if not self._commands:
            raise ValueError("At least one command must be configured")

    @classmethod
    def from_settings(cls, settings: GatewaySettings) -> "CommandRegistry":
        if settings.commands_json:
            payload = json.loads(settings.commands_json)
            commands = [RegisteredCommand.model_validate(item) for item in payload]
            return cls(commands)

        target = settings.target_device_id
        return cls(
            [
                RegisteredCommand(command="ON", label="Relay ON", target=target, action="ON", variant="success"),
                RegisteredCommand(command="OFF", label="Relay OFF", target=target, action="OFF", variant="danger"),
                RegisteredCommand(command="TOGGLE", label="Relay Toggle", target=target, action="TOGGLE", variant="secondary"),
            ]
        )

    def resolve(self, command_name: str) -> RegisteredCommand:
        try:
            return self._commands[command_name]
        except KeyError as exc:
            raise KeyError(f"Unknown command '{command_name}'") from exc

    def list_commands(self) -> List[RegisteredCommand]:
        return list(self._commands.values())
