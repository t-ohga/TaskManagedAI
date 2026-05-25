from __future__ import annotations

import argparse

from tm.commands.onboarding import add_dry_run_arguments, build_dry_run_request
from tm.types import ApiRequest, JSONObject


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("run", help="Inspect or control agent runs")
    nested = parser.add_subparsers(dest="run_command", required=True)

    show_parser = nested.add_parser("show", help="Show an agent run")
    show_parser.add_argument("run_id")
    show_parser.set_defaults(tm_builder=_show)

    cancel_parser = nested.add_parser("cancel", help="Cancel an agent run")
    cancel_parser.add_argument("run_id")
    cancel_parser.add_argument("--reason")
    cancel_parser.set_defaults(tm_builder=_cancel)

    plan_parser = nested.add_parser("plan", help="Create a response-only dry-run plan")
    plan_parser.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="Required; F4 never starts an AgentRun from this command",
    )
    add_dry_run_arguments(plan_parser)
    plan_parser.set_defaults(tm_builder=_plan)


def _show(args: argparse.Namespace) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=f"/api/v1/agent_runs/{args.run_id}",
        capability="run_show",
        requires_project=False,
    )


def _cancel(args: argparse.Namespace) -> ApiRequest:
    body: JSONObject = {}
    if args.reason is not None:
        body["reason"] = args.reason
    return ApiRequest(
        method="POST",
        path=f"/api/v1/agent_runs/{args.run_id}/cancel",
        capability="run_cancel",
        json_body=body,
        mutating=True,
        requires_project=False,
    )


def _plan(args: argparse.Namespace) -> ApiRequest:
    return build_dry_run_request(args)
