# Frontend Strategy

TaskManagedAI frontend の最小戦略。  
Next.js 16 + Tailwind CSS のみを基盤候補とし、**component library は未確定**（Phase 0 mapping §6 で shadcn/ui は除外明記、Sprint 9 の Sprint Pack / ADR で承認後に採用判断）。P0 UI が Sprint 9 で始まるまで未確定事項は ADR に寄せる。

## 1. 目的

- P0 UI は運用・承認・監査のための作業画面。
- marketing landing ではなく、最初の画面から実務操作できる dashboard を優先する。
- Ticket、Approval、AgentRun、Audit、Settings、Eval を中心にする。
- provider / secret / runner / repo write は UI から直接 bypass できない。
- UI は traceability を高めるための表示層であり、policy engine の代替ではない。

## 2. Stack

| 領域 | 方針 |
|---|---|
| Framework | Next.js 16 App Router |
| Language | TypeScript strict |
| Styling | Tailwind CSS |
| Component | **未確定**（Sprint 9 の ADR で決定。shadcn/ui 等は Phase 0 で除外明記、ADR 承認後のみ採用） |
| Icons | **未確定**（lucide-react 等は ADR 承認後のみ採用） |
| Test | Vitest + Testing Library |
| E2E | Playwright |
| API | FastAPI OpenAPI client |
| Auth P0 | dev login / actor context |
| Deployment P0 | Tailscale Serve / single VPS |

## 3. Route Candidates

| route | 画面 | P0 |
|---|---|---|
| `/tickets` | Ticket 一覧 | 必須 |
| `/tickets/[id]` | Ticket 詳細 | 必須 |
| `/approvals` | Approval Inbox | 必須 |
| `/agent-runs` | AgentRun 一覧 | 必須 |
| `/agent-runs/[id]` | AgentRun trace | 必須 |
| `/audit` | Audit Log | 必須 |
| `/settings/project` | Project Settings | 必須 |
| `/settings/providers` | Provider Matrix 表示 | 必須 |
| `/eval` | Eval Dashboard | 必須 |
| `/notifications` | In-App Notification | 最小 |

## 4. Server / Client Component

| 種類 | 用途 |
|---|---|
| Server Component | read data、layout、table initial render |
| Client Component | filter、dialog、form、approval action |
| Server Action | 必要時のみ。FastAPI boundary を迂回しない |
| Route Handler | frontend-local API が必要な場合のみ |
| Suspense | slow data / dashboard segment |
| Error Boundary | route-level error |

原則:

- Server Component default。
- Client Component は leaf に寄せる。
- secret 値は client に渡さない。
- `allowed_data_class` を client で算出しない。
- mutation は FastAPI + policy / approval / audit を通す。

## 5. Data Display

| データ | 表示方針 |
|---|---|
| `payload_data_class` | artifact / provider request metadata として表示 |
| `allowed_data_class` | Matrix 由来として表示 |
| AgentRun status | 16 状態をそのまま表示 |
| `blocked_reason` | status と別表示 |
| ContextSnapshot | 10 カラムの summary |
| `secret_ref` | URI metadata は可、raw secret は不可 |
| audit payload | redacted / structured 表示 |
| provider request | redacted fingerprint 中心 |
| cost | tokens / USD / provider / run |
| approval | requester / decider / stale reason |

## 6. UX Principles

- Operational dashboard として密度高く、静かな UI。
- hero / marketing / decorative section を作らない。
- tables、filters、tabs、details panel を中心にする。
- cards は repeated item / modal / framed tool に限定する。
- nested card を避ける。
- UI text は操作に必要な情報に絞る。
- dangerous action は P0 では基本表示しない。
- approval 画面は diff hash / policy version / stale reason を明確にする。
- Audit Log は検索性と raw secret 非表示を両立する。

## 7. Component Library 方針 (P0 では未確定)

Phase 0 mapping §6 で shadcn/ui は除外明記。Component library は Sprint 9 の Sprint Pack / ADR で確定する。

- 採用候補は Sprint 9 で評価し、ADR で proposed → accepted を経て決定。
- 評価軸: P0 UI 必要 component 範囲（Button / Dialog / Table / Form / DropdownMenu 等）、accessibility (WCAG 2.2 AA)、bundle size、TypeScript strict 互換性、license。
- 候補が確定するまでは、最小限の素の HTML + Tailwind で実装し、再利用可能な component は `frontend/components/` の自前 wrapper に閉じ込める。

採用方針 (確定後に守るルール):

- component 追加は必要最小限。
- design token は一箇所に寄せる。
- accessibility を壊す custom wrapper を避ける。
- icon-only button は Tooltip と accessible name を持つ。
- destructive action は AlertDialog 相当 + policy check 前提。

## 8. Cache Components

未確定事項:

- private data cache strategy。
- AgentRun live update strategy。
- approval invalidation と cache invalidation の関係。
- Eval Dashboard read-only cache。
- Provider Matrix version 表示。
- audit log pagination / cache。

扱い:

- Sprint 9 の ADR または Sprint Pack で確定。
- private / actor-specific data は shared cache しない。
- stale approval を cache で隠さない。
- secret / raw provider response は cache しない。

## 9. API Client

- OpenAPI から client 生成を検討する。
- response schema drift を typecheck / contract test で検出する。
- FastAPI error は structured `error_code` を持つ。
- UI は HTTP status だけで判断しない。
- mutation response は audit / event id を返す。
- retry は idempotency key がある operation に限定する。
- provider / runner / secret operation を UI client から直接叩かない。

## 10. P0 Screens

### Ticket

- Acceptance Criteria。
- linked Research / Evidence。
- AgentRun history。
- approval state。
- cost summary。
- audit link。

### Approval Inbox

- action class。
- artifact hash。
- diff hash。
- requester actor。
- stale condition。
- approve / reject。
- self-approval 禁止。

### AgentRun

- status 16。
- `blocked_reason`。
- event timeline。
- ContextSnapshot summary。
- provider request fingerprint。
- cost。
- artifact list。
- retry / resume availability。

### Audit

- event_type filter。
- actor filter。
- resource filter。
- trace / correlation search。
- redacted payload。
- raw secret absence。

### Eval

- Hard Gates 7。
- Quality KPIs 5。
- fixture dataset version。
- public / private / adversarial summary。
- P0 pass / fail rule。

## 11. Playwright Verification

対象 viewport:

- desktop。
- mobile。
- narrow table overflow。
- approval dialog。
- AgentRun event timeline。
- Eval dashboard。

確認:

- text overflow がない。
- button label が収まる。
- modal が viewport に収まる。
- keyboard navigation。
- no raw secret in DOM。
- status / blocked_reason 表示。
- redacted audit payload。

## 12. ADR に送る未確定事項

- Server Actions を使う範囲。
- Cache Components 方針。
- UI state library の要否。
- live update を polling / SSE / websocket のどれにするか。
- generated API client の方式。
- dashboard metric aggregation。
- 採用 component library の theme / token（Sprint 9 で決定）。
- Eval drill-down の P1 移送範囲。

## 13. Review Checklist

- [ ] Server / Client boundary が妥当。
- [ ] FastAPI policy / approval / audit を迂回していない。
- [ ] `payload_data_class` と `allowed_data_class` を混同していない。
- [ ] AgentRun 16 状態と `blocked_reason` 表示が正しい。
- [ ] ContextSnapshot 10 カラムを表示・参照できる。
- [ ] raw secret / token / provider key が DOM に出ない。
- [ ] Playwright で主要 flow を確認した。
- [ ] Cache Components 未確定事項は ADR / Sprint Pack に残した。

