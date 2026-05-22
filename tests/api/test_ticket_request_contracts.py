from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.tickets import (
    TicketCreateRequest,
    TicketUpdateRequest,
    update_ticket_endpoint,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000077001")
TICKET_ID = UUID("00000000-0000-4000-8000-000000077002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000077003")


def _base_create_payload() -> dict[str, object]:
    return {
        "slug": "ticket-request-contract",
        "title": "Ticket request contract",
        "description": "safe description",
        "status": "open",
    }


def _assert_single_extra_error(
    error: ValidationError,
    field_name: str,
) -> None:
    assert [
        (entry["type"], entry["loc"])
        for entry in error.errors()
    ] == [("extra_forbidden", (field_name,))]


def test_ticket_create_request_rejects_caller_supplied_project_id() -> None:
    payload = _base_create_payload() | {"project_id": str(PROJECT_ID)}

    with pytest.raises(ValidationError) as exc_info:
        TicketCreateRequest.model_validate(payload)

    _assert_single_extra_error(exc_info.value, "project_id")


def test_ticket_create_request_rejects_caller_supplied_tenant_id() -> None:
    payload = _base_create_payload() | {"tenant_id": 1}

    with pytest.raises(ValidationError) as exc_info:
        TicketCreateRequest.model_validate(payload)

    _assert_single_extra_error(exc_info.value, "tenant_id")


def test_ticket_create_request_rejects_caller_supplied_created_by_actor_id() -> None:
    payload = _base_create_payload() | {"created_by_actor_id": str(ACTOR_ID)}

    with pytest.raises(ValidationError) as exc_info:
        TicketCreateRequest.model_validate(payload)

    _assert_single_extra_error(exc_info.value, "created_by_actor_id")


def test_ticket_update_request_rejects_caller_supplied_project_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TicketUpdateRequest.model_validate(
            {"title": "New title", "project_id": str(PROJECT_ID)}
        )

    _assert_single_extra_error(exc_info.value, "project_id")


def test_ticket_update_request_rejects_caller_supplied_tenant_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TicketUpdateRequest.model_validate({"title": "New title", "tenant_id": 1})

    _assert_single_extra_error(exc_info.value, "tenant_id")


def test_ticket_update_request_rejects_caller_supplied_created_by_actor_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TicketUpdateRequest.model_validate(
            {"title": "New title", "created_by_actor_id": str(ACTOR_ID)}
        )

    _assert_single_extra_error(exc_info.value, "created_by_actor_id")


def test_ticket_update_request_omits_absent_description() -> None:
    payload = TicketUpdateRequest.model_validate({"title": "New title"})

    assert payload.model_dump(exclude_unset=True) == {"title": "New title"}


def test_ticket_update_request_preserves_null_description_clear() -> None:
    payload = TicketUpdateRequest.model_validate({"description": None})

    assert payload.model_dump(exclude_unset=True) == {"description": None}


def test_ticket_update_request_preserves_empty_string_description_clear() -> None:
    payload = TicketUpdateRequest.model_validate({"description": ""})

    assert payload.model_dump(exclude_unset=True) == {"description": ""}


@pytest.mark.asyncio
async def test_update_ticket_endpoint_rejects_empty_payload_before_db_access() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await update_ticket_endpoint(
            project_id=PROJECT_ID,
            ticket_id=TICKET_ID,
            payload=TicketUpdateRequest(),
            actor_id=ACTOR_ID,
            tenant_id=1,
            session=cast(AsyncSession, object()),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "empty update payload"
