from __future__ import annotations

import argparse

from tm.types import ApiRequest, JSONObject


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("memory", help="Memory commands are disabled until SP-018")
    nested = parser.add_subparsers(dest="memory_command", required=True)

    record_parser = nested.add_parser("record", help="Disabled until SP-018")
    record_parser.add_argument("--text", required=True)
    record_parser.set_defaults(tm_builder=_record, tm_disabled=True)

    search_parser = nested.add_parser("search", help="Disabled until SP-018")
    search_parser.add_argument("query")
    search_parser.set_defaults(tm_builder=_search, tm_disabled=True)


def _record(args: argparse.Namespace) -> ApiRequest:
    body: JSONObject = {"text": args.text}
    return ApiRequest(
        method="POST",
        path="/api/v1/projects/{project_id}/memory/record",
        capability="memory_disabled",
        json_body=body,
        mutating=True,
    )


def _search(args: argparse.Namespace) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path="/api/v1/projects/{project_id}/memory/search",
        capability="memory_disabled",
        params={"query": str(args.query)},
    )
