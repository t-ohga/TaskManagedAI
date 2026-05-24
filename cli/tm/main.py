from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TextIO, cast

from tm import __version__
from tm.auth.capability_token import APPROVAL_REQUIRED_CAPABILITIES, is_mutating_capability, resolve_operation_token
from tm.client import ApiClientError, ClientConfig, ClientProtocol, TaskManagedAIClient
from tm.commands import register_commands
from tm.config.profile_loader import ProfileConfigError, ProfileLoader, default_profile_loader_from_env
from tm.output import format_human, format_json, format_yaml
from tm.types import ApiRequest, JSONValue

ClientFactory = Callable[[ClientConfig], ClientProtocol]


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    profile_loader: ProfileLoader | None = None,
    client_factory: ClientFactory | None = None,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    environ = env or os.environ
    working_dir = cwd or Path.cwd()
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    if not hasattr(args, "tm_builder"):
        parser.print_help(err)
        return 2

    if bool(getattr(args, "tm_disabled", False)):
        _emit(
            {
                "error_code": "tm_memory_disabled",
                "message": "tm memory is disabled until SP-018 is accepted.",
            },
            args=args,
            stdout=out,
        )
        return 3

    loader = profile_loader or default_profile_loader_from_env(environ)
    try:
        profile = loader.load(str(args.profile), environ)
        request = _build_request(args)
    except (ProfileConfigError, ValueError) as exc:
        _emit_error("tm_config_error", str(exc), stderr=err)
        return 2

    request = _normalize_capability_flags(request)
    resolution = loader.resolve_project(
        explicit_project_id=cast(str | None, args.project),
        env=environ,
        profile=profile,
        cwd=working_dir,
    )
    if request.requires_project and resolution.project_id is None:
        if resolution.ambiguous_candidates:
            candidates = ", ".join(resolution.ambiguous_candidates)
            _emit_error(
                "tm_project_ambiguous",
                f"ambiguous project context ({candidates}), specify --project explicitly",
                stderr=err,
            )
        elif request.mutating or bool(args.no_interactive) or not _is_tty(out):
            _emit_error(
                "tm_project_unresolved",
                "ambiguous project context, specify --project explicitly",
                stderr=err,
            )
        else:
            _emit_error("tm_project_unresolved", "project context unresolved", stderr=err)
        return 2
    if bool(args.agent_mode) and request.mutating:
        _emit_error("tm_agent_mode_mutation_denied", "agent-mode cannot execute mutating commands", stderr=err)
        return 2
    if request.approval_required and (bool(args.no_interactive) or not _is_tty(out)):
        _emit_error(
            "tm_non_interactive_approval_denied",
            "approval-required command needs interactive approval",
            stderr=err,
        )
        return 2

    try:
        operation_token = resolve_operation_token(
            environ,
            token_override=cast(str | None, args.operation_token),
            auth_method=profile.auth_method,
            credential_ref=profile.refresh_credential_ref,
        )
    except ValueError as exc:
        _emit_error("tm_operation_token_config_error", str(exc), stderr=err)
        return 2
    try:
        request = _inject_operation_token(request, operation_token)
    except ValueError as exc:
        _emit_error("tm_operation_token_missing", str(exc), stderr=err)
        return 2
    request = request.with_project_id(resolution.project_id)
    client = (client_factory or TaskManagedAIClient)(
        ClientConfig(
            backend_url=str(args.backend_url or profile.backend_url),
            operation_token=operation_token,
        )
    )
    try:
        payload = client.request(request)
    except ApiClientError as exc:
        _emit(exc.payload, args=args, stdout=out)
        return 1 if exc.status_code < 500 else 2
    _emit(payload, args=args, stdout=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tm", description="TaskManagedAI project-user CLI")
    parser.add_argument("--version", action="version", version=f"tm {__version__}")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--project")
    parser.add_argument("--backend-url")
    parser.add_argument("--operation-token")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--yaml", action="store_true", dest="yaml_output")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--no-interactive", action="store_true")
    parser.add_argument("--agent-mode", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    register_commands(subparsers)
    return parser


def _build_request(args: argparse.Namespace) -> ApiRequest:
    builder = args.tm_builder
    request = builder(args)
    if not isinstance(request, ApiRequest):
        raise TypeError("command builder must return ApiRequest")
    return request


def _normalize_capability_flags(request: ApiRequest) -> ApiRequest:
    if request.capability in APPROVAL_REQUIRED_CAPABILITIES and not request.approval_required:
        return ApiRequest(
            method=request.method,
            path=request.path,
            capability=request.capability,
            params=request.params,
            json_body=request.json_body,
            mutating=True,
            approval_required=True,
            requires_project=request.requires_project,
        )
    if is_mutating_capability(request.capability) and not request.mutating:
        return ApiRequest(
            method=request.method,
            path=request.path,
            capability=request.capability,
            params=request.params,
            json_body=request.json_body,
            mutating=True,
            approval_required=request.approval_required,
            requires_project=request.requires_project,
        )
    return request


def _inject_operation_token(request: ApiRequest, operation_token: str | None) -> ApiRequest:
    if request.capability not in {"auth_cli_refresh", "auth_cli_revoke"}:
        return request
    if not operation_token:
        raise ValueError("operation token is required; pass --operation-token or TASKMANAGEDAI_OPERATION_TOKEN")
    body = dict(request.json_body or {})
    body["operation_token"] = operation_token
    return replace(request, json_body=body)


def _emit(payload: JSONValue, *, args: argparse.Namespace, stdout: TextIO) -> None:
    if bool(args.quiet):
        return
    if bool(args.json_output):
        print(format_json(payload), file=stdout)
        return
    if bool(args.yaml_output):
        print(format_yaml(payload), file=stdout)
        return
    print(format_human(payload), file=stdout)


def _emit_error(error_code: str, message: str, *, stderr: TextIO) -> None:
    print(f"{error_code}: {message}", file=stderr)


def _is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    return bool(isatty())
