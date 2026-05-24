from __future__ import annotations

import argparse

from tm.types import ApiRequest, JSONObject


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("ticket", help="Manage project tickets")
    nested = parser.add_subparsers(dest="ticket_command", required=True)

    list_parser = nested.add_parser("list", help="List tickets")
    list_parser.add_argument("--limit", default="50")
    list_parser.add_argument("--offset", default="0")
    list_parser.set_defaults(tm_builder=_list)

    show_parser = nested.add_parser("show", help="Show a ticket")
    show_parser.add_argument("ticket_id")
    show_parser.set_defaults(tm_builder=_show)

    create_parser = nested.add_parser("create", help="Create a ticket")
    create_parser.add_argument("--slug", required=True)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--description")
    create_parser.add_argument("--priority")
    create_parser.set_defaults(tm_builder=_create)

    update_parser = nested.add_parser("update", help="Update a ticket")
    update_parser.add_argument("ticket_id")
    update_parser.add_argument("--title")
    update_parser.add_argument("--description")
    update_parser.add_argument("--status")
    update_parser.add_argument("--priority")
    update_parser.set_defaults(tm_builder=_update)


def _list(args: argparse.Namespace) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path="/api/v1/projects/{project_id}/tickets",
        capability="task_list",
        params={"limit": str(args.limit), "offset": str(args.offset)},
    )


def _show(args: argparse.Namespace) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=f"/api/v1/projects/{{project_id}}/tickets/{args.ticket_id}",
        capability="task_show",
    )


def _create(args: argparse.Namespace) -> ApiRequest:
    body: JSONObject = {"slug": args.slug, "title": args.title}
    if args.description is not None:
        body["description"] = args.description
    if args.priority is not None:
        body["priority"] = args.priority
    return ApiRequest(
        method="POST",
        path="/api/v1/projects/{project_id}/tickets",
        capability="task_create",
        json_body=body,
        mutating=True,
    )


def _update(args: argparse.Namespace) -> ApiRequest:
    body: JSONObject = {}
    for field in ("title", "description", "status", "priority"):
        value = getattr(args, field)
        if value is not None:
            body[field] = value
    return ApiRequest(
        method="PATCH",
        path=f"/api/v1/projects/{{project_id}}/tickets/{args.ticket_id}",
        capability="task_write",
        json_body=body,
        mutating=True,
    )
