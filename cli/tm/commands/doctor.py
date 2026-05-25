from __future__ import annotations

import argparse

from tm.types import ApiRequest


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("doctor", help="Check backend reachability")
    parser.set_defaults(tm_builder=_doctor)


def _doctor(_args: argparse.Namespace) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path="/healthz",
        capability="doctor",
        requires_project=False,
    )
