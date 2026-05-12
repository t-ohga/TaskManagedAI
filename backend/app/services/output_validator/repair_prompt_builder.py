"""Sprint 5.5 BL-0068: repair retry context redaction.

Build a redacted retry-prompt input from the previous (failed) artifact and
the validation error. The retry input is the seed for the next provider call;
this builder enforces that NO raw secret / provider key / capability token
leaves the orchestrator boundary into the next prompt.

ADR-00006 (SecretBroker) §11 / `.claude/rules/secretbroker-boundary.md` §11 /
`.claude/rules/ai-output-boundary.md` §10:

- raw provider response / secret canary raw value / capability token 生値 を
  retry prompt に含めない
- ``assert_no_raw_secret`` を retry prompt builder で **必須実行**
- 違反は release blocker (Sprint Pack §残リスク)

The decision logic (whether to retry vs. terminal) lives in
``backend.app.services.output_validator.core.decide_repair`` (BL-0064). This
builder is a pure function: given the previous artifact's redacted summary
and the validation error's redacted summary, it returns an immutable
``RetryPromptInput``.

Immutability strategy (SP55-B3-F-001 + SP55-B3-R2-F-001 fixes):

1. ``RetryPromptInput.__post_init__`` takes ownership of the dicts by
   deep-copying them, so the caller's reference graph cannot mutate the
   stored summary after construction.
2. The stored dicts are then wrapped in ``types.MappingProxyType`` so the
   top-level mapping rejects ``__setitem__`` / ``__delitem__`` with
   ``TypeError`` — defending against ``result.previous_artifact_summary["k"]
   = ...`` style direct mutation of the returned object.
3. ``__post_init__`` re-runs ``assert_no_raw_secret`` on the owned graph so
   direct frozen-dataclass construction (bypassing the builder) still
   enforces the fail-closed invariant.
"""

from __future__ import annotations

import copy
import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from backend.app.repositories._payload_secret_scan import assert_no_raw_secret


@dataclass(frozen=True)
class RetryPromptInput:
    """Redacted seed for the next provider call after ``validation_failed``.

    The two mapping fields are wrapped in ``types.MappingProxyType`` so the
    top-level dictionary cannot be mutated after construction. The underlying
    dict is a deep copy of the caller's input, so external mutations to the
    caller's reference graph cannot tamper with the retry prompt either.

    For JSON serialization, call ``as_dict()`` to obtain a fresh dict copy.
    """

    previous_artifact_summary: Mapping[str, Any] = field(default_factory=dict)
    validation_error_summary: Mapping[str, Any] = field(default_factory=dict)
    retry_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.retry_count, int) or isinstance(self.retry_count, bool):
            raise ValueError("retry_count must be int")
        if self.retry_count < 0:
            raise ValueError("retry_count must be zero or greater.")
        if not isinstance(self.previous_artifact_summary, Mapping):
            raise ValueError("previous_artifact_summary must be a mapping")
        if not isinstance(self.validation_error_summary, Mapping):
            raise ValueError("validation_error_summary must be a mapping")

        # Take ownership of the input graph via deep copy + raw-secret scan so
        # that:
        #   - the caller's reference graph cannot mutate the stored summary
        #     post-construction (SP55-B3-F-001)
        #   - the returned object's top-level mapping rejects __setitem__
        #     via MappingProxyType (SP55-B3-R2-F-001)
        #   - direct frozen-dataclass construction cannot bypass the
        #     raw-secret scan (SP55-B3-F-001 __post_init__ defense)
        owned_previous = copy.deepcopy(dict(self.previous_artifact_summary))
        owned_validation = copy.deepcopy(dict(self.validation_error_summary))

        assert_no_raw_secret(
            owned_previous,
            path="$retry_prompt.previous_artifact_summary",
        )
        assert_no_raw_secret(
            owned_validation,
            path="$retry_prompt.validation_error_summary",
        )

        # ``object.__setattr__`` is the standard escape hatch for setting
        # fields on a frozen dataclass during ``__post_init__``.
        object.__setattr__(
            self,
            "previous_artifact_summary",
            types.MappingProxyType(owned_previous),
        )
        object.__setattr__(
            self,
            "validation_error_summary",
            types.MappingProxyType(owned_validation),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable plain dict copy of the retry prompt input.

        The copy is fresh on every call so the caller cannot mutate the
        retained internal state.
        """

        return {
            "previous_artifact_summary": copy.deepcopy(
                dict(self.previous_artifact_summary)
            ),
            "validation_error_summary": copy.deepcopy(
                dict(self.validation_error_summary)
            ),
            "retry_count": self.retry_count,
        }


def build_retry_prompt_input(
    *,
    previous_artifact_content: Mapping[str, Any],
    validation_error: Mapping[str, Any],
    retry_count: int,
) -> RetryPromptInput:
    """Build a fail-closed retry input.

    Raises
    ------
    ValueError
        - ``retry_count`` is negative
        - ``previous_artifact_content`` or ``validation_error`` contains a
          prohibited key or a raw secret value pattern. The scan is
          recursive and uses the shared 21-prohibited-key set +
          8-regex-pattern table from ``_payload_secret_scan.py``.

    The construction delegates immutability and the raw-secret scan to
    ``RetryPromptInput.__post_init__`` so the two code paths (builder /
    direct construction) cannot drift.
    """

    if retry_count < 0:
        raise ValueError("retry_count must be zero or greater.")

    # First-pass fail-closed scan on the caller-supplied references so the
    # builder rejects hostile input *before* allocating the deep copy.
    # The __post_init__ re-scan covers direct construction.
    assert_no_raw_secret(
        previous_artifact_content,
        path="$retry_prompt.previous_artifact_content",
    )
    assert_no_raw_secret(
        validation_error,
        path="$retry_prompt.validation_error",
    )

    return RetryPromptInput(
        previous_artifact_summary=previous_artifact_content,
        validation_error_summary=validation_error,
        retry_count=retry_count,
    )


__all__ = ["RetryPromptInput", "build_retry_prompt_input"]
