---
id: "ADR-00043"
title: "dev session claims に iat (最終ログイン日時) を追加 (R-2)"
status: "proposed"
created_at: "2026-06-01"
updated_at: "2026-06-01"
deciders:
  - "t-ohga"
related_sprints:
  - "UI 改善監査 (catalog R-2)"
gate_criteria:
  - "1: 認証・認可 (session token 構造)"
supersedes: []
---

# ADR-00043: dev session claims に iat (最終ログイン日時) を追加 (R-2)

## 背景

UI 改善 catalog の **R-2「最終ログイン日時」**。設定ページの SessionInfo は R-1 でセッション有効期限を
表示するようになったが、「いつログインしたか (最終ログイン日時)」が無い。dev session cookie は login 時に
発行されるが、その **発行時刻 (issued-at)** を保持していないため、最終ログイン日時を表示できない。

### 既存資産 (P0 実在、調査済 2026-06-01)

- dev session cookie は custom HMAC token: `base64url(json claims).signature`。
- `DevSessionClaims` (backend `app/middleware/dev_actor.py`): `actor_id` / `principal_type` / `exp`。
  **`iat` (issued-at) は無い**。
- `create_signed_session_cookie`: `issued_at` (= now) から `exp = issued_at + TTL` を計算して claims に入れるが、
  `issued_at` 自体は claims に保存していない。
- frontend `SessionClaims` (`lib/auth/types.ts`): `actor_id` / `principal_type` / `exp`。
- `actors` table に `last_login_at` column は無い。

## 決定対象

dev session claims に **`iat` (発行時刻 = login 時刻) を追加** し、frontend SessionInfo に「最終ログイン日時」
として表示する契約。**iat は purely informational** (表示のみ。auth / expiry 判定には一切使わない)。

## 設計判断: iat-in-claims (DB migration なし、user 決定 2026-06-01)

単一ユーザー P0 では、現セッション cookie の発行時刻 (= 直近のログイン時刻) が「最終ログイン日時」を
正確に表す。よって **session claims に iat を追加** する方式 (DB 変更なし) を採用する。
`actors.last_login_at` column 追加 (DB migration、cookie 失効を跨ぐ永続) は cookie iat で十分な単一ユーザー
P0 では過剰なため却下。

## 前提 / 制約

- **iat は auth / expiry 判定に使わない**。session 有効性は `exp` のみで判定 (R-1/既存と不変)。iat は表示のみ。
- iat は **HMAC 署名対象に含める** (改ざん不可)。caller / UI からの入力ではない (server-owned)。
- iat に secret / PII を含めない (UNIX 秒の整数のみ)。
- **後方互換**: 既存 cookie (iat 無) は iat=None として degrade (UI は「—」表示)。新規ログインで iat が入る。

## 選択肢

### 案 A (採用): session claims に iat を追加

- backend: `DevSessionClaims.iat` 追加、`create_signed_session_cookie` が iat=int(issued_at) を入れて署名、
  `_parse_claims` で optional 読取。
- frontend: `SessionClaims.iat?` 追加、`parseClaims` / `sessionFromClaims` で `issuedAt` を expose、
  SessionInfo に「最終ログイン日時」表示。

### 案 B (却下): actors.last_login_at column + migration

- 却下理由: DB schema 変更 (最高リスク gate) + auth flow 変更 + /me endpoint を伴うが、単一ユーザー P0 では
  cookie iat で十分。cookie 失効を跨ぐ永続が必要になった段階 (multi-user / P0.1) で再検討。

## 採用案 (案 A) 詳細契約

### backend (`app/middleware/dev_actor.py`)

- `DevSessionClaims` に **`iat: int | None = None`** を追加 (optional、後方互換)。
- `_claims_json`: `iat` が not None のときだけ key を含める (既存 cookie の署名再現性を壊さない。
  iat 無 cookie は iat key 無しで署名されているため、付与すると signature mismatch になる)。**新規発行 cookie は
  常に iat を含む**。
- `create_signed_session_cookie`: `iat=int(issued_at.timestamp())` を claims に入れる。`exp = iat + TTL` は不変。
- `_parse_claims`: `iat` を読み、`int` ならその値、無ければ `None` (既存 cookie)。**exp 検証 logic は不変**。
- `verify_signed_session_cookie`: claims に iat を載せて返す。exp 期限切れ判定は従来通り `exp` のみ。
- **iat は `_set_authenticated_actor` 等の auth 判定に使わない** (request.state には載せない、表示専用)。

### frontend (`lib/auth/`)

- `SessionClaims` に **`iat?: number`** を追加。`parseClaims` は iat が present なら整数検証して採用、
  無ければ undefined。**exp / actor_id / principal_type の検証は不変** (iat 欠如で session を invalid にしない)。
- `DevSession` に **`issuedAt: Date | null`** を追加 (`claims.iat ? new Date(claims.iat*1000) : null`)。
- settings page `loadSessionInfo`: `lastLoginAt = session.issuedAt?.toISOString() ?? null` を SessionInfo へ渡す。
- `SessionInfo`: 「最終ログイン日時」行を追加 (`lastLoginAt` を ja-JP datetime 表示、null は「—」)。

## リスク

| リスク | 対策 |
|---|---|
| iat を auth/expiry に誤用し session 有効性が変わる | iat は表示専用。exp 検証 logic は不変 (test で exp のみが期限判定に使われることを固定)。iat を request.state / auth に載せない |
| iat 改ざんで虚偽の login 時刻表示 | iat を HMAC 署名対象に含める (payload 改ざんで signature mismatch → reject)。tamper test |
| 既存 cookie (iat 無) で UI crash / session invalid | iat optional。iat 無 → None/undefined → UI「—」。session 検証は iat 非依存 (後方互換 test) |
| iat に PII/secret 混入 | iat は UNIX 秒の整数のみ |

## rollback 手順

- 純粋な additive 変更 (claims field 追加 + 表示)。migration なし、DB 変更なし。
- rollback: backend の iat 追加 + frontend の表示を revert。既存 cookie / 認証 logic に影響なし
  (iat 無 cookie は元から有効、新 cookie の iat は無視されるだけ)。

## 実装対象ファイル

- `backend/app/middleware/dev_actor.py`: `DevSessionClaims.iat` + `_claims_json` + `create_signed_session_cookie`
  + `_parse_claims`。
- `frontend/lib/auth/types.ts`: `SessionClaims.iat?` + `DevSession.issuedAt`。
- `frontend/lib/auth/dev-login.ts`: `parseClaims` / `sessionFromClaims` で iat → issuedAt。
- `frontend/app/(admin)/settings/page.tsx`: `loadSessionInfo` に lastLoginAt 追加。
- `frontend/components/session-info.tsx`: 「最終ログイン日時」表示。
- test: `tests/...` (backend dev_actor test、collected path) + `frontend/__tests__/session-info.test.tsx`。

## テスト指針

- backend (`tests/` 配下、collected path):
  - `create_signed_session_cookie` が iat を含み、`verify_signed_session_cookie` が iat を載せて返す。
  - `exp = iat + TTL` (now を固定して検証)。
  - **後方互換**: iat 無 payload を旧 secret で署名 → verify で claims.iat=None、session は有効 (exp が未来なら)。
  - **tamper**: iat を改ざんした payload → signature mismatch で reject (None)。
  - **exp-only expiry**: iat が未来でも exp が過去なら reject (iat を有効性に使わない)。iat が過去でも exp が未来なら有効。
- frontend: `parseClaims` が iat optional (iat 無で session 有効)、`sessionFromClaims` の issuedAt、
  SessionInfo の「最終ログイン日時」表示 (iat あり → datetime、iat 無 → 「—」)。

## 不変条件 trace

- 認証・認可: session 有効性は `exp` のみで判定 (不変)。iat は表示専用で auth に使わない。
- secret 非露出: iat は UNIX 秒整数のみ。cookie secret / actor 機密は不変。
- AI 出力 / Provider / SecretBroker / DB schema に影響なし。migration なし (claims additive のみ)。
