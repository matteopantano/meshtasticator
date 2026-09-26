from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(REPO_ROOT / ".env")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class GatewaySettings(BaseModel):
    app_title: str = "RAK4630 Remote Control"
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    mock_meshtastic: bool = False
    meshtastic_use_serial: bool = True
    meshtastic_device: str = "/dev/ttyACM0"
    meshtastic_host: str = "localhost"
    meshtastic_port: int = 4404
    meshtastic_destination: str = "^all"
    control_secret: str = "MeshShellySecret2026"
    target_device_id: str = "shelly1-sim01"
    command_timeout_seconds: int = 8
    log_level: str = "INFO"
    commands_json: Optional[str] = None
    reconnect_interval_seconds: int = Field(default=5, ge=1)

    @classmethod
    def from_env(cls) -> "GatewaySettings":
        return cls(
            app_title=os.getenv("APP_TITLE", cls.model_fields["app_title"].default),
            web_host=os.getenv("WEB_HOST", cls.model_fields["web_host"].default),
            web_port=int(os.getenv("WEB_PORT", cls.model_fields["web_port"].default)),
            mock_meshtastic=_env_bool("MOCK_MESHTASTIC", cls.model_fields["mock_meshtastic"].default),
            meshtastic_use_serial=_env_bool(
                "MESHTASTIC_USE_SERIAL",
                cls.model_fields["meshtastic_use_serial"].default,
            ),
            meshtastic_device=os.getenv("MESHTASTIC_DEVICE", cls.model_fields["meshtastic_device"].default),
            meshtastic_host=os.getenv("MESHTASTIC_HOST", cls.model_fields["meshtastic_host"].default),
            meshtastic_port=int(os.getenv("MESHTASTIC_PORT", cls.model_fields["meshtastic_port"].default)),
            meshtastic_destination=os.getenv(
                "MESHTASTIC_DESTINATION",
                cls.model_fields["meshtastic_destination"].default,
            ),
            control_secret=os.getenv("CONTROL_SECRET", cls.model_fields["control_secret"].default),
            target_device_id=os.getenv(
                "TARGET_DEVICE_ID",
                cls.model_fields["target_device_id"].default,
            ),
            command_timeout_seconds=int(
                os.getenv(
                    "COMMAND_TIMEOUT_SECONDS",
                    cls.model_fields["command_timeout_seconds"].default,
                )
            ),
            log_level=os.getenv("LOG_LEVEL", cls.model_fields["log_level"].default),
            commands_json=os.getenv("COMMANDS_JSON"),
            reconnect_interval_seconds=int(
                os.getenv(
                    "RECONNECT_INTERVAL_SECONDS",
                    cls.model_fields["reconnect_interval_seconds"].default,
                )
            ),
        )

    @property
    def static_dir(self) -> Path:
        return PROJECT_ROOT / "app" / "static"

    @property
    def sender_script_path(self) -> Path:
        return REPO_ROOT / "meshtasticd-config" / "send_control_cmd.py"
