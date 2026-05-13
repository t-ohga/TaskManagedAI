#!/usr/bin/env bash
# Alembic migration revision_id length guard.
#
# Alembic default `alembic_version.version_num` is `varchar(32)`. TaskManagedAI
# project convention enforces revision_id <= 30 chars to avoid CI surprises and
# leave headroom for future suffixes.
#
# refs: .claude/rules/testing.md §12, memory/reference_ci_lessons_2026_05_10.md
#       and migrations/env.py `assert_revision_ids_within_limit()`.

set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# project boundary guard (lightweight inline、cross-project hook leak 防止)
# TaskManagedAI worktree 外なら別 project の migrations を見ないよう exit
# HBG-R1-003 + HBG-R1-004 + R2-001 fix: macOS /bin/realpath -m 非対応のため Python3 fallback
_root_abs="$ROOT"
if command -v python3 >/dev/null 2>&1; then
  _root_resolved="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$ROOT" 2>/dev/null || true)"
  [ -n "$_root_resolved" ] && _root_abs="$_root_resolved"
elif command -v realpath >/dev/null 2>&1; then
  _root_resolved="$(realpath -m "$ROOT" 2>/dev/null || realpath "$ROOT" 2>/dev/null || true)"
  [ -n "$_root_resolved" ] && _root_abs="$_root_resolved"
fi
case "$_root_abs" in
  */TaskManagedAI|*/TaskManagedAI/*|*/taskmanagedai|*/taskmanagedai/*) ;;
  *) exit 0 ;;
esac
unset _root_abs _root_resolved

# Alembic default `alembic_version.version_num` is `varchar(32)`. We BLOCK at 32 (technical limit).
# Project convention recommends 30 chars (2-char safety margin) — surfaced as WARN at 31-32.
MAX_LEN=32
RECOMMEND_LEN=30
status=0

if [ ! -d "$ROOT/migrations/versions" ]; then
  exit 0
fi

while IFS= read -r -d '' file; do
  revision="$(
    python3 - "$file" <<'PY'
import ast
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    tree = ast.parse(path.read_text())
except SyntaxError:
    sys.exit(0)
for node in tree.body:
    if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "revision":
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            print(node.value.value)
            break
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if getattr(target, "id", None) == "revision":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    print(node.value.value)
                    break
PY
  )"
  if [[ -n "$revision" && ${#revision} -gt $MAX_LEN ]]; then
    printf 'BLOCK: %s revision_id "%s" is %d chars; max is %d (alembic_version.version_num is varchar(32))\n' \
      "$file" "$revision" "${#revision}" "$MAX_LEN" >&2
    status=1
  elif [[ -n "$revision" && ${#revision} -gt $RECOMMEND_LEN ]]; then
    printf 'WARN: %s revision_id "%s" is %d chars; project convention recommends <= %d chars (technical limit %d)\n' \
      "$file" "$revision" "${#revision}" "$RECOMMEND_LEN" "$MAX_LEN" >&2
  fi
done < <(find "$ROOT/migrations/versions" -type f -name '*.py' -print0)

exit "$status"
