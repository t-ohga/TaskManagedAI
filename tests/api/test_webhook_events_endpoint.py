"""ADR-00050 (SP-028) webhook events read endpoint の wiring 契約 test (DB 不要)。

Codex adversarial F-1: project join だけでは actor->project 認可を保証しない。read endpoint が
``require_project_owner`` owner gate を **確実に経由している** ことを drift guard として固定する
(gate を外す regression を host で検出する)。owner gate の非 owner -> 403 挙動自体は
``tests/api/test_me_secret_refs.py`` / ``tests/api/test_me_data_management.py`` で既に固定済。
"""

from __future__ import annotations

import inspect

from backend.app.api.me import require_project_owner
from backend.app.api.webhook_events import list_webhook_events_endpoint


def test_read_endpoint_is_guarded_by_project_owner() -> None:
    """list endpoint が require_project_owner dependency を経由する (cross-project/actor leak 防止、F-1)。"""
    signature = inspect.signature(list_webhook_events_endpoint)
    owner_param = signature.parameters["_owner_actor_id"]
    # FastAPI Depends marker の .dependency が owner gate を指すこと。
    assert getattr(owner_param.default, "dependency", None) is require_project_owner


def test_read_endpoint_does_not_use_bare_actor_dependency() -> None:
    """owner gate を bare get_current_actor_id に巻き戻していないこと (gate 退行 drift guard)。"""
    from backend.app.api.approval_inbox import get_current_actor_id

    signature = inspect.signature(list_webhook_events_endpoint)
    dependencies = [
        getattr(param.default, "dependency", None)
        for param in signature.parameters.values()
    ]
    assert get_current_actor_id not in dependencies
    assert require_project_owner in dependencies
