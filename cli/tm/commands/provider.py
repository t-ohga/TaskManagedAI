from __future__ import annotations

import argparse
import json

from tm.types import ApiRequest, JSONObject


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("provider", help="Request provider calls through policy gates")
    nested = parser.add_subparsers(dest="provider_command", required=True)

    call_parser = nested.add_parser("call", help="Request a provider call")
    call_parser.add_argument("--provider", required=True)
    call_parser.add_argument("--feature", required=True)
    call_parser.add_argument("--payload-json", default="{}")
    call_parser.set_defaults(tm_builder=_call)


def _call(args: argparse.Namespace) -> ApiRequest:
    payload = json.loads(str(args.payload_json))
    if not isinstance(payload, dict):
        raise ValueError("--payload-json must decode to an object")
    body: JSONObject = {
        "provider": args.provider,
        "feature": args.feature,
        "payload": payload,
    }
    return ApiRequest(
        method="POST",
        path="/api/v1/projects/{project_id}/providers/call",
        capability="provider_call",
        json_body=body,
        mutating=True,
        approval_required=True,
    )
