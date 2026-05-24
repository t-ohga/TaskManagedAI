from __future__ import annotations

import json

from tm.output.redaction import redact_json
from tm.types import JSONValue


def format_json(value: JSONValue) -> str:
    return json.dumps(redact_json(value), ensure_ascii=False, sort_keys=True, indent=2)
