---
id: "ADR-00022"
title: "dev_login cookie の secure 属性を environment-conditional 化 (production 強制 / development+test は HTTP loopback 動作)"
status: "accepted"
date: "2026-05-10"
authors:
  - "t-ohga"
related_sprints:
  - "SP-001_project_foundation"
related_research:
  - "ADR-00007 (External exposure boundary、production HTTPS / Tailscale Serve TLS 終端)"
  - ".claude/rules/sprint-pack-adr-gate.md §10 (Break-Glass 例外運用、24h 以内 retro)"
supersedes: null
superseded_by: null
retro_for_commit: "056d9bd"
---

最終更新: 2026-05-10 (retro ADR、commit 056d9bd の事後正式化)

## 背景

- 決定対象: `backend/app/api/auth.py` の dev_login endpoint が発行する session cookie の `Secure` 属性を、`Settings.environment` に応じて conditional に設定する。production のみ `secure=True` 強制、development / test では `secure=False`。
- 関連 Sprint: SP-001 (Project foundation)。本変更は CI 残 failure (`tests/e2e/approval-inbox.spec.ts` の Approval Inbox heading not visible) の root cause fix として実施した。
- 前提 / 制約 (既存 invariant 不変):
  - production: HTTPS / Tailscale Serve TLS 終端を前提 → `secure=True` 強制 (ADR-00007 invariant 維持)
  - development / test: CI Playwright が `http://127.0.0.1:3900` (HTTP loopback) で走る → Chromium 147 が HTTP context で `Secure` 属性付き cookie を silently drop する事象を回避
  - XSS / CSRF 防御は HttpOnly + SameSite=lax で維持 (boundary 不変)
  - cookie value 自体は HMAC-SHA256 署名済 (`create_signed_session_cookie`) → 署名検証で改ざん検知
- ADR Gate Criteria #1 (認証・認可) 該当。`.claude/rules/sprint-pack-adr-gate.md` §10 break-glass exception の 24h 以内 retro 規約に従い proposed → accepted で起票。

## 問題の発見経路

1. `commit 4d6acfe` 後の CI Smoke で 2 件 残 failure (Backend Pytest DetachedInstanceError + Frontend Playwright approval-inbox)
2. Playwright trace 解析 (`/tmp/pw-trace/0-trace.network`):
   - POST `/login?next=/dashboard` (35.773Z): 303 + Set-Cookie `taskmanagedai_session=...; Path=/; Secure; HttpOnly; SameSite=lax`
   - GET `/approvals` (35.809Z): **request_cookies=[]** (cookie 送信されず) → middleware 307 redirect → `/login?next=/approvals`
   - その後の static asset 要求 (35.956Z+) では cookie 付与あり → 「最初の数百ミリ秒は cookie 喪失、後で出現」状態
3. admin-shell.spec.ts は通過: Server Action redirect が RSC payload (`x-action-redirect: /dashboard;push`) で完結し、`/dashboard` への実 GET が発生しないため cookie 不要
4. approval-inbox.spec.ts のみ `page.goto("/approvals")` で実 GET → cookie 必須 → `Secure` 属性で Chromium に drop されており送信なし → /login へ redirect

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: secure を environment-conditional 化 (採用) | production のみ True、dev/test は False | production semantics 不変、最小 patch、明示的 boundary | dev/test は eavesdrop 耐性が弱まる (loopback では非実害) |
| B: CI で HTTPS + 自己署名証明書 | Playwright を HTTPS で走らせる | secure=True 維持 | webServer 設定複雑化、cert 配布、Sprint 1 範囲外 |
| C: secure 属性を一律 False | env 分岐なし | コード単純 | production で eavesdrop 耐性喪失 → 不採用 |
| D: CI で `TASKMANAGEDAI_ALLOW_DEV_ACTOR_FALLBACK=true` | middleware fallback で session 不要化 | cookie 問題回避 | auth boundary を bypass する経路を CI に開ける、approval flow の test 価値喪失 |

## 採用案

- 採用: **A (environment-conditional)**
- 理由:
  - production の HTTPS + Tailscale Serve TLS 終端前提下では `secure=True` 強制を維持し、認証 boundary の strength 不変
  - dev/test の HTTP loopback では `Secure` 属性が silent drop の原因となり、CI 全体の信頼性を毀損していた
  - HttpOnly + SameSite=lax は env 不問で維持され、XSS / CSRF 防御は不変
  - cookie value は HMAC-SHA256 署名 + `verify_signed_session_cookie` で改ざん検知、`Secure` 喪失で攻撃面増加なし (loopback 環境のため)
- 実装 Sprint: SP-001 (CI 残 failure 対応として完了済、commit `056d9bd`)
- 実装対象ファイル:
  - `backend/app/api/auth.py` (`is_production = settings.environment == "production"` + `secure=is_production`)
  - `tests/test_auth.py` (既存 test の Secure assertion 反転 + parametrized cross-env test 新設)
- 実装ガイダンス:
  - production の env detection は `Settings.environment == "production"` の単一基準。Pydantic Settings の Literal type で enum 強制
  - 新規 test `test_dev_login_cookie_secure_attribute_omitted_for_non_production_environments` を development / test 2 環境 parametrized で contract 化
  - production 環境では dev_login endpoint 自体が 404 を返す (`_DEV_LOGIN_ENVIRONMENTS = {"development", "test"}`) ため、production の cookie 設定経路は実行不可 (defense-in-depth)
- テスト指針:
  - `uv run pytest tests/test_auth.py -q` (11 passed: 旧 9 + parametrized 2)
  - `uv run mypy backend` (122 source files clean)
  - `uv run ruff check backend tests` (clean)
  - CI Playwright `frontend/tests/e2e/approval-inbox.spec.ts` で /approvals 遷移後 heading visible の green 確認

## 却下案

- B (HTTPS + 自己署名証明書): Sprint 1 範囲外。Sprint 11.5 (private staging CI/E2E) で Tailscale GitHub Action + Tailscale Serve 経由 HTTPS 化を別途検討。本 fix は P0 path 継続を優先。
- C (一律 secure=False): production で eavesdrop 耐性喪失。Tailscale Serve TLS 終端を前提にしてもアプリ層で `Secure` を維持する depth-in-defense を放棄するのは不適切。
- D (middleware fallback bypass): `TASKMANAGEDAI_ALLOW_DEV_ACTOR_FALLBACK=true` で auth boundary を CI 全体から bypass する経路を生むことになり、approval flow / actor binding の test 価値を喪失。本 fix の対象は cookie 配送の env 整合であり、auth bypass は別問題。

## リスク

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| 本番設定で `environment=production` を見落とすと `secure=False` で動く | `Settings.validate_local_boundary` (config.py §81-87) が production env では placeholder / dev URL を reject + dev_login endpoint が 404 を返す (`_DEV_LOGIN_ENVIRONMENTS`) | Sprint 11.5 で deploy script に `assert TASKMANAGEDAI_ENVIRONMENT == "production"` の preflight 追加 (本 ADR 範囲外) |
| dev/test の loopback 以外で cookie eavesdrop | dev/test は localhost / 127.0.0.1 / Docker bridge 限定 (DD-05 / ADR-00007) | network boundary は ADR-00007 で network layer に閉じている |
| frontend Server Action 側 (`frontend/app/(auth)/login/actions.ts`) の cookie parser が backend Set-Cookie の `Secure` 不在で挙動変化 | 既存 `parseBackendSetCookie` は attribute parser として `secure` flag が不在なら default false、有時は true を立てる | 不在時は false 設定 → ブラウザは secure=false cookie として保持 → HTTP でも送信される (今回の fix と整合) |

## rollback 手順

1. CI Playwright が `/approvals` 遷移で再度失敗、または production で session 喪失が観測された場合
2. `git revert 056d9bd` で auth.py + 2 test を一括 revert
3. CI 結果 + production cookie の Set-Cookie ヘッダ (production access log) で挙動を verify
4. 別経路 (B: HTTPS for CI、または別 fix) を Sprint Pack 追加で着手

## 関連 commit

- `056d9bd` fix(ci): backend pytest DetachedInstanceError + frontend Playwright Approval Inbox の root cause fix
