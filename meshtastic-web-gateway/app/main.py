from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.commands.registry import CommandRegistry
from app.commands.service import CommandService
from app.config import GatewaySettings
from app.meshtastic.adapter import ExistingMeshtasticAdapter


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_command_service(settings: GatewaySettings) -> CommandService:
    registry = CommandRegistry.from_settings(settings)
    adapter = ExistingMeshtasticAdapter(settings)
    return CommandService(registry=registry, adapter=adapter, logger=logging.getLogger("gateway.commands"))


def create_app(
    settings: Optional[GatewaySettings] = None,
    command_service: Optional[CommandService] = None,
) -> FastAPI:
    settings = settings or GatewaySettings.from_env()
    configure_logging(settings.log_level)
    logger = logging.getLogger("gateway")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting RAK4630 web gateway")
        if app.state.command_service is not None:
            app.state.command_service.adapter.refresh_connection_status()
        yield
        logger.info("Stopping RAK4630 web gateway")

    app = FastAPI(title=settings.app_title, lifespan=lifespan)
    app.state.settings = settings
    app.state.command_service = command_service or build_command_service(settings)
    app.include_router(router)

    static_dir = Path(settings.static_dir)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(static_dir / "index.html")

    return app


app = create_app()
