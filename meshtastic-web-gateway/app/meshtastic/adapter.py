from __future__ import annotations

import importlib.util
import logging
from types import ModuleType
from typing import Any, Dict, Optional

from app.commands.registry import RegisteredCommand
from app.config import GatewaySettings


class ExistingMeshtasticAdapter:
    def __init__(
        self,
        settings: GatewaySettings,
        sender_module: Optional[ModuleType] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self.sender_module = sender_module or self._load_sender_module()
        self.connected = bool(settings.mock_meshtastic)
        self.last_error: Optional[str] = None

    def _load_sender_module(self) -> ModuleType:
        script_path = self.settings.sender_script_path
        spec = importlib.util.spec_from_file_location("existing_send_control_cmd", script_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load existing sender from {script_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _build_sender(self, verbose: bool = False):
        kwargs = {"verbose": verbose}
        if self.settings.meshtastic_use_serial:
            kwargs["serial_port"] = self.settings.meshtastic_device
        else:
            kwargs["host"] = self.settings.meshtastic_host
            kwargs["port"] = self.settings.meshtastic_port
        return self.sender_module.MeshtasticSender(**kwargs)

    def refresh_connection_status(self) -> bool:
        if self.settings.mock_meshtastic:
            self.connected = True
            self.last_error = None
            return True

        sender = None
        try:
            sender = self._build_sender(verbose=False)
            self.connected = True
            self.last_error = None
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            self.logger.warning("Meshtastic connection check failed: %s", exc)
        finally:
            if sender is not None:
                sender.close()
        return self.connected

    def get_status(self) -> Dict[str, Any]:
        self.refresh_connection_status()
        status = {
            "connected": self.connected,
            "device": self.settings.meshtastic_device if self.settings.meshtastic_use_serial else None,
            "host": None if self.settings.meshtastic_use_serial else self.settings.meshtastic_host,
            "port": None if self.settings.meshtastic_use_serial else self.settings.meshtastic_port,
            "mock_mode": self.settings.mock_meshtastic,
        }
        if self.last_error:
            status["last_error"] = self.last_error
        return status

    def send_command(self, command: RegisteredCommand) -> Dict[str, Any]:
        if self.settings.mock_meshtastic:
            self.connected = True
            self.last_error = None
            self.logger.info("MOCK send: %s -> target=%s action=%s", command.command, command.target, command.action)
            return {
                "success": True,
                "status": "mock-sent",
                "command": command.command,
                "target": command.target,
                "action": command.action,
                "ack": None,
            }

        sender = None
        try:
            sender = self._build_sender(verbose=False)
            result = sender.send_command(
                target=command.target,
                action=command.action,
                secret=self.settings.control_secret,
                dest=self.settings.meshtastic_destination,
                timeout=self.settings.command_timeout_seconds,
                verbose=False,
            )
            self.connected = True
            self.last_error = None
            result["success"] = True
            result["target"] = command.target
            result["action"] = command.action
            return result
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            self.logger.exception("Failed to send Meshtastic command %s", command.command)
            return {
                "success": False,
                "status": "error",
                "command": command.command,
                "target": command.target,
                "action": command.action,
                "error": str(exc),
            }
        finally:
            if sender is not None:
                sender.close()
