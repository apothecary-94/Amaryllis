from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Query, Request

from runtime.auth import assert_owner, auth_context_from_request, resolve_user_id
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
    auth = auth_context_from_request(request)
    effective_user_id = resolve_user_id(request_user_id=user_id, auth=auth)
    try:
        items = services.automation_scheduler.list_inbox_items(
            user_id=effective_user_id,
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
    auth = auth_context_from_request(request)
    try:
        existing = services.database.get_inbox_item(item_id)
        if existing is None:
            raise NotFoundError(f"Inbox item not found: {item_id}")
        assert_owner(
            owner_user_id=str(existing.get("user_id") or ""),
            auth=auth,
            resource_name="inbox_item",
            resource_id=item_id,
        )
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
    auth = auth_context_from_request(request)
    try:
        existing = services.database.get_inbox_item(item_id)
        if existing is None:
            raise NotFoundError(f"Inbox item not found: {item_id}")
        assert_owner(
            owner_user_id=str(existing.get("user_id") or ""),
            auth=auth,
            resource_name="inbox_item",
            resource_id=item_id,
        )
        item = services.automation_scheduler.set_inbox_item_read(item_id=item_id, is_read=False)
        return {
            "item": item,
            "request_id": str(getattr(request.state, "request_id", "")),
        }
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc
