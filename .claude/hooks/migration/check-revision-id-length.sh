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
