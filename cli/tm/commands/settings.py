from __future__ import annotations

import argparse

from tm.types import ApiRequest, JSONObject

_AUTONOMY_LEVELS = ("L0", "L1", "L2", "L3")


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("settings", help="Manage project settings")
    nested = parser.add_subparsers(dest="settings_command", required=True)

    autonomy_parser = nested.add_parser("autonomy", help="Set project autonomy level")
    autonomy_parser.add_argument("--level", choices=_AUTONOMY_LEVELS, required=True)
    # Codex adversarial R7/R8 (HIGH): AI 権限制御の compare-and-swap baseline (必須)。
    # 編集の基にした現在の autonomy_level を宣言する。backend が DB current と比較し、
    # 不一致なら 409 で拒否する (stale な値での re-escalation を防ぐ)。
    autonomy_parser.add_argument(
        "--expected-level",
        choices=_AUTONOMY_LEVELS,
        required=True,
        help="Current autonomy level the change is based on (compare-and-swap baseline)",
    )
    autonomy_parser.set_defaults(tm_builder=_autonomy)


def _autonomy(args: argparse.Namespace) -> ApiRequest:
    body: JSONObject = {
        "autonomy_level": str(args.level),
        "expected_autonomy_level": str(args.expected_level),
    }
    return ApiRequest(
        method="PATCH",
        path="/api/v1/me/projects/{project_id}/autonomy",
        capability="task_write",
        json_body=body,
        mutating=True,
    )
