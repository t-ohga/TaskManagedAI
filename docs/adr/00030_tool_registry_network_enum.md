---
id: "ADR-00030"
title: "Tool Registry network_access enum + tool_network_policies"
status: "accepted"
date: "2026-05-22"
accepted_at: "2026-05-22"
authors:
  - "t-ohga"
related_sprints:
  - "SP-014_orchestrator_agent"
  - "SP-0045_tool_registry"
related_adrs:
  - "ADR-00027"
supersedes: null
superseded_by: null
---

最終更新: 2026-05-22 (SP-014 batch 0d 実装と同時に accepted)

## 背景

- 決定対象: `tool_registry.network_access` を boolean から 3 値 enum (`none` / `allowlist` / `internet`) にし、network allowlist の詳細を `tool_network_policies` に分離する。
- 関連 Sprint: SP-014 batch 0d で DB schema / service guard / deny-only seed を実装し、SP-0045 Tool Registry 本体が loader / UI / registry version を引き継ぐ。
- 前提 / 制約: ADR-00009 は `read/search` を action_class へ戻さない。ADR-00027 は Tool Registry 全体の security boundary owner だが、SP-014 では network enum を先行実装する。P0/P0.1 では direct internet は deny-only、許可する場合も allowlist 経由に限定する。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: `none/allowlist/internet` enum + `tool_network_policies` | registry row は network mode のみを持ち、allowlist domain / payload upper bound / provider requirement は別 table に置く | boolean から段階的に拡張でき、P0 deny-only と P0.1 allowlist を同じ schema で表現できる | table が 1 つ増える。service guard が必須 |
| B: boolean のまま維持 | `network_access=false` を継続 | migration が最小 | web_fetch/docs_search の deny-only と将来 allowlist の差分が表現できない |
| C: registry manifest JSON に network policy を埋め込む | `manifest.network` に domain / payload policy を保存 | table 増加なし | DB CHECK / FK / exact query が弱く、policy drift を検出しづらい |

## 採用案

- 採用: A: `none/allowlist/internet` enum + `tool_network_policies`
- 理由: Tool Registry の authorization layer と実 network policy を分離でき、P0 deny-only、P0.1 allowlist、将来 internet 解除の 3 段階を schema で表現できる。`read/search` を ADR-00009 action_class に戻さず、Tool Registry `allowed_actions` 側へ保持できる。
- 実装 Sprint: SP-014 batch 0d
- 実装対象ファイル:
  - `migrations/versions/0028_sp014_tool_registry_network.py`
  - `backend/app/db/models/tool_registry.py`
  - `backend/app/domain/tool_registry/network_policy.py`
  - `backend/app/services/tool_registry/network_policy.py`
  - `tests/services/tool_registry/test_network_policy.py`
  - `docs/基本設計/02_データモデル.md`
- 実装ガイダンス:
  - `network_access='none'`: network call は常に deny。P0 default かつ `web_fetch` / `docs_search` 初期 seed はこの mode。
  - `network_access='allowlist'`: `tool_network_policies.domain_allowlist` exact domain match、`payload_data_class_max` ordinal check、`provider_required` check をすべて満たす場合のみ allow。
  - `network_access='internet'`: enum として登録可能だが P0/P0.1 service guard は deny (`tool_network_internet_denied`)。解除は別 ADR が必要。
  - 新規 tenant には `web_fetch` / `docs_search` の deny-only rows を trigger で seed する。
  - caller-supplied domain / payload class は正規化・検証し、URL path / scheme / port 付き値は bare DNS name ではないため reject する。
- テスト指針:
  - enum exact set (`none/allowlist/internet`) の Python source test。
  - default seed `web_fetch` / `docs_search` は `network_access='none'` で deny-only。
  - new tenant trigger が同じ seed を作る。
  - allowlist は domain / payload / provider requirement の negative case を個別に test。
  - DB CHECK が unknown `network_access` を reject。

## 却下案

- B: boolean 維持では `none` と `allowlist` の違いを表現できず、P0.1 の read-only network tool を deny-only から allowlist へ段階解禁する trace が残らないため却下する。
- C: manifest JSON 埋め込みは schema が弱く、domain allowlist / payload class / provider requirement の FK・CHECK・query が不透明になるため却下する。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| `internet` mode が実装者により直接 allow される | `test_internet_mode_is_registered_but_denied_in_p0` | service guard で `tool_network_internet_denied` を固定し、解除は別 ADR Gate にする |
| allowlist domain match が suffix match になり過許可 | allowlist negative test (`evil.example.com`) | exact domain match のみ採用。wildcard / suffix は別 ADR まで禁止 |
| web_fetch/docs_search が seed だけで実行可能と誤解される | default seed deny-only test | manifest に `deny_only=true` と reason_code を入れ、service guard も `none` を deny |
| new tenant で deny-only tool rows が欠落 | trigger test | `tenants_seed_tool_registry_network` trigger で seed |

## rollback 手順

1. rollback trigger: `tool_registry` / `tool_network_policies` の migration により project startup または DB migration が失敗、または `internet` が deny されない regression を検出。
2. `uv run alembic downgrade -1` で `0028_sp014_tool_registry_network` を rollback し、`tool_registry` / `tool_network_policies` / `tenants_seed_tool_registry_network` を削除する。
3. `uv run alembic upgrade head` と `uv run pytest tests/services/tool_registry/test_network_policy.py -q` を staging DB で再確認する。rollback 後は Tool Registry network enum を参照する runtime path を無効化する。
