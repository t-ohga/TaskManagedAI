#!/usr/bin/env bash
# SP-PHASE0 S4 #7: throwaway docker smoke (operator-run helper).
#
# 本 helper は **operator (user) が実機 Docker daemon 上で手動実行する** smoke。pytest として hermetic に
# 走らせるのは不可 (real Docker daemon 依存 + 実 compose stack + 実運用 volume 汚染リスク)。よって S4 では
# (1) loopback-binding の regression は `tests/deploy/test_compose_loopback_binding.py` (no-DB pytest) が
# config レベルで担保し、(2) live stack の起動 smoke は本 operator helper + `docs/deploy/mac-single-host-
# smoke-sop.md` (Layer B/C) が担う、という分担にする。
#
# 安全則 (rules/docker-stack-hygiene.md 準拠):
#   - **volume 隔離 (常時保証)**: 専用 throwaway compose project 名 (`taskmanagedai_sp_phase0_smoke`) を使い、
#     終了時の `down -v` は **本 throwaway project の volume のみ**破棄する。実運用 volume
#     (taskmanagedai_postgres_data / redis_data) は project が異なるため一切触らない (blanket prune 禁止)。
#   - **port 隔離 (条件付き)**: 真の専用 port (18000/13900 等、hygiene §2) は `docker-compose.smoke.yml`
#     override を別途用意した場合のみ実現する。**本 helper はその override を同梱しておらず、未配置時は
#     base compose の port (8000/3900/5432/6379) にフォールバックする**。したがって override が無い環境では
#     **実運用 stack (`taskmanagedai`) を停止してから実行**すること (port 衝突回避。volume は上記の通り常時保護)。
#   - **bind-mount 非隔離 (要注意、Codex PR #354 F2)**: base compose は api/worker に
#     `./data/artifacts:/app/data/artifacts` の **host bind mount** を持つ。throwaway project 名 + `down -v` は
#     **named volume のみ**隔離し、**host bind mount (`./data/artifacts`) は隔離しない** → smoke 実行中の
#     artifact 書込が実 repo の `./data/artifacts` に残留する。回避するには (a) **throwaway な checkout / 別 dir**
#     で本 helper を実行する、または (b) `docker-compose.smoke.yml` override で artifact path を temp dir へ
#     差し替える。実運用 checkout で実行する場合は teardown 後に `./data/artifacts` の smoke 生成物を手動確認/削除。
#
# 前提: Docker Desktop running、compose v2、.env.local 等の dev credential が用意済 (SOP §0.1)。
# 使い方:  bash scripts/sp_phase0_docker_smoke.sh up      # 起動 + /healthz green まで待つ
#          bash scripts/sp_phase0_docker_smoke.sh down    # throwaway stack を down -v で破棄
#          bash scripts/sp_phase0_docker_smoke.sh         # up → smoke → down を一括

set -euo pipefail

# 検証 smoke stack の専用 project 名 / port (rules/docker-stack-hygiene.md §2、実運用と並走しても衝突しない)。
PROJECT="taskmanagedai_sp_phase0_smoke"
SMOKE_API_PORT="18000"
SMOKE_FRONTEND_PORT="13900"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# compose interpolation env (user 実機検証 2026-06-21 + Codex PR #355 F1/F2 反映)。
# - compose の `${VAR:?}` interpolation source は precedence 順に: shell env > `--env-file` > cwd `.env`。
#   よって COOKIE_SECRET 等は **`--env-file .env.local`** が供給する (下記 _compose で渡す)。
# - `.env.local` を bash `source` しない (compose env-file は bash 構文保証が無く、`VAR: VAL` / 未 quote backtick 等で
#   破損/実行され得る、Codex F1)。.env.local に無い `TASKMANAGEDAI_ENVIRONMENT` のみ shell default を補う。
ENV_FILE="${ENV_FILE:-.env.local}"
export TASKMANAGEDAI_ENVIRONMENT="${TASKMANAGEDAI_ENVIRONMENT:-development}"

# 注意: base compose は loopback bind 127.0.0.1:8000/3900 を固定する。smoke 用 port override は
# docker-compose.smoke override で行う想定 (本 helper は project 名 + down -v の安全則を主眼とし、
# port override file が無い環境では base port にフォールバックする = 実運用 stack を起動していない時のみ実行)。
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.dev.yml)
SMOKE_OVERRIDE="docker-compose.smoke.yml"
if [[ -f "$SMOKE_OVERRIDE" ]]; then
  COMPOSE_FILES+=(-f "$SMOKE_OVERRIDE")
fi
# `--env-file` は compose の interpolation source (COOKIE_SECRET 等) かつ container env_file の供給元。
# .env.local が無い場合 (例: cleanup 後の down) は付けない (down は placeholder で interpolation を通す、下記)。
COMPOSE_ENV_FILE_ARGS=()
[[ -f "$ENV_FILE" ]] && COMPOSE_ENV_FILE_ARGS=(--env-file "$ENV_FILE")

_compose() {
  docker compose "${COMPOSE_ENV_FILE_ARGS[@]}" -p "$PROJECT" "${COMPOSE_FILES[@]}" "$@"
}

_up() {
  echo "[smoke] starting throwaway stack project=$PROJECT (実運用 taskmanagedai は非対象)"
  _compose up -d --build
  echo "[smoke] waiting for api /healthz ..."
  local api_port="${SMOKE_API_PORT}"
  [[ -f "$SMOKE_OVERRIDE" ]] || api_port="8000"
  local tries=0
  until curl -fsS "http://127.0.0.1:${api_port}/healthz" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [[ $tries -ge 60 ]]; then
      echo "[smoke] FAIL: /healthz did not turn green within timeout" >&2
      _compose logs --tail=50 api >&2 || true
      return 1
    fi
    sleep 2
  done
  echo "[smoke] PASS: /healthz green on 127.0.0.1:${api_port}"
  if [[ -f "$SMOKE_OVERRIDE" ]]; then
    echo "[smoke] frontend (if published) expected on 127.0.0.1:${SMOKE_FRONTEND_PORT}"
  fi
}

_down() {
  echo "[smoke] tearing down throwaway stack project=$PROJECT (down -v、本 project の volume のみ破棄)"
  _compose down -v --remove-orphans
}

# teardown は startup secret 不要 (Codex F2): down 経路は compose ファイル parse で ${COOKIE_SECRET:?} を
# interpolation するが、.env.local が既に削除されていても cleanup できるよう無害な placeholder を補う
# (shell > --env-file precedence のため up では設定しない = .env.local の正値を上書きしない)。
_ensure_down_interpolation_defaults() {
  export TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET="${TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET:-smoke_teardown_placeholder_not_a_secret}"
  export TASKMANAGEDAI_DEV_LOGIN_TOKEN="${TASKMANAGEDAI_DEV_LOGIN_TOKEN:-}"
}

case "${1:-all}" in
  up) _up ;;
  down) _ensure_down_interpolation_defaults; _down ;;
  all)
    # up 失敗で .env.local が無い等でも EXIT trap の teardown が interpolation で止まらないよう default を補う。
    trap '_ensure_down_interpolation_defaults; _down' EXIT
    _up
    echo "[smoke] OK (up + healthz green); auto down on exit"
    ;;
  *)
    echo "usage: $0 [up|down|all]" >&2
    exit 2
    ;;
esac
