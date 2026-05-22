# Layer A Evidence Addendum (2026-05-22、routing-fix-2026-05-22 hardening)

最終更新: 2026-05-22 (p0-exit-final-hardening-2026-05-22 plan の Phase 3、Layer A verify 経路強化)

status: appended (PR #93 で起票された Layer A evidence への補足)

## 背景

PR #93 の Layer A (`docs/deploy/smoke-evidence/2026-05-22-layer-A.md`) は `pnpm install / pytest / ruff / mypy / vitest / typecheck + eslint / alembic` の 6 task で構成され、全件 PASS と報告された。しかし **本 session (2026-05-22 後半) の SP022-T09 prep Mac smoke verification を実施した結果、`pnpm typecheck` は Next.js `experimental.typedRoutes` の strict check を catch しない false positive** であることが判明した:

| symptom | 根本原因 |
|---|---|
| Layer A typecheck PASS | `tsc --noEmit` 単独では `.next/types/` (Next.js が build 時に生成する Route declaration) が未生成のため typed routes strict check が走らない |
| Docker `pnpm build` で typed routes 2 件 type error が発覚 | (1) `frontend/app/(auth)/login/actions.ts:219` `redirect(safeRedirectPath(parsed.data.next))` で `RouteImpl<string>` 型不一致、(2) `frontend/components/navigation.tsx:48` `href={item.href}` で `/dashboard/tickets` 等の存在しない URL が Route union と非整合 |

この 2 件は実 build (production build または Docker build) を実行しない限り catch できず、CI billing-blocked により直近 20 runs failure で main 上での verification も成立しなかった blind spot。

## Hardening 内容 (p0-exit-final-hardening-2026-05-22 plan Phase 3)

### A-7 step 追加 (Layer A SOP 強化)

`.claude/plans/sp022-t09-prep-mac-smoke.md` Layer A の 6 task 表に **A-7 `pnpm build`** を追加:

| # | task | command | expected | log |
|---|---|---|---|---|
| A-7 | frontend production build (typed routes verify) | `cd frontend && pnpm build` | exit 0、`.next/types/` 生成 + typed routes strict check PASS | `.claude/local/smoke-evidence/A-7-build.log` |

### Verify sequence の変更

**Before (PR #93 まで)**:
```
A-1 deps → A-2 pytest → A-3 ruff+mypy → A-4 vitest → A-5 typecheck+eslint → A-6 alembic
```

**After (本 addendum 以降)**:
```
A-1 deps → A-2 pytest → A-3 ruff+mypy → A-4 vitest → A-5 typecheck+eslint → A-6 alembic → A-7 build
```

- A-7 は `pnpm typecheck` (A-5 内) の **後** に走らせる (`.next/types/` 生成は build で行うが、A-5 の typecheck PASS は false positive を catch しないため、A-7 で実 build を含む verification を 1 段追加)
- `pnpm typecheck` の意味 (= `tsc --noEmit`) は不変、`package.json` も触らない (本 plan §3.1 採用案、棄却した代替案 D 参照)

### catch される latent bug (例)

- typed routes 戻り値型 mismatch (`safeRedirectPath`、`redirect` 等)
- Link href が Next.js route union に含まれない literal を使用
- production build でしか発覚しない optimization-time error (e.g., unused export 検出、bundling)
- Server Component / Client Component boundary 違反 (typecheck 段では検出できない場合)

### Codex PR #93 R1 fix との関係

Codex PR #93 R1 5 findings (1 P1 + 4 P2) 全件 adopt 完了済 (commit `5fc48de`)。本 addendum は Codex PR #93 R1 fix の補完: **R1 fix で SOP rigor 改善は完了したが、Layer A 自体の verify gap (`pnpm typecheck` false positive) は別問題で、本 plan で initial routing fix と同時 hardening する**。

## 影響範囲

- Layer A 所要時間: +30-60 秒 (`pnpm build` の追加分、production build は約 5-15 秒 で完了する想定)
- CI 実行時間: 同様 (本 plan §3.1 で trade-off 検討済、許容範囲)
- Layer A 失敗判定: A-7 で `pnpm build` exit 0 ≠ 0 なら failure として明示記録
- Docker `compose build` も同経路の typed routes check を含むため、Layer B `docker compose build` の二重 verification としても機能

## 影響なし

- backend layer (pytest / ruff / mypy / alembic): 変更なし
- frontend test (vitest): 変更なし
- frontend lint (eslint): 変更なし
- frontend tsconfig / next.config: 変更なし
- 既存 evidence file (`2026-05-22-layer-A.md`): immutable、本 addendum で補足のみ

## 参照

- p0-exit-final-hardening-2026-05-22 plan §3.1 (Layer A 強化、1 案固定)
- p0-exit-final-hardening-2026-05-22 plan §5 Phase 2 step 9 (build → typecheck 順序、F-PR-R1-INFO-2 adopt)
- `.claude/plans/sp022-t09-prep-mac-smoke.md` Layer A 表 (A-7 追加版)
- `frontend/next.config.ts` (`experimental.typedRoutes: true`)
- `frontend/package.json` (`typecheck = tsc --noEmit` 不変、`build = next build` 不変)

## verify 完了条件

- [ ] Layer A SOP に A-7 step が追加済
- [ ] `pnpm build` exit 0 を新規 Mac smoke 実施時に確認
- [ ] Docker `compose build` も併用して二重 verify (Phase 4 Layer B 経路)
- [ ] 本 addendum が PR で merge 済
