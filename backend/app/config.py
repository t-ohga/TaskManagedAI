from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]

_PLACEHOLDER_SENTINEL = "REPLACE_ME"
_DEV_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@postgres:5432/taskmanagedai"
)
_DEV_REDIS_URL = "redis://redis:6379/0"
_BLOCKED_DATABASE_URL_FRAGMENTS = ("taskmanagedai:taskmanagedai@",)


def _dev_database_url() -> str:
    return _DEV_DATABASE_URL


def _dev_redis_url() -> str:
    return _DEV_REDIS_URL


def _reject_production_placeholder(setting_name: str, value: str) -> None:
    if _PLACEHOLDER_SENTINEL in value:
        raise ValueError(f"{setting_name} must not contain placeholder values in production.")


def _reject_production_url(
    setting_name: str,
    value: str,
    *,
    default_value: str | None = None,
    blocked_fragments: tuple[str, ...] = (),
) -> None:
    _reject_production_placeholder(setting_name, value)
    if default_value is not None and value == default_value:
        raise ValueError(f"{setting_name} must not use the development default in production.")
    if any(fragment in value for fragment in blocked_fragments):
        raise ValueError(f"{setting_name} must not use known weak credentials in production.")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TASKMANAGEDAI_",
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = "development"
    app_name: str = "TaskManagedAI"
    app_version: str = "0.1.0"

    database_url: str = Field(default_factory=_dev_database_url)
    redis_url: str = Field(default_factory=_dev_redis_url)
    dev_login_cookie_secret: str = Field(default=_PLACEHOLDER_SENTINEL, min_length=8)

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    tz: str = "Asia/Tokyo"

    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "localhost", "api", "testserver"]
    )
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:3000", "http://localhost:3000"]
    )

    request_id_header: str = "x-request-id"
    default_tenant_id: int = Field(default=1, ge=1)
    default_actor_id: str = "human:default"
    default_principal_id: str = "session"

    arq_queue_name: str = "taskmanagedai:jobs"
    worker_cancel_channel: str = "taskmanagedai:cancel"

    # SP-012 §9.10 R10 F-001: active-registry gate (L1+L2+L3 defense-in-depth).
    # production deployment 時に enabled=True にする (`TASKMANAGEDAI_ACTIVE_REGISTRY_GATE_ENABLED=true`).
    # test / development default は disabled (既存 fixture / contract test を維持)、
    # production startup で config_dir / host_id が解決できなければ fail-closed startup abort。
    active_registry_gate_enabled: bool = False
    taskhub_config_dir: str = "/etc/taskhub"
    taskhub_host_id: str = ""

    @model_validator(mode="after")
    def validate_local_boundary(self) -> Self:
        if self.environment == "production":
            self._validate_production_runtime_settings()
        if self.api_host != "127.0.0.1":
            raise ValueError("TASKMANAGEDAI_API_HOST must stay on the local loopback boundary.")
        return self

    def _validate_production_runtime_settings(self) -> None:
        if _PLACEHOLDER_SENTINEL in self.dev_login_cookie_secret:
            raise ValueError(
                "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET must not contain "
                "placeholder values in production."
            )

        _reject_production_url(
            "TASKMANAGEDAI_DATABASE_URL",
            self.database_url,
            default_value=_DEV_DATABASE_URL,
            blocked_fragments=_BLOCKED_DATABASE_URL_FRAGMENTS,
        )
        _reject_production_url(
            "TASKMANAGEDAI_REDIS_URL",
            self.redis_url,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

