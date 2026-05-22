"""Review artifact contract for SP-014 batch 0b.

Agent-level review artifacts are separate from human approval decisions:
review verdicts use pass/fail/needs_revision, and the allowed action_class
subset is limited to the action classes that can be policy-reviewed before a
human approval boundary is involved.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

from backend.app.domain.policy.action_class import ALL_ACTION_CLASSES

ReviewArtifactActionClass = Literal[
    "task_write",
    "repo_write",
    "pr_open",
    "secret_access",
]

REVIEW_ARTIFACT_ACTION_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "task_write",
        "repo_write",
        "pr_open",
        "secret_access",
    }
)

ReviewArtifactVerdict = Literal["pass", "fail", "needs_revision"]

REVIEW_ARTIFACT_VERDICTS: Final[frozenset[str]] = frozenset(
    {"pass", "fail", "needs_revision"}
)

_ACTION_LITERAL_ARGS: Final[frozenset[str]] = frozenset(
    get_args(ReviewArtifactActionClass)
)
if _ACTION_LITERAL_ARGS != REVIEW_ARTIFACT_ACTION_CLASSES:
    raise AssertionError(
        "ReviewArtifactActionClass Literal and REVIEW_ARTIFACT_ACTION_CLASSES drift: "
        f"Literal={sorted(_ACTION_LITERAL_ARGS)}, "
        f"frozenset={sorted(REVIEW_ARTIFACT_ACTION_CLASSES)}"
    )

_VERDICT_LITERAL_ARGS: Final[frozenset[str]] = frozenset(get_args(ReviewArtifactVerdict))
if _VERDICT_LITERAL_ARGS != REVIEW_ARTIFACT_VERDICTS:
    raise AssertionError(
        "ReviewArtifactVerdict Literal and REVIEW_ARTIFACT_VERDICTS drift: "
        f"Literal={sorted(_VERDICT_LITERAL_ARGS)}, "
        f"frozenset={sorted(REVIEW_ARTIFACT_VERDICTS)}"
    )

if not REVIEW_ARTIFACT_ACTION_CLASSES.issubset(ALL_ACTION_CLASSES):
    raise AssertionError(
        "review_artifacts action classes must remain a subset of ADR-00009 "
        f"ActionClass values: {sorted(REVIEW_ARTIFACT_ACTION_CLASSES)}"
    )


__all__ = [
    "REVIEW_ARTIFACT_ACTION_CLASSES",
    "REVIEW_ARTIFACT_VERDICTS",
    "ReviewArtifactActionClass",
    "ReviewArtifactVerdict",
]
