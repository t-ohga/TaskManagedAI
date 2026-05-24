from __future__ import annotations

import argparse

from tm.types import ApiRequest, JSONObject

_MEMORY_RECORD_KINDS = (
    "manual_user",
    "manual_agent",
    "auto_completion",
    "auto_failure",
    "auto_review_finding",
)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("memory", help="Memory read-only commands")
    nested = parser.add_subparsers(dest="memory_command", required=True)

    record_parser = nested.add_parser("record", help="Disabled until SP-018")
    record_parser.add_argument("--text", required=True)
    record_parser.set_defaults(tm_builder=_record, tm_disabled=True)

    search_parser = nested.add_parser("search", help="Disabled until SP-018")
    search_parser.add_argument("query")
    search_parser.set_defaults(tm_builder=_search, tm_disabled=True)

    insights_parser = nested.add_parser("insights", help="List ref-only memory insights")
    insights_parser.add_argument("--record-kind", choices=_MEMORY_RECORD_KINDS)
    insights_parser.add_argument("--limit", type=int, default=20)
    insights_parser.set_defaults(tm_builder=_insights)


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


def _insights(args: argparse.Namespace) -> ApiRequest:
    params = {"limit": str(args.limit)}
    if args.record_kind:
        params["record_kind"] = str(args.record_kind)
    return ApiRequest(
        method="GET",
        path="/api/v1/projects/{project_id}/memory/insights",
        capability="memory_insights",
        params=params,
    )
