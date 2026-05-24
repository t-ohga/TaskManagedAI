from __future__ import annotations

import argparse

from tm.types import ApiRequest, JSONObject


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("approval", help="Review approval requests")
    nested = parser.add_subparsers(dest="approval_command", required=True)

    list_parser = nested.add_parser("list", help="List approvals")
    list_parser.add_argument("--status", default="pending")
    list_parser.set_defaults(tm_builder=_list)

    approve_parser = nested.add_parser("approve", help="Approve a request")
    approve_parser.add_argument("approval_id")
    approve_parser.add_argument("--rationale")
    approve_parser.set_defaults(tm_builder=_approve)

    reject_parser = nested.add_parser("reject", help="Reject a request")
    reject_parser.add_argument("approval_id")
    reject_parser.add_argument("--rationale")
    reject_parser.set_defaults(tm_builder=_reject)


def _list(args: argparse.Namespace) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path="/api/v1/approvals",
        capability="approval_list",
        params={"status": str(args.status)},
        requires_project=False,
    )


def _approve(args: argparse.Namespace) -> ApiRequest:
    return _decide(args, action="approve")


def _reject(args: argparse.Namespace) -> ApiRequest:
    return _decide(args, action="reject")


def _decide(args: argparse.Namespace, *, action: str) -> ApiRequest:
    body: JSONObject = {"action": action}
    if args.rationale is not None:
        body["rationale"] = args.rationale
    return ApiRequest(
        method="POST",
        path=f"/api/v1/approvals/{args.approval_id}/decide",
        capability="approval_decide",
        json_body=body,
        mutating=True,
        approval_required=True,
        requires_project=False,
    )
