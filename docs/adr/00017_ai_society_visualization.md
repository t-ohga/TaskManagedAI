---
id: "ADR-00017"
title: "AI Society Visualization (P2): role icon + character image generation + board view + agent room visualization"
status: "proposed"
date: "2026-05-10"
authors:
  - "t-ohga"
related_sprints:
  - "SP-017_ai_society_visualization"
  - "SP-021_ai_character_generation"
related_research:
  - "docs/設計検討/phase-c-multi-agent-spec-draft.md §11.3 PE-F-009 (P2 image generation prompt sanitization)"
acceptance_blocked_by:
  - "ADR-00014/19 accepted"
  - "P0.1 完了 + Sprint 17 UI foundation 完了"
---

最終更新: 2026-05-10 (proposed 起票、P2 vision)

## 背景

- 決定対象: TaskManagedAI vision の **「AI 集合体 = 一つの会社」** を **視覚的に表現する** UI 拡張 + role character image (P2 段階)。本 ADR は (1) board view / progress dashboard (P1 SP-017)、(2) role icon default (P1)、(3) character image generation via Codex API (P2 SP-021) の 3 段階を分けて定義.
- ADR Gate Criteria #3 (UI / API 契約) 該当.

## 採用案

### §1: SP-017 (P1) — 最小可視化

- Web UI 拡張: project board / agent role visualization / progress dashboard / inter-agent timeline view
- role icon は **default emoji or static SVG** (例: orchestrator=👔 / implementer=💻 / reviewer=🔍 / tester=🧪 / security_agent=🛡 / researcher=🔬 / observer=👁 / curator=📚 / dispatcher=🚦 / repair_specialist=🔧)
- 動的画像生成は P2 (SP-021) まで含めない
- frontend: `frontend/app/(admin)/orchestrator/board/page.tsx` / `frontend/lib/domain/role-icon.ts`

### §2: SP-021 (P2) — character image generation

| 項目 | 仕様 |
|---|---|
| Provider | Codex / OpenAI Image API / Anthropic Vision (provider 選定は SP-021 着手時 ADR-00020 framework intake checklist で確認) |
| 画像生成 trigger | role icon は default のまま、ユーザーが個別に「カスタム character 生成」を request した時のみ |
| 保存 | `agent_role_icons` table (tenant_id, role_id, icon_url, generated_by_actor_id, generated_at)、画像本体は object store (Tailscale 内 internal) |
| **prompt sanitization (PE-F-009 fix)** | character image prompt に secret pattern / system instruction overwrite / internal context redact を強制、provider に internal classification 情報を送らない |
| Compliance Matrix | image generation provider を ADR-00010 Provider Compliance Matrix に登録 (allowed_data_class=public、payload_data_class=public のみ送信) |
| audit | `character_image_generated` event (provider, role_id, prompt_hash、raw prompt なし) |
| rollback | tenant_config で `character_generation_enabled=false` |

### §3: 8 invariant chart (P2 character generation)

| invariant | 強制 |
|---|---|
| secret canary scan | image prompt 構築時に provider-compliance §8 と同等 scan |
| payload_data_class | image prompt は public のみ送信、internal/confidential/pii reject |
| Provider Compliance Matrix | image generation provider を Matrix に登録、未登録 reject |
| ContextSnapshot | image generation も AgentRun として 16 状態 + 10 列 invariant 維持 |
| audit | character_image_generated + character_image_request_blocked (canary hit / data_class violation) |
| tenant boundary | 各 tenant の character は (tenant_id) scope で隔離 |
| user 任意 | character 生成は opt-in、default は emoji icon |
| roll-back | feature flag で全停止可能 |

### §4: 実装 Sprint

- SP-017 (P1、target 3/max 4 days): board / role visualization / progress dashboard + default emoji icon
- SP-021 (P2、target 1/max 2 days): character image generation (任意機能、user opt-in)

### §5: テスト

- `tests/ui/test_role_visualization.py` (board / dashboard / inter-agent timeline)
- `tests/character_image/test_prompt_sanitization.py` (secret pattern / system instruction overwrite reject)
- `tests/character_image/test_provider_compliance.py` (Matrix 未登録 provider reject)
- `eval/multi_agent/character_image_canary/` (P2 fixture)

## リスク

| リスク | 軽減 |
|---|---|
| character image prompt injection | sanitizer pipeline + provider-compliance §8 |
| public bind に動的 image url 露出 | object store は Tailscale 内部のみ、URL signed token + TTL |
| user 任意性が義務化される | character_generation_enabled=false default、opt-in 明示 |

## rollback

- tenant_config で `character_generation_enabled=false`
- existing character image は object store から削除 (HARD DELETE 含めて ADR Gate Criteria #8 で判断)
- emoji default に degrade

## 関連

- ADR-00014 / ADR-00019 / ADR-00010 (Provider Compliance) / ADR-00020 (Framework Intake) / Phase C §11.3 PE-F-009
