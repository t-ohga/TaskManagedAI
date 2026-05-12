#!/bin/bash
# scripts/worktree_setup.sh
# git worktree 作成直後に 1 回実行する setup script
#
# 目的:
#   - FleetView の自動 worktree 化で作られた worktree でも、Sprint batch 実装に
#     即着手できる状態にする
#   - pnpm install / uv sync / SOPS 復号を 1 コマンド化
#   - 失敗箇所を明示しつつ continue (一部失敗で全体 abort しない)
#
# 使用方法:
#   cd .claude/worktrees/<worktree-name>
#   bash scripts/worktree_setup.sh
#
# 依存:
#   - pnpm (frontend dependencies)
#   - uv (backend Python dependencies)
#   - sops (任意、secret 復号する場合のみ)
#   - age key path (~/.sops-age-key or env)
#
# 出力:
#   - 各 step の成否を [OK] / [SKIP] / [WARN] / [FAIL] で表示
#   - 全 step 完了後 ready 状態 (pytest / pnpm test / docker compose up 可能)
#
# 関連:
#   - .worktreeinclude: gitignored 個人設定の自動 copy 定義 (DD-06 SecretBroker 原則準拠)
#   - docs/設計検討/bg-job-worktree-workflow.md: 並列 bg job 運用 workflow
#   - ~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/reference_fleetview_worktree_workflow.md

set -u  # unbound variable は error、ただし set -e はしない (一部失敗で continue)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

WORKTREE_ROOT="$(pwd)"
FAILED_STEPS=()

log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_skip()  { echo -e "${BLUE}[SKIP]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_fail()  { echo -e "${RED}[FAIL]${NC}  $1"; FAILED_STEPS+=("$1"); }

echo "=================================================="
echo "TaskManagedAI worktree setup"
echo "  worktree: $WORKTREE_ROOT"
echo "  branch:   $(git rev-parse --abbrev-ref HEAD)"
echo "=================================================="

# ----- Step 1: verify worktree context -----
if [ ! -d "$WORKTREE_ROOT/.git" ] && ! git rev-parse --git-dir > /dev/null 2>&1; then
    log_fail "Not inside a git repository / worktree"
    echo
    echo "Aborting setup. Run this script from within a TaskManagedAI worktree."
    exit 1
fi
log_ok "git worktree context verified"

# ----- Step 2: frontend pnpm install -----
if [ -d "$WORKTREE_ROOT/frontend" ] && [ -f "$WORKTREE_ROOT/frontend/package.json" ]; then
    if command -v pnpm > /dev/null 2>&1; then
        echo
        echo "--- [2/5] frontend pnpm install ---"
        if (cd "$WORKTREE_ROOT/frontend" && pnpm install --frozen-lockfile 2>&1 | tail -20); then
            log_ok "frontend dependencies installed (pnpm content-addressable store で main と共有、duplicate なし)"
        else
            log_fail "pnpm install --frozen-lockfile failed (check pnpm-lock.yaml)"
        fi
    else
        log_warn "pnpm not found, skip frontend setup (install via 'npm install -g pnpm')"
    fi
else
    log_skip "no frontend/ directory or package.json, skip"
fi

# ----- Step 3: backend uv sync -----
if [ -f "$WORKTREE_ROOT/pyproject.toml" ] && [ -f "$WORKTREE_ROOT/uv.lock" ]; then
    if command -v uv > /dev/null 2>&1; then
        echo
        echo "--- [3/5] backend uv sync ---"
        if (cd "$WORKTREE_ROOT" && uv sync --locked 2>&1 | tail -10); then
            log_ok "backend dependencies synced (.venv created)"
        else
            log_fail "uv sync --locked failed (check uv.lock)"
        fi
    else
        log_warn "uv not found, skip backend setup (install via 'curl -LsSf https://astral.sh/uv/install.sh | sh')"
    fi
else
    log_skip "no pyproject.toml or uv.lock, skip backend setup"
fi

# ----- Step 4: SOPS env decryption (optional) -----
ENC_PATHS=(
    "config/local/env.local.enc"
    "config/local/env.local.sops"
    "$HOME/.taskmanagedai-secrets/env.local.enc"
)

if command -v sops > /dev/null 2>&1; then
    echo
    echo "--- [4/5] SOPS env decryption (optional) ---"
    ENC_FOUND=false
    for enc_path in "${ENC_PATHS[@]}"; do
        if [ -f "$enc_path" ]; then
            ENC_FOUND=true
            if sops -d "$enc_path" > "$WORKTREE_ROOT/.env.local" 2>/dev/null; then
                log_ok "decrypted: $enc_path → .env.local"
                break
            else
                log_warn "sops decryption failed for $enc_path (age key not available?)"
            fi
        fi
    done
    if [ "$ENC_FOUND" = false ]; then
        log_skip "no encrypted env file found at expected paths (DD-06 SecretBroker 原則: secret 値は SOPS 経由のみ)"
    fi
else
    log_skip "sops not found, skip env decryption (install via 'brew install sops' or equivalent)"
fi

# ----- Step 5: verify .worktreeinclude copies -----
echo
echo "--- [5/5] .worktreeinclude file verification ---"
INCLUDED_FILES=(
    ".claude/settings.local.json"
    ".codex/config.local.toml"
    ".sops.yaml"
)
INCLUDED_COUNT=0
for f in "${INCLUDED_FILES[@]}"; do
    if [ -f "$WORKTREE_ROOT/$f" ]; then
        INCLUDED_COUNT=$((INCLUDED_COUNT + 1))
    fi
done
log_ok ".worktreeinclude copied $INCLUDED_COUNT/${#INCLUDED_FILES[@]} expected files (gitignored personal settings)"

# ----- Summary -----
echo
echo "=================================================="
if [ ${#FAILED_STEPS[@]} -eq 0 ]; then
    echo -e "${GREEN}✅ worktree setup complete${NC}"
    echo
    echo "Ready commands:"
    echo "  Backend:"
    echo "    uv run pytest"
    echo "    uv run ruff check backend tests"
    echo "    uv run mypy backend"
    echo "    uv run alembic upgrade head"
    echo "  Frontend:"
    echo "    cd frontend && pnpm test"
    echo "    cd frontend && pnpm exec eslint . --max-warnings=0"
    echo "    cd frontend && pnpm exec tsc --noEmit"
    echo "  Full stack:"
    echo "    docker compose up --build"
else
    echo -e "${YELLOW}⚠️  worktree setup partial${NC} (${#FAILED_STEPS[@]} step(s) failed)"
    echo
    echo "Failed steps:"
    for step in "${FAILED_STEPS[@]}"; do
        echo "  - $step"
    done
    echo
    echo "Resolve failures above, then re-run this script or proceed manually."
fi
echo "=================================================="
