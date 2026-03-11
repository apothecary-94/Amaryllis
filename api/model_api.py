from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from runtime.errors import ProviderError, ValidationError

router = APIRouter(tags=["models"])


class DownloadModelRequest(BaseModel):
    model_id: str = Field(min_length=1)
    provider: str | None = None


class LoadModelRequest(BaseModel):
    model_id: str = Field(min_length=1)
    provider: str | None = None


class ModelRouteRequest(BaseModel):
    mode: str = Field(default="balanced")
    provider: str | None = None
    model: str | None = None
    require_stream: bool = True
    require_tools: bool = False
    prefer_local: bool | None = None
    min_params_b: float | None = Field(default=None, ge=0.0)
    max_params_b: float | None = Field(default=None, ge=0.0)
    include_suggested: bool = False
    limit_per_provider: int = Field(default=120, ge=1, le=500)


@router.get("/models")
def list_models(request: Request) -> dict[str, Any]:
    services = request.app.state.services
    return services.model_manager.list_models()


@router.get("/models/capabilities")
def model_capabilities(request: Request) -> dict[str, Any]:
    services = request.app.state.services
    return {
        "active": {
            "provider": services.model_manager.active_provider,
            "model": services.model_manager.active_model,
        },
        "providers": services.model_manager.provider_capabilities(),
    }


@router.get("/models/capability-matrix")
def capability_matrix(
    request: Request,
    include_suggested: bool = True,
    limit_per_provider: int = 120,
) -> dict[str, Any]:
    services = request.app.state.services
    return services.model_manager.model_capability_matrix(
        include_suggested=include_suggested,
        limit_per_provider=max(1, min(limit_per_provider, 500)),
    )


@router.post("/models/route")
def model_route(payload: ModelRouteRequest, request: Request) -> dict[str, Any]:
    services = request.app.state.services
    try:
        return services.model_manager.choose_route(
            mode=payload.mode,
            provider=payload.provider,
            model=payload.model,
            require_stream=payload.require_stream,
            require_tools=payload.require_tools,
            prefer_local=payload.prefer_local,
            min_params_b=payload.min_params_b,
            max_params_b=payload.max_params_b,
            include_suggested=payload.include_suggested,
            limit_per_provider=payload.limit_per_provider,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


@router.post("/models/download")
def download_model(payload: DownloadModelRequest, request: Request) -> dict[str, Any]:
    services = request.app.state.services
    try:
        return services.model_manager.download_model(
            model_id=payload.model_id,
            provider=payload.provider,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


@router.post("/models/load")
def load_model(payload: LoadModelRequest, request: Request) -> dict[str, Any]:
    services = request.app.state.services
    try:
        return services.model_manager.load_model(
            model_id=payload.model_id,
            provider=payload.provider,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc
