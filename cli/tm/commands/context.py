from __future__ import annotations

import argparse

from tm.types import ApiRequest


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("context", help="Inspect the resolved TaskManagedAI context")
    nested = parser.add_subparsers(dest="context_command", required=True)

    show_parser = nested.add_parser("show", help="Show the current project context")
    show_parser.set_defaults(tm_builder=_show)


def _show(_args: argparse.Namespace) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path="/api/v1/me/current_project",
        capability="context_show",
        requires_project=False,
    )
