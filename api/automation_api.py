from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, Field

from runtime.errors import NotFoundError, ProviderError, ValidationError

router = APIRouter(tags=["automations"])


class CreateAutomationRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    session_id: str | None = None
    interval_sec: int | None = Field(default=None, ge=10, le=86400)
    schedule_type: str | None = Field(default=None)
    schedule: dict[str, Any] = Field(default_factory=dict)
    timezone: str = Field(default="UTC", min_length=1)
    start_immediately: bool = False


@router.post("/automations/create")
def create_automation(payload: CreateAutomationRequest, request: Request) -> dict[str, Any]:
    services = request.app.state.services
    try:
        automation = services.automation_scheduler.create_automation(
            agent_id=payload.agent_id,
            user_id=payload.user_id,
            session_id=payload.session_id,
            message=payload.message,
            interval_sec=payload.interval_sec,
            schedule_type=payload.schedule_type,
            schedule=payload.schedule,
            timezone_name=payload.timezone,
            start_immediately=payload.start_immediately,
        )
        return {
            "automation": automation,
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


class UpdateAutomationRequest(BaseModel):
    message: str | None = None
    session_id: str | None = None
    interval_sec: int | None = Field(default=None, ge=10, le=86400)
    schedule_type: str | None = None
    schedule: dict[str, Any] | None = None
    timezone: str | None = None


@router.post("/automations/{automation_id}/update")
def update_automation(
    payload: UpdateAutomationRequest,
    request: Request,
    automation_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    services = request.app.state.services
    try:
        automation = services.automation_scheduler.update_automation(
            automation_id=automation_id,
            message=payload.message,
            session_id=payload.session_id,
            interval_sec=payload.interval_sec,
            schedule_type=payload.schedule_type,
            schedule=payload.schedule,
            timezone_name=payload.timezone,
        )
        return {
            "automation": automation,
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise NotFoundError(str(exc)) from exc
        raise ValidationError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


@router.get("/automations")
def list_automations(
    request: Request,
    user_id: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    services = request.app.state.services
    try:
        items = services.automation_scheduler.list_automations(
            user_id=user_id,
            agent_id=agent_id,
            enabled=enabled,
            limit=limit,
        )
        return {
            "items": items,
            "count": len(items),
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


@router.get("/automations/{automation_id}")
def get_automation(
    request: Request,
    automation_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    services = request.app.state.services
    automation = services.automation_scheduler.get_automation(automation_id)
    if automation is None:
        raise NotFoundError(f"Automation not found: {automation_id}")
    return {
        "automation": automation,
        "request_id": str(getattr(request.state, "request_id", "")),
    }


@router.post("/automations/{automation_id}/pause")
def pause_automation(
    request: Request,
    automation_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    services = request.app.state.services
    try:
        automation = services.automation_scheduler.pause_automation(automation_id)
        return {
            "automation": automation,
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


@router.post("/automations/{automation_id}/resume")
def resume_automation(
    request: Request,
    automation_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    services = request.app.state.services
    try:
        automation = services.automation_scheduler.resume_automation(automation_id)
        return {
            "automation": automation,
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


@router.post("/automations/{automation_id}/run")
def run_automation_now(
    request: Request,
    automation_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    services = request.app.state.services
    try:
        automation = services.automation_scheduler.run_now(automation_id)
        return {
            "automation": automation,
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


@router.delete("/automations/{automation_id}")
def delete_automation(
    request: Request,
    automation_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    services = request.app.state.services
    try:
        deleted = services.automation_scheduler.delete_automation(automation_id)
        if not deleted:
            raise NotFoundError(f"Automation not found: {automation_id}")
        return {
            "status": "deleted",
            "automation_id": automation_id,
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except NotFoundError:
        raise
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


@router.get("/automations/{automation_id}/events")
def list_automation_events(
    request: Request,
    automation_id: str = Path(..., min_length=1),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    services = request.app.state.services
    automation = services.automation_scheduler.get_automation(automation_id)
    if automation is None:
        raise NotFoundError(f"Automation not found: {automation_id}")
    try:
        items = services.automation_scheduler.list_events(automation_id=automation_id, limit=limit)
        return {
            "items": items,
            "count": len(items),
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except Exception as exc:
        raise ProviderError(str(exc)) from exc
