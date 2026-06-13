from __future__ import annotations

from decimal import Decimal
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
        default_factory=lambda: ["http://127.0.0.1:3900", "http://localhost:3900"]
    )

    request_id_header: str = "x-request-id"
    default_tenant_id: int = Field(default=1, ge=1)
    default_actor_id: str = "human:default"
    default_principal_id: str = "session"

    active_registry_gate_enabled: bool = False
    taskhub_host_id: str = ""
    taskhub_config_dir: str = "/etc/taskhub"
    memory_api_enabled: bool = False

    # SP-029 shadow mode (ADR-00055). shadow run の feature toggle (default off、operator opt-in)
    # と per-run hard cap。safety は (1) production budget 非加算 (2) per-run cap で担保するため、
    # flag は「機能の有効/無効」であり安全 gate ではない。cap は 1 shadow run あたりの累計 cost 上限。
    shadow_mode_enabled: bool = False
    shadow_run_max_cost_usd: Decimal = Field(default=Decimal("1.00"), gt=0)
    # USD 非依存の shadow per-run bound (Codex SP-029 R6 F-1)。provider が cost_usd=0 /
    # 未報告でも shadow run の provider spend を token 累計で必ず上限化する (production の
    # BudgetGuard hard_tokens_limit を skip するため、shadow 専用に必須)。
    shadow_run_max_total_tokens: int = Field(default=2_000_000, gt=0)
    # shadow の **pre-execution USD projection** 用の保守的 worst-case 単価 ($/token、Codex R11 F-1)。
    # per-model pricing table が無いため、(estimated_input + max_tokens) * 本単価で 1 call の USD を
    # over-estimate し、`current_usd + projected > shadow_run_max_cost_usd` を provider 課金前に block
    # する。fail-safe (過大見積) 方向の単一 ceiling。default は premium output 級 (~$20/1M tokens)。
    shadow_run_max_usd_per_token: Decimal = Field(default=Decimal("0.00002"), gt=0)

    arq_queue_name: str = "taskmanagedai:jobs"
    worker_cancel_channel: str = "taskmanagedai:cancel"

    # ADR-00038 (L-3 SSE realtime). AgentRun 進捗 SSE stream の運用パラメータ。
    agentrun_sse_enabled: bool = True
    # 専用 LISTEN connection pool 上限 (= 同時 SSE stream 上限)。main transactional
    # pool の余力と独立に上げてはならない (R7/R8): 同時 stream の per-query checkout が
    # main pool を枯渇させないよう、main pool_size+max_overflow より十分小さく保つ。
    agentrun_sse_listen_pool_max: int = Field(default=10, ge=1, le=100)
    # stream 由来 main DB query (tail/status) の同時実行上限 (R7)。通常 API 用の
    # main pool 余力を常に残すため stream 群の同時 checkout を bound する。
    agentrun_sse_query_concurrency: int = Field(default=4, ge=1, le=64)
    # heartbeat 間隔 + jitter (R7): 全 stream の同時 wake を散らし main pool burst を防ぐ。
    agentrun_sse_heartbeat_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    agentrun_sse_heartbeat_jitter_seconds: float = Field(default=3.0, ge=0.0, le=30.0)
    # 1 stream の最大生存時間。超過で server から close、client は ?last_event_id= で再接続。
    agentrun_sse_max_lifetime_seconds: float = Field(default=1800.0, ge=30.0, le=86400.0)

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

