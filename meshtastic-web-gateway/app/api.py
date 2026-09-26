from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


class CommandRequest(BaseModel):
    command: str = Field(min_length=1)


class CommandResponse(BaseModel):
    success: bool
    command: str
    status: str
    detail: Dict[str, Any]


class MeshtasticStatusResponse(BaseModel):
    connected: bool
    device: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    mock_mode: bool = False
    last_error: Optional[str] = None


class StatusResponse(BaseModel):
    meshtastic: MeshtasticStatusResponse
    last_command: Optional[str] = None
    last_command_status: str
    available_commands: List[Dict[str, Any]]


class AvailableCommandsResponse(BaseModel):
    commands: List[Dict[str, Any]]


router = APIRouter()


@router.get("/api/status", response_model=StatusResponse)
def get_status(request: Request) -> Dict[str, Any]:
    return request.app.state.command_service.get_status()


@router.get("/api/commands", response_model=AvailableCommandsResponse)
def get_commands(request: Request) -> Dict[str, Any]:
    status = request.app.state.command_service.get_status()
    return {"commands": status["available_commands"]}


@router.post("/api/commands", response_model=CommandResponse)
def post_command(payload: CommandRequest, request: Request) -> Dict[str, Any]:
    try:
        return request.app.state.command_service.send(payload.command)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
