---
id: "SP-009-5_p0_ui_deferred_surfaces"
type: "light"
status: "partial_skeleton"
sprint_no: 9.5
created_at: "2026-05-24"
updated_at: "2026-05-24"
target_days: 1.5
max_days: 3
---

最終更新: 2026-05-24

## 目的

- SP-009 から P0.1 へ送る UI 面を独立 Sprint Pack として固定し、SP-009 本体の must_ship と scope creep を分離する。
- Today/Inbox control plane、unified execution timeline、decision packet hash visibility、notification triage、minimal KPI strip、Newcomer Path、`request_revision` を、実装前に read-only surface と state/API mutation surface へ分ける。
- U-02 / U-03 の未決事項を、実装前 approval gate と ADR/API contract gate に落とし込む。

## 対象範囲

| surface | source | P0.1 landing | gate |
|---|---|---|---|
| Today / Inbox control plane | SP-009 Q-E.1 / Q-E.3 | open / due / unassigned work を daily control plane として表示 | read-only UI から開始 |
| Unified execution timeline | SP-009 residual | AgentRunEvent / AuditEvent / Approval / Budget / Eval summary を redacted timeline として統合 | raw payload 非表示 contract |
| Decision packet hash visibility | SP-009 Q-E.1 #2 | artifact_hash / diff_hash / policy_version / provider_request_fingerprint / stale_after_event_seq を表示 | 既存 API で不足する場合は別 API contract PR |
| Notification triage queue | SP-009 Q-E.4 | action-required queue の minimal model を確定 | ADR-00003 event schema gate |
| Minimal KPI strip | SP-009 Q-E.5 | header/top surface に P0 Exit KPI を read-only 表示 | SP-010 / SP-011 metric source 明示 |
| Newcomer Path | SP-009 Q-E.5 | initial tenant onboarding の最小導線 | P0.1 only |
| Approval `request_revision` | SP-009 Q-E.2 | revision_requested flow の採否判断と実装 | ADR-00003 / ADR-00004 / ADR-00009 update 後のみ |

## 対象外

- 本 Pack 作成 PR では code / schema / migration / API route / UI 実装を変更しない。
- `request_revision`、notification triage lifecycle、decision packet API 拡張は、accepted plan + ADR/API contract update なしに実装しない。
- Realtime / voice / raw audio / consent UI は SP-009-5 に含めない。SP-009 Q-E.6 の exclusion を維持する。
- Advanced Approval Inbox の bulk action / 高度 filter / policy editor は P0.1 後続または別 Pack に分ける。

## 実装順序

| batch | scope | boundary |
|---|---|---|
| A | Today/Inbox + minimal KPI strip read-only UI (completed 2026-05-24) | existing API only、mutation なし |
| B | Unified execution timeline read-only UI (completed 2026-05-24) | raw payload key/value を DOM に出さない |
| C | Decision packet hash visibility (completed 2026-05-24) | `stale_after_event_seq` は additive Approval Detail API field として公開、state transition なし |
| D1 | Notification triage DB/API contract (completed 2026-05-24) | additive migration、redacted triage endpoint、actor-owned snooze/resolve、metadata-only audit |
| D2 | Notification triage `/notifications` UI actions | D1 API を利用し、bulk action なしで actor-owned transition のみ |
| E | `request_revision` approval loop | ADR-00003 / ADR-00004 / ADR-00009 update + regression tests |
| F | Newcomer Path / advanced approval refinements | P0.1 polish、P0 Exit blocker にしない |

## 受け入れ条件

- [ ] SP-009 本体は `partial_skeleton` のまま、SP-009-5 への split と未完 residual が明記されている。
- [ ] `docs/sprints/README.md` の canonical registry が `SP-009-5_p0_ui_deferred_surfaces.md` を解決できる。
- [ ] `docs/実装計画/P0_バックログ.md` に P0.1 UI deferred surface の追跡項目がある。
- [x] read-only UI batch と API/state mutation batch が分離され、mutation batch は ADR/API gate を持つ。
- [x] `request_revision` と notification triage は、人間承認・stale invalidation・raw payload redaction の invariant を満たすまで実装しない。

## 検証手順

- [ ] `ruby -e 'require "yaml"; require "date"; YAML.safe_load(File.read("docs/sprints/SP-009-5_p0_ui_deferred_surfaces.md"), permitted_classes: [Date], aliases: true); puts "ok"'`
- [ ] `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh` を本 Pack への PostToolUse JSON で実行
- [ ] `rg -n "SP-009-5_p0_ui_deferred_surfaces|SP-009-5" docs/sprints docs/実装計画 docs/codex-handoff/2026-05-24-post-sp024-carryover`
- [ ] `git diff --check`

## 残リスク

- SP-009-5 は UI 面の束ね直しであり、P0 Exit へ直接必要な SP-009 golden E2E / DOM secret scan / residual enum contract を完了扱いにしない。
- `request_revision` と notification triage は state/API/schema 変更を伴うため、実装時に ADR/API contract update と migration verification が必要。
- Today/Inbox と KPI strip は既存データの欠落が UI 上の空表示に見えやすい。実装時は empty state と source attribution を acceptance に含める。

## Review

- changed: SP-009 から P0.1 deferred UI surfaces を独立 Pack として起票し、Batch A で `/today` read-only control plane + minimal KPI strip、Batch B で `/timeline` unified execution timeline、Batch C で Approval Detail decision packet hash visibility、Batch D1 で notification triage DB/API contract を追加した。
- verified: frontmatter / registry / backlog / handoff cross-reference、frontend typecheck/lint/Vitest、desktop/mobile browser smoke、timeline sensitive key leak check、decision packet malformed-hash DOM non-exposure、notification triage migration up/down + redacted API tests を確認した。
- deferred: notification triage D2 UI actions、`request_revision` state machine は別 PR。
- risks: SP-009 本体の golden E2E / DOM secret scan / residual enum contract は引き続き未完。
