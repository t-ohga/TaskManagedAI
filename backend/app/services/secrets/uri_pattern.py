"""secret_ref URI grammar の単一 source of truth (ADR-00058)。

正本 grammar: ``secret://<backend>/<scope>/<name>#v<n>``

- ``backend`` ∈ {``sops``, ``local``} (Phase 0 で ``local`` を additive 追加、scheme ``secret://`` 不変)
- ``scope``   ∈ {``p0``, ``workspace``, ``project``, ``repo``, ``agent_run``, ``provider``}
- ``name``    = ``[a-z0-9_-]+``
- ``version`` = ``v[0-9]+`` (``v`` prefix を含む。``version`` column は ``v1`` を保存)

``SECRET_URI_PATTERN`` は **canonical pattern 文字列**で、次の 2 経路の唯一の source of truth:

- Python ``re`` (``re.fullmatch`` / ``re.compile``)
- PostgreSQL POSIX ``~`` 演算子 (ORM ``CheckConstraint``)

そのため pattern には **Python 専用構文 (named group ``(?P<...>)`` 等) を入れない** (POSIX ERE 非互換)。
parse は「validate 後に文字列分割」で行い、第 2 の regex を持たず drift をゼロ化する。

**5+source 整合 (cross-source-enum-integrity §1)**: ORM ``CheckConstraint`` / resolver dispatch /
registration validation / test ``EXPECTED`` が本定数を import する。**Alembic migration は本定数を
import しない** (revision 固定 literal を hardcode = migration 不変性、ADR-00058 境界批評 R4)。
drift guard test が「最新 migration の固定 literal == current ``SECRET_URI_PATTERN``」を CI 強制する。

未知 backend / scope / 形式は fail-closed (``ValueError``)。
"""

from __future__ import annotations

import re
from typing import Final

SECRET_BACKENDS: Final[tuple[str, ...]] = ("sops", "local")
SECRET_SCOPES: Final[tuple[str, ...]] = (
    "p0",
    "workspace",
    "project",
    "repo",
    "agent_run",
    "provider",
)

# canonical pattern 文字列 (POSIX ERE ∩ Python re の共通 subset、anchored)。
# DB CHECK (POSIX ``~``) と Python ``re`` の両方で同一文字列を使う唯一の source of truth。
# S105 は regex 文字列を hardcoded password と誤検出する false positive (secret 値ではない)。
SECRET_URI_PATTERN: Final[str] = r"^secret://(sops|local)/(p0|workspace|project|repo|agent_run|provider)/[a-z0-9_-]+#v[0-9]+$"  # noqa: S105, E501

_SECRET_URI_RE: Final[re.Pattern[str]] = re.compile(SECRET_URI_PATTERN)
_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9_-]+$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^v[0-9]+$")

_SCHEME_PREFIX: Final[str] = "secret://"


class SecretUriError(ValueError):
    """secret_ref URI が canonical grammar に一致しない (fail-closed)。"""


def is_valid_secret_uri(uri: str) -> bool:
    """``uri`` が canonical grammar に一致するか (boolean、例外なし)。"""
    return _SECRET_URI_RE.fullmatch(uri) is not None


def parse_secret_uri(uri: str) -> tuple[str, str, str, str]:
    """``(backend, scope, name, version)`` を返す。不一致は ``SecretUriError`` (fail-closed)。

    第 2 の regex を持たず、validate 後に文字列分割で抽出する (named group は POSIX 非互換のため
    ``SECRET_URI_PATTERN`` に含められず、別 regex を持つと drift する)。
    """
    if not is_valid_secret_uri(uri):
        raise SecretUriError(
            "secret_ref URI rejected: expected "
            "secret://<sops|local>/<scope>/<name>#v<n>"
        )
    rest = uri[len(_SCHEME_PREFIX) :]
    backend, scope, name_version = rest.split("/", 2)
    name, _, version = name_version.partition("#")
    return backend, scope, name, version


def build_secret_uri(backend: str, scope: str, name: str, version: str) -> str:
    """canonical URI を server 側で組み立てる。各 component を fail-closed 検証する。

    caller が任意の URI 文字列を渡すのではなく、構造化 component から server が組み立てることで
    URI と (scope, name, version) column の drift を構造的に防ぐ (components_match CHECK と整合)。
    """
    if backend not in SECRET_BACKENDS:
        raise SecretUriError(f"unknown secret backend: {backend!r}")
    if scope not in SECRET_SCOPES:
        raise SecretUriError(f"unknown secret scope: {scope!r}")
    if _NAME_RE.fullmatch(name) is None:
        raise SecretUriError(f"invalid secret name: {name!r}")
    if _VERSION_RE.fullmatch(version) is None:
        raise SecretUriError(f"invalid secret version: {version!r} (expected v<n>)")
    uri = f"{_SCHEME_PREFIX}{backend}/{scope}/{name}#{version}"
    # 防御的 round-trip: 組み立て結果が canonical pattern に必ず一致すること。
    if not is_valid_secret_uri(uri):  # pragma: no cover - defensive
        raise SecretUriError(f"constructed URI failed validation: {uri!r}")
    return uri


def secret_uri_backend(uri: str) -> str:
    """URI の backend segment を返す (resolver dispatch 用)。未知形式は fail-closed。"""
    backend, _, _, _ = parse_secret_uri(uri)
    return backend


__all__ = [
    "SECRET_BACKENDS",
    "SECRET_SCOPES",
    "SECRET_URI_PATTERN",
    "SecretUriError",
    "build_secret_uri",
    "is_valid_secret_uri",
    "parse_secret_uri",
    "secret_uri_backend",
]
