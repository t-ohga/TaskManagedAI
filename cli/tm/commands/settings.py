from __future__ import annotations

import argparse

from tm.types import ApiRequest, JSONObject

_AUTONOMY_LEVELS = ("L0", "L1", "L2", "L3")


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("settings", help="Manage project settings")
    nested = parser.add_subparsers(dest="settings_command", required=True)

    autonomy_parser = nested.add_parser("autonomy", help="Set project autonomy level")
    autonomy_parser.add_argument("--level", choices=_AUTONOMY_LEVELS, required=True)
    autonomy_parser.set_defaults(tm_builder=_autonomy)


def _autonomy(args: argparse.Namespace) -> ApiRequest:
    body: JSONObject = {"autonomy_level": str(args.level)}
    return ApiRequest(
        method="PATCH",
        path="/api/v1/me/projects/{project_id}/autonomy",
        capability="task_write",
        json_body=body,
        mutating=True,
    )
