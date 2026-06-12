# Docker Stack Hygiene

worktree / 検証 stack の compose project 残骸を作らない常時ルール。
2026-06-12 の整理 (orphan 3 project / 匿名 volume 39 / build cache 16GB = 約 32GB) の再発防止。

## 1. 原則: 起動した stack は起動した側が片付ける

- `docker compose up` した stack は、**同じ作業単位の終了時に `down` する**のが default。
- compose project 名は起動 dir 名 (worktree 名) になるため、worktree を消しても stack / volume / network / image は**自動では消えない** (実例: `ui-tier3-remaining`, `sequence-h-sp015-kickoff`, `sprint-sp-012-batch-7`)。
- **ExitWorktree / worktree 削除の前に必ず確認**:

```bash
docker compose ls -a          # 当該 worktree 名の project が残っていないか
docker compose -p <project> down   # 残っていたら down (volume は default 保持)
```

## 2. Port 規約 (URL 取り違え防止)

| stack | port | 用途 |
|---|---|---|
| 通常 stack (`taskmanagedai`) | 3900 / 8000 / 5432 / 6379 | 実運用 dogfooding |
| 検証 smoke stack (`taskmanagedai_codex_mac_smoke` 等) | 13900 / 18000 / 15432 / 16379 | PR 検証用、検証完了後に down |

- 検証 stack を立てたまま通常 stack と並走させない (検証期間中のみ例外、終了後すぐ down)。

## 3. 保護対象 (削除禁止、user 明示指示時のみ例外)

- `taskmanagedai_postgres_data` / `taskmanagedai_redis_data`: **実運用 DB データ**。`down -v` / `volume rm` / blanket `volume prune --all` 禁止。
- 稼働中の検証 stack の volume (検証完了までは保持)。

## 4. 安全な定期 prune (破壊リスクなし)

```bash
# dangling 匿名 volume のみ (named volume は regex で除外)
docker volume ls -qf dangling=true | grep -E '^[0-9a-f]{64}$' | xargs docker volume rm
# build cache (直近 5GB は keep)
docker builder prune -f --keep-storage 5GB
# dangling image
docker image prune -f
```

- blanket `docker volume prune` / `system prune --volumes` は使わない (named volume を巻き込む)。

## 5. 残骸検知 checklist (整理を頼まれたら最初に実行、説明を鵜呑みにしない)

```bash
docker compose ls -a                       # project 一覧 (created 状態の orphan も出る)
docker ps -a --format 'table {{.Names}}\t{{.State}}\t{{.Ports}}'
docker volume ls | grep -vE '^[0-9a-f]{64}'   # named volume の棚卸し
docker network ls | grep -iE 'taskmanaged|worktree名'
git worktree list                          # volume/project 名と worktree の突合 (worktree 消滅 = orphan 確定)
docker system df                           # reclaimable 把握
```

- 「worktree が存在しない compose project」= 完全 orphan として削除可 (container → volume → network → image の順)。
