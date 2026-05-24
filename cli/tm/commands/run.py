from __future__ import annotations

import argparse

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
