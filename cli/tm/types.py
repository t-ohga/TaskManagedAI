from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]


type HttpMethod = Literal["GET", "POST", "PATCH", "DELETE"]


@dataclass(frozen=True)
class ApiRequest:
    method: HttpMethod
    path: str
    capability: str
    params: dict[str, str] | None = None
    json_body: JSONObject | None = None
    mutating: bool = False
    approval_required: bool = False
    requires_project: bool = True

    def with_project_id(self, project_id: str | None) -> ApiRequest:
        if not project_id:
            return self
        if "{project_id}" in self.path:
            return replace(self, path=self.path.replace("{project_id}", project_id))
        return self
