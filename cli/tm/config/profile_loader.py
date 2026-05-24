from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tm.auth.capability_token import CapabilityTokenConfigError, assert_profile_has_no_raw_token

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"


class ProfileConfigError(ValueError):
    """Raised when CLI profile config is malformed or unsafe."""


@dataclass(frozen=True)
class CliProfile:
    name: str
    backend_url: str
    default_project_id: str | None
    auth_method: str
    refresh_credential_ref: str | None
    projects_by_remote: dict[str, str]


@dataclass(frozen=True)
class ProjectResolution:
    project_id: str | None
    source: str
    ambiguous_candidates: tuple[str, ...] = ()


class ProfileLoader:
    def __init__(self, *, home: Path | None = None, profile_path: Path | None = None) -> None:
        self._home = home or Path.home()
        self._profile_path = profile_path

    def load(self, profile_name: str, env: Mapping[str, str]) -> CliProfile:
        data = self._load_file(env)
        profiles = data.get("profiles")
        if profiles is not None and not isinstance(profiles, dict):
            raise ProfileConfigError("profiles must be an object")
        selected = self._select_profile_data(profile_name, profiles)
        try:
            assert_profile_has_no_raw_token(selected)
        except CapabilityTokenConfigError as exc:
            raise ProfileConfigError(str(exc)) from exc

        backend_url = str(
            env.get("TASKMANAGEDAI_BACKEND_URL")
            or selected.get("backend_url")
            or data.get("backend_url")
            or DEFAULT_BACKEND_URL
        ).rstrip("/")
        default_project_id = _string_or_none(
            env.get("TASKMANAGEDAI_PROJECT_ID")
            or selected.get("default_project_id")
            or data.get("default_project_id")
        )
        auth_method = str(selected.get("auth_method") or data.get("auth_method") or "env")
        refresh_credential_ref = _string_or_none(
            selected.get("refresh_credential_ref")
            or selected.get("refresh_credential_env")
            or data.get("refresh_credential_ref")
            or data.get("refresh_credential_env")
        )
        projects_by_remote = _string_dict(selected.get("projects_by_remote") or data.get("projects_by_remote"))
        return CliProfile(
            name=profile_name,
            backend_url=backend_url,
            default_project_id=default_project_id,
            auth_method=auth_method,
            refresh_credential_ref=refresh_credential_ref,
            projects_by_remote=projects_by_remote,
        )

    def resolve_project(
        self,
        *,
        explicit_project_id: str | None,
        env: Mapping[str, str],
        profile: CliProfile,
        cwd: Path,
    ) -> ProjectResolution:
        if explicit_project_id:
            return ProjectResolution(project_id=explicit_project_id, source="explicit_arg")
        env_project_id = env.get("TASKMANAGEDAI_PROJECT_ID")
        if env_project_id:
            return ProjectResolution(project_id=env_project_id, source="env")
        remote_project = _project_from_git_remote(profile.projects_by_remote, cwd)
        if remote_project.ambiguous_candidates or remote_project.project_id:
            return remote_project
        if profile.default_project_id:
            return ProjectResolution(project_id=profile.default_project_id, source="profile")
        return ProjectResolution(project_id=None, source="unresolved")

    def _load_file(self, env: Mapping[str, str]) -> dict[str, Any]:
        path = self._profile_path
        if path is None:
            path_value = env.get("TASKMANAGEDAI_PROFILE_PATH")
            if path_value:
                path = Path(path_value)
            else:
                path = self._home / ".taskmanagedai" / "profile.yaml"
        if not path.exists():
            return {}
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProfileConfigError(f"profile not readable: {path}") from exc
        parsed = _parse_profile_content(content, path)
        try:
            assert_profile_has_no_raw_token(parsed)
        except CapabilityTokenConfigError as exc:
            raise ProfileConfigError(str(exc)) from exc
        return parsed

    @staticmethod
    def _select_profile_data(profile_name: str, profiles: object) -> dict[str, Any]:
        if profiles is None:
            return {}
        if not isinstance(profiles, dict):
            raise ProfileConfigError("profiles must be an object")
        selected = profiles.get(profile_name)
        if selected is None:
            return {}
        if not isinstance(selected, dict):
            raise ProfileConfigError(f"profile {profile_name!r} must be an object")
        return dict(selected)


def _parse_profile_content(content: str, path: Path) -> dict[str, Any]:
    stripped = content.strip()
    if not stripped:
        return {}
    if path.suffix == ".json" or stripped.startswith("{"):
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            raise ProfileConfigError("profile JSON must be an object")
        return parsed
    return _parse_simple_yaml(stripped.splitlines())


def _parse_simple_yaml(lines: Sequence[str]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if ":" not in raw_line:
            raise ProfileConfigError("profile YAML supports mapping keys only")
        key, _, value = raw_line.strip().partition(":")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value.strip():
            parent[key] = _coerce_scalar(value.strip())
            continue
        child: dict[str, Any] = {}
        parent[key] = child
        stack.append((indent, child))
    return root


def _coerce_scalar(value: str) -> str | bool | None:
    unquoted = value.strip().strip('"').strip("'")
    if unquoted == "null":
        return None
    if unquoted == "true":
        return True
    if unquoted == "false":
        return False
    return unquoted


def _project_from_git_remote(projects_by_remote: Mapping[str, str], cwd: Path) -> ProjectResolution:
    if not projects_by_remote:
        return ProjectResolution(project_id=None, source="cwd_git_remote")
    git_path = shutil.which("git")
    if git_path is None:
        return ProjectResolution(project_id=None, source="cwd_git_remote")
    try:
        completed = subprocess.run(  # noqa: S603 - fixed git argv from PATH resolution, no shell
            [git_path, "config", "--get", "remote.origin.url"],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ProjectResolution(project_id=None, source="cwd_git_remote")
    remote = completed.stdout.strip()
    if not remote:
        return ProjectResolution(project_id=None, source="cwd_git_remote")
    matches = sorted(
        project_id for remote_pattern, project_id in projects_by_remote.items() if remote_pattern in remote
    )
    if len(matches) > 1:
        return ProjectResolution(
            project_id=None,
            source="cwd_git_remote",
            ambiguous_candidates=tuple(matches),
        )
    if matches:
        return ProjectResolution(project_id=matches[0], source="cwd_git_remote")
    return ProjectResolution(project_id=None, source="cwd_git_remote")


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_dict(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProfileConfigError("projects_by_remote must be an object")
    return {str(key): str(item) for key, item in value.items()}


def default_profile_loader_from_env(env: Mapping[str, str]) -> ProfileLoader:
    home = Path(env.get("HOME", os.path.expanduser("~")))
    return ProfileLoader(home=home)
