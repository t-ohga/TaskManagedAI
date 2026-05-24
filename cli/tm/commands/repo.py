from __future__ import annotations

import argparse

from tm.types import ApiRequest, JSONObject


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("repo", help="Inspect or mutate repository state")
    nested = parser.add_subparsers(dest="repo_command", required=True)

    status_parser = nested.add_parser("status", help="Show repository status")
    status_parser.add_argument("--repo-id")
    status_parser.set_defaults(tm_builder=_status)

    push_parser = nested.add_parser("push", help="Request a repository push")
    push_parser.add_argument("--repo-id")
    push_parser.add_argument("--branch", required=True)
    push_parser.add_argument("--remote", default="origin")
    push_parser.set_defaults(tm_builder=_push)


def _status(args: argparse.Namespace) -> ApiRequest:
    params = {"repo_id": str(args.repo_id)} if args.repo_id else None
    return ApiRequest(
        method="GET",
        path="/api/v1/projects/{project_id}/repo/status",
        capability="repo_status",
        params=params,
    )


def _push(args: argparse.Namespace) -> ApiRequest:
    body: JSONObject = {"branch": args.branch, "remote": args.remote}
    if args.repo_id:
        body["repo_id"] = args.repo_id
    return ApiRequest(
        method="POST",
        path="/api/v1/projects/{project_id}/repo/push",
        capability="repo_push",
        json_body=body,
        mutating=True,
    )
