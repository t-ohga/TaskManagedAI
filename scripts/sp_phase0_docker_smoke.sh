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

# 注意: base compose は loopback bind 127.0.0.1:8000/3900 を固定する。smoke 用 port override は
# docker-compose.smoke override で行う想定 (本 helper は project 名 + down -v の安全則を主眼とし、
# port override file が無い環境では base port にフォールバックする = 実運用 stack を起動していない時のみ実行)。
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.dev.yml)
SMOKE_OVERRIDE="docker-compose.smoke.yml"
if [[ -f "$SMOKE_OVERRIDE" ]]; then
  COMPOSE_FILES+=(-f "$SMOKE_OVERRIDE")
fi

_compose() {
  docker compose -p "$PROJECT" "${COMPOSE_FILES[@]}" "$@"
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

case "${1:-all}" in
  up) _up ;;
  down) _down ;;
  all)
    trap _down EXIT
    _up
    echo "[smoke] OK (up + healthz green); auto down on exit"
    ;;
  *)
    echo "usage: $0 [up|down|all]" >&2
    exit 2
    ;;
esac
