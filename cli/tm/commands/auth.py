from __future__ import annotations

import argparse
import hashlib
from typing import cast

from tm.auth.capability_token import ALL_CAPABILITIES, compute_auth_context_hash, validate_capability_set
from tm.types import ApiRequest, JSONObject


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("auth", help="Manage short-lived CLI operation tokens")
    nested = parser.add_subparsers(dest="auth_command", required=True)

    login_parser = nested.add_parser("login", help="Issue a short-lived operation token")
    login_parser.add_argument("--device-id")
    login_parser.add_argument("--ttl-minutes", type=int, default=5)
    login_parser.add_argument("--auth-method", choices=("keyring", "sops", "env", "plain"), default="env")
    login_parser.add_argument("--allow-action", action="append", dest="allowed_actions")
    login_parser.set_defaults(tm_builder=_login)

    refresh_parser = nested.add_parser("refresh", help="Refresh an operation token")
    refresh_parser.add_argument("--ttl-minutes", type=int, default=5)
    refresh_parser.set_defaults(tm_builder=_refresh)

    revoke_parser = nested.add_parser("revoke", help="Revoke an operation token")
    revoke_parser.set_defaults(tm_builder=_revoke)


def _login(args: argparse.Namespace) -> ApiRequest:
    actions = validate_capability_set(cast(list[str] | None, args.allowed_actions) or ALL_CAPABILITIES)
    auth_method = str(args.auth_method)
    credential_ref = "env:TASKMANAGEDAI_OPERATION_TOKEN" if auth_method == "env" else auth_method
    body: JSONObject = {
        "allowed_actions": list(actions),
        "scope_constraint": {"scope": "project_user_minimum"},
        "auth_method": auth_method,
        "auth_context_hash": compute_auth_context_hash(auth_method, credential_ref),
        "request_binding_hash": hashlib.sha256(
            f"{auth_method}:{args.device_id or ''}:{','.join(actions)}".encode()
        ).hexdigest(),
        "ttl_minutes": int(args.ttl_minutes),
    }
    if args.project is not None:
        body["project_id"] = args.project
    if args.device_id is not None:
        body["device_id"] = args.device_id
    return ApiRequest(
        method="POST",
        path="/api/v1/auth/cli-login",
        capability="auth_cli_login",
        json_body=body,
        mutating=True,
        requires_project=False,
    )


def _refresh(args: argparse.Namespace) -> ApiRequest:
    return ApiRequest(
        method="POST",
        path="/api/v1/auth/cli-token/refresh",
        capability="auth_cli_refresh",
        json_body={"operation_token": "", "ttl_minutes": int(args.ttl_minutes)},
        mutating=True,
        requires_project=False,
    )


def _revoke(args: argparse.Namespace) -> ApiRequest:
    return ApiRequest(
        method="POST",
        path="/api/v1/auth/cli-token/revoke",
        capability="auth_cli_revoke",
        json_body={"operation_token": ""},
        mutating=True,
        requires_project=False,
    )
