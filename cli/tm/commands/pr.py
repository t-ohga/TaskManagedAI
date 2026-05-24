from __future__ import annotations

import argparse

from tm.types import ApiRequest, JSONObject


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("pr", help="Manage pull requests")
    nested = parser.add_subparsers(dest="pr_command", required=True)

    open_parser = nested.add_parser("open", help="Open a pull request")
    open_parser.add_argument("--base", required=True)
    open_parser.add_argument("--head", required=True)
    open_parser.add_argument("--title", required=True)
    open_parser.add_argument("--draft", action="store_true")
    open_parser.set_defaults(tm_builder=_open)


def _open(args: argparse.Namespace) -> ApiRequest:
    body: JSONObject = {
        "base": args.base,
        "head": args.head,
        "title": args.title,
        "draft": bool(args.draft),
    }
    return ApiRequest(
        method="POST",
        path="/api/v1/projects/{project_id}/pull-requests",
        capability="pr_open",
        json_body=body,
        mutating=True,
    )
