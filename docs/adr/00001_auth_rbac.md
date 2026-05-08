---
id: "ADR-00001"
title: "認証方式: P0 dev login (Cookie + secret token + human:default actor)"
status: "accepted"
date: "2026-05-07"
accepted_at: "2026-05-08"
authors:
  - "t-ohga"
related_sprints:
  - "SP-000_bootstrap"
  - "SP-001_project_foundation"
supersedes: null
superseded_by: null
---

最終更新: 2026-05-08 (Sprint 1 着手前に proposed → accepted 昇格)

## 背景

- 決定対象: P0 dev login、session cookie、actor binding、最小 RBAC 境界。
- 関連 Sprint: SP-000_bootstrap
- 前提 / 制約: P0 は個人 1 user 専用であり、multi-tenant 認証、external IdP、tsidp は対象外。商用化時に IdP token へ置換しても actor / principal schema を壊さない。ADR Gate Criteria #1（認証・認可）に該当する。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: dev login | Cookie + secret token でログインし、`actor_id=human:default` を固定注入する | P0 の個人利用に十分小さい。actor / audit / approval の実装を先に固められる | token 漏えい、cookie scope 誤設定、将来 IdP 移行時の hardcode 残存に注意 |
| B: Tailscale identity 連携 | tailnet identity をアプリ認証主体に使う | 閉域運用と相性がよい | P0 では identity header / tsidp 前提が増え、認証基盤が過大 |
| C: GitHub OAuth | GitHub OAuth で user identity を取得する | 将来の repository 連携や SaaS 化と親和性がある | tenant / workspace / membership 設計が前提になり、P0 の個人運用には重い |

## 採用案

- 採用: A: dev login (Cookie + secret token、`actor_id=human:default` 固定)
- 理由: Sprint 1 の Project Foundation で最小の認証体験と audit 主体を確立できる。IdP 置換時は cookie 内の principal 表現を差し替え、domain 側の actor / principal / audit contract は維持する。
- 実装 Sprint: SP-001_project_foundation
- 実装対象ファイル:
  - `backend/app/auth/`
  - `backend/app/middleware/`
  - `backend/app/models/actor.py`
- 実装ガイダンス:
  - Cookie は host-only、HttpOnly、Secure、SameSite を明示し、Tailscale Serve 上の HTTPS を前提にする。
  - secret token は raw 値を文書、DB、audit、artifact に残さない。rotation は `secret_ref` version 切替に寄せる。
  - middleware は authenticated session から `actor_id=human:default` と `principal=session` を組み立て、audit event `login_succeeded` / `login_failed` に raw token を含めない。
  - `human:default` は P0 固定値だが、RBAC 判定や approval の self-approval 禁止は actor schema 経由で実装し、将来 user id へ置換できるようにする。
- テスト指針:
  - dev login flow: 正しい token で cookie が発行され、誤 token は `login_failed` になる。
  - actor binding: 認証後 request が必ず `human:default` として audit / policy に渡る。
  - cookie scope: path、domain、Secure、SameSite の設定を regression test にする。
  - secret token rotation: 旧 version 無効化、新 version 有効化、旧 cookie 失効を検証する。

## 却下案

- B: Tailscale identity 連携: P0 では tailnet 依存をアプリ認証 contract に混ぜず、Tailscale は network boundary に限定する。P1 以降に再評価する。
- C: GitHub OAuth: tenant / workspace / membership と外部 IdP 運用が必要になり、Sprint 0-1 の目的を超えるため P1 以降に送る。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| secret token が漏えいする | `login_failed` 急増、secret canary / redaction test、audit review | SOPS 管理、短い rotation 手順、raw token の log 禁止 |
| cookie scope 誤設定で意図しない送信が起きる | cookie attribute test、manual browser inspection | host-only / HttpOnly / Secure / SameSite を固定 |
| `human:default` hardcode が将来移行を妨げる | `rg "human:default"` と actor model review | middleware 境界に閉じ、domain model は actor id を opaque に扱う |
| 個人 1 user で approval 境界が曖昧になる | policy decision / approval test | AI / service が requester、human が decider という contract を守る |

## rollback 手順

1. dev login の不具合、cookie scope 逸脱、token 漏えい疑いを検知したら、対象 `secret_ref` version を revoked にし、新規 login を停止する。
2. session cookie を無効化し、直前の有効 token version または修正版 middleware へ戻す。必要なら Tailscale 側で app 到達を一時停止する。
3. `login_succeeded` / `login_failed` / policy audit を確認し、`human:default` の actor binding と cookie 再発行が期待通りであることを検証する。

