---
id: "ADR-00032"
title: "Curator Insights + Multi-Agent Metrics Boundary"
status: "proposed"
date: "2026-05-24"
authors:
  - "t-ohga"
related_sprints:
  - "SP-020_curator_insights_integration"
related_adrs:
  - "ADR-00016"
  - "ADR-00014"
  - "ADR-00009"
  - "ADR-00024"
supersedes: null
superseded_by: null
---

最終更新: 2026-05-24 (SP-020 plan-only gate)

## 背景

- 決定対象: SP-020 で導入する curator / insights / adopted artifact attribution / Phase E PE-F-014〜016 closure の境界を固定する。
- 関連 Sprint: SP-020 curator + insights integration。
- 前提 / 制約:
  - SP-018 memory backend は project-scoped / artifact-bound / untrusted-by-default / feature-flagged read-only retrieval として完了済み。
  - ContextSnapshot 10 列は不変。curator は ContextSnapshot を置換・overlay しない。
  - curator / insights は Hermes pattern adoption only。外部 memory cloud、SQLite、external publishing は禁止。
  - memory record / retrieval / insight / audit payload に raw secret、capability token、raw message body、raw prompt text を残さない。
  - PE-F-014 / PE-F-015 / PE-F-016 は SP-020 exit gate で cross-source closure を確認する。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: SP-018 memory service 上に curator / insights / adopted_artifacts を追加 | memory store/retrieval の ref-only boundary を再利用し、archive と insight は別 service + audit で扱う | 既存 invariant を最小変更で保てる。PE-F-014〜016 closure を同一 Sprint に束ねられる | SP-020 scope が大きく、batch 分割が必須 |
| B: curator 専用 table に raw summary を持つ | insight 取得は単純になる | raw payload 漏えいと ContextSnapshot 迂回のリスクが高い |
| C: external memory/insight service を使う | 実装量は減る | ADR-00020/00016 の external API / persistence deny に反する |

## 採用案

- 採用: A: SP-018 memory service 上に curator / insights / adopted_artifacts を追加。
- 理由: SP-018 で確立した project boundary、sanitizer drift、artifact-bound content、feature flag、untrusted retrieval を壊さずに Wave 22 を進められる。
- 実装 Sprint: SP-020。
- 実装対象ファイル:
  - `backend/app/services/memory/curator.py`
  - `backend/app/services/memory/insights.py`
  - `backend/app/repositories/memory.py`
  - `backend/app/api/memory.py`
  - `cli/tm/commands/memory.py`
  - `migrations/versions/00xx_sp020_curator_insights.py`
  - `tests/memory/test_curator_insights.py`
  - `tests/metrics/test_adopted_artifacts_kpi_boundary.py`
  - `tests/security/test_secretbroker_multi_agent_reason_matrix.py`
- 実装ガイダンス:
  - curator が自動生成する memory は `MemoryStoreService` を通す。record_kind は `auto_completion` / `auto_failure` / `auto_review_finding` のみ。
  - archive は `memory_records.archived_at` を service boundary で設定し、retrieval は既存通り archived record を除外する。
  - insight response は ref-only summary。raw memory content、raw artifact body、capability token、secret-shaped value は返さない。
  - adopted artifact attribution は dedicated link table (`adopted_artifacts`) を第一候補にし、`artifacts` 本体への boolean 追加は避ける。
  - `repo_pr_merged` event_type を追加する場合は ADR-00004 update + 5+ source enum sync を別 batch gate にする。追加しない batch では `repo_pr_opened` proxy を明示する。
  - PE-F-016 は policy schema を再拡張せず、SP-014 で作成済みの `policy_profile_action_effects` exact 14 rows と required review artifact guard を closure test で再検証する。
- テスト指針:
  - curator auto-record は raw payload を保存せず、artifact ref + content_hash のみ。
  - archive 後の retrieval は対象 memory を返さない。
  - insight API / CLI output は ref-only + redaction。
  - adopted_artifacts は tenant/project/run/artifact boundary を持つ。
  - SecretBroker multi-agent reason matrix は 6 case を exact reason_code で検証する。

## 却下案

- B: raw summary 専用 table は secret/canary/message body の永続化リスクが高く、SP-018 の ref-only boundary を迂回するため却下する。
- C: external service は ADR-00016/00020 の pattern-only / external API deny と矛盾するため却下する。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| curator が低価値判定を誤り manual_user memory を archive する | archive policy unit test + manual_user weighting regression | manual_user は default で自動 archive 対象外。tenant_config で opt-in |
| insight summary が raw memory content を返す | no raw sentinel test / secret canary test | response schema を ref-only に固定し、redaction helper を API/CLI 両方で使う |
| adopted_artifacts が citation_coverage を過大評価する | cross-project / non-final artifact negative tests | dedicated link tableに tenant/project/run/artifact FK と final adoption event requirement を置く |
| PE-F-014 reason_code が SP-014/015/016 と drift する | 6 case exact reason matrix test | ADR-00014 §9 と SP-020 test constant を同期し、docs drift test を追加 |

## rollback 手順

1. rollback trigger: curator / insights / adopted_artifacts migration が project boundary、secret redaction、archive exclusion、または Phase E closure test を満たさない。
2. `uv run alembic downgrade -1` で SP-020 migration を戻す。feature flag `TASKMANAGEDAI_MEMORY_CURATOR_ENABLED=false` を維持する。
3. `uv run pytest tests/memory tests/metrics/test_adopted_artifacts_kpi_boundary.py tests/security/test_secretbroker_multi_agent_reason_matrix.py -q` を再実行し、SP-018 retrieval path が影響を受けていないことを確認する。
