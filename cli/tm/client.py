from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from tm.types import ApiRequest, JSONValue

OPERATION_TOKEN_HEADER = "X-TaskManagedAI-Operation-Token"  # noqa: S105 - header name, not a token value


class ApiClientError(RuntimeError):
    def __init__(self, status_code: int, payload: JSONValue) -> None:
        super().__init__(f"TaskManagedAI API returned {status_code}")
        self.status_code = status_code
        self.payload = payload


@dataclass(frozen=True)
class ClientConfig:
    backend_url: str
    operation_token: str | None
    timeout_seconds: float = 15.0


class ClientProtocol(Protocol):
    def request(self, request: ApiRequest) -> JSONValue:
        ...


class TaskManagedAIClient:
    def __init__(self, config: ClientConfig) -> None:
        self._config = config

    def request(self, request: ApiRequest) -> JSONValue:
        headers = {"Accept": "application/json"}
        if self._config.operation_token:
            headers[OPERATION_TOKEN_HEADER] = self._config.operation_token
        url = f"{self._config.backend_url}{request.path}"
        response = httpx.request(
            request.method,
            url,
            params=request.params,
            json=request.json_body,
            headers=headers,
            timeout=self._config.timeout_seconds,
        )
        payload = _response_payload(response)
        if response.status_code >= 400:
            raise ApiClientError(response.status_code, payload)
        return payload


def _response_payload(response: httpx.Response) -> JSONValue:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        parsed = response.json()
        if isinstance(parsed, str | int | float | bool) or parsed is None:
            return parsed
        if isinstance(parsed, list | dict):
            return parsed
    return {"status_code": response.status_code, "body": response.text}
