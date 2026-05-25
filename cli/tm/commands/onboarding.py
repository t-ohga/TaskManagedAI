from __future__ import annotations

import argparse

from tm.types import ApiRequest, JSONObject

_ACTION_CLASSES = ("read_only", "task_write", "repo_write", "pr_open")
_STARTER_MODES = ("research_only", "plan_only", "draft_pr_requires_approval")


def add_dry_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--purpose", required=True)
    parser.add_argument("--expected-artifact", required=True)
    parser.add_argument("--allowed-action-class", choices=_ACTION_CLASSES, default="read_only")
    parser.add_argument("--starter-mode", choices=_STARTER_MODES, default="plan_only")
    parser.add_argument("--target-repo-ref")
    parser.add_argument("--budget-cap")


def build_dry_run_request(args: argparse.Namespace) -> ApiRequest:
    body: JSONObject = {
        "purpose": args.purpose,
        "expected_artifact": args.expected_artifact,
        "allowed_action_class": args.allowed_action_class,
        "starter_mode": args.starter_mode,
    }
    if args.target_repo_ref is not None:
        body["target_repo_ref"] = args.target_repo_ref
    if args.budget_cap is not None:
        body["budget_cap"] = args.budget_cap
    return ApiRequest(
        method="POST",
        path="/api/v1/onboarding/dry_run_plan",
        capability="onboarding_dry_run",
        json_body=body,
    )
