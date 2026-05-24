from __future__ import annotations

import argparse

from tm.types import ApiRequest, JSONObject


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("secret", help="Resolve brokered secret references")
    nested = parser.add_subparsers(dest="secret_command", required=True)

    use_parser = nested.add_parser("use", help="Request brokered secret resolution")
    use_parser.add_argument("secret_ref")
    use_parser.add_argument("--purpose", required=True)
    use_parser.set_defaults(tm_builder=_use)


def _use(args: argparse.Namespace) -> ApiRequest:
    body: JSONObject = {"secret_ref": args.secret_ref, "purpose": args.purpose}
    return ApiRequest(
        method="POST",
        path="/api/v1/projects/{project_id}/secrets/resolve",
        capability="secret_resolve",
        json_body=body,
        mutating=True,
        approval_required=True,
    )
