from __future__ import annotations

from tm.output.redaction import redact_json
from tm.types import JSONValue


def format_human(value: JSONValue) -> str:
    redacted = redact_json(value)
    if isinstance(redacted, dict):
        return _dict_to_lines(redacted)
    if isinstance(redacted, list):
        return "\n".join(_line_for_item(item) for item in redacted)
    return str(redacted)


def _dict_to_lines(value: dict[str, JSONValue]) -> str:
    return "\n".join(f"{key}: {_line_for_item(item)}" for key, item in value.items())


def _line_for_item(value: JSONValue) -> str:
    if isinstance(value, dict):
        stable = ", ".join(f"{key}={_line_for_item(item)}" for key, item in value.items())
        return "{" + stable + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_line_for_item(item) for item in value) + "]"
    if value is None:
        return "null"
    return str(value)
