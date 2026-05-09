#!/usr/bin/env bash
# cross-source-enum-drift-check.sh
# Wave 18 BL-WP018-004 移送 (refs: ADR-harness-consolidation [planned])
# source: feedback_taskmanagedai_invariants.md §1 cross-source enum
#
# file-changed hook で DB CHECK / ORM CheckConstraint / Python Literal enum を比較し
# drift があれば WARN (exit 1)。実装は本 skeleton から別 session で content 充実。
#
# exit 0 = pass / exit 1 = WARN (non-blocking) / exit 2 = BLOCK (drift critical)
set -euo pipefail
FILE_PATH="${1:-}"
[[ -z "$FILE_PATH" ]] && exit 0
# Wave 18 残実装で content 充実: enum grep + drift check
echo "INFO cross-source-enum-drift-check: $FILE_PATH (skeleton、実装は Wave 18 残 session)" >&2
exit 0
