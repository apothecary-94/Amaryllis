from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Query, Request

from runtime.errors import NotFoundError, ProviderError

router = APIRouter(tags=["inbox"])


@router.get("/inbox")
def list_inbox_items(
    request: Request,
    user_id: str | None = Query(default=None),
    unread_only: bool = Query(default=False),
    category: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    services = request.app.state.services
    try:
        items = services.automation_scheduler.list_inbox_items(
            user_id=user_id,
            unread_only=unread_only,
            category=category,
            limit=limit,
        )
        return {
            "items": items,
            "count": len(items),
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


@router.post("/inbox/{item_id}/read")
def mark_inbox_item_read(
    request: Request,
    item_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    services = request.app.state.services
    try:
        item = services.automation_scheduler.set_inbox_item_read(item_id=item_id, is_read=True)
        return {
            "item": item,
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


@router.post("/inbox/{item_id}/unread")
def mark_inbox_item_unread(
    request: Request,
    item_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    services = request.app.state.services
    try:
        item = services.automation_scheduler.set_inbox_item_read(item_id=item_id, is_read=False)
        return {
            "item": item,
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc
