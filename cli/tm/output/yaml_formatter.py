from __future__ import annotations

from tm.output.redaction import redact_json
from tm.types import JSONValue


def format_yaml(value: JSONValue) -> str:
    return _format(redact_json(value), indent=0).rstrip()


def _format(value: JSONValue, *, indent: int) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, dict | list):
                lines.append(f"{prefix}{key}:")
                lines.append(_format(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{prefix}[]"
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}-")
                lines.append(_format(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}- {_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{_scalar(value)}"


def _scalar(value: JSONValue) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int | float):
        return str(value)
    return str(value)
