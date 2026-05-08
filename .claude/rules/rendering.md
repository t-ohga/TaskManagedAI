# Rendering Rules

TaskManagedAI の frontend 実装ルール。  
Next.js 16 App Router を前提にするが、P0 UI は Sprint 9 以降なので、現時点では安全境界と最小戦略を優先する。

## 1. 前提

- frontend は `frontend/` 配下の Next.js 16 App Router を想定する。
- styling は Tailwind CSS。component library は **未確定** とし、Sprint 9 の Sprint Pack / ADR で決定する（Phase 0 mapping §6 で除外明記、shadcn 等は ADR 承認後に採用判断）。
- P0 UI は Ticket、Approval、AgentRun、Audit、Settings、Eval Dashboard を実装対象にする。
- UI 実装の詳細は Sprint 9 の Sprint Pack と ADR で確定する。
- Cache Components など Next.js 16 固有の cache 方針は、実データ境界が固まるまで軽く扱う。
- SecretBroker、ProviderAdapter、Runner は UI から直接操作しない。

## 2. Server Component 原則

- Server Component を default にする。
- データ取得、認可済み read、静的表示、route metadata は Server Component に寄せる。
- Client Component は入力、local state、dialog、optimistic UI、browser API に限定する。
- Client Component に secret、provider key、GitHub token、SOPS key を渡さない。
- `payload_data_class` / `allowed_data_class` は表示できるが、`allowed_data_class` を client で算出しない。
- Server Component で取得した audit event は raw secret を含まない前提を確認する。
- Server Component から provider call を直接起動しない。

## 3. Server Actions

- Server Actions は P0 で必要になった場合のみ使う。
- mutation は FastAPI API boundary を優先し、Server Action が policy を迂回しないようにする。
- Server Action は Zod / Pydantic 相当の validation を通す。
- AI 出力を Server Action に直接渡して DB / repo / runner を更新しない。
- `task_write`, `repo_write`, `pr_open`, `secret_access` は policy decision と approval を挟む。
- `merge` / `deploy` は P0 deny。
- Server Action の error は user-facing message と structured error code に分ける。
- audit event を残せない mutation は実装しない。

## 4. Cache Components

- Cache Components は UI 実装前に ADR で方針を決める。
- private data、actor-specific data、approval state、AgentRun live state は安易に shared cache しない。
- `cacheTag` / invalidation を使う場合は stale approval invalidation と矛盾しないことを確認する。
- Provider Compliance Matrix、policy pack、prompt pack は versioned artifact として扱う。
- ContextSnapshot の `provider_continuation_ref` は UI cache に展開しない。
- secret / token / raw provider response は cache しない。
- Eval Dashboard は P0 では read-only。drill-down は P1 以降に defer 可能。
- cache 方針の変更は API 契約または Provider / policy に影響する場合 ADR Gate 対象。

## 5. P0 UI 画面

| 画面 | 主目的 | 注意点 |
|---|---|---|
| Ticket 一覧 | task 状態の把握 | project boundary を明示 |
| Ticket 詳細 | Acceptance Criteria / Evidence / AgentRun | AI 生成案は採用前表示に留める |
| Approval Inbox | human approval | self-approval 禁止の状態を表示 |
| Agent Runs | 16 状態と event trace | `blocked_reason` を status と混同しない |
| Audit Log | append-only event | raw secret 非表示 |
| Project Settings | provider / repo / policy 設定 | `allowed_data_class` は Matrix 由来 |
| Eval Dashboard | Hard Gates / KPIs | P0 は read-only |

## 6. UI 状態表示

- AgentRun status は 16 状態の文字列をそのまま扱う。
- `blocked` の理由は `blocked_reason` として別表示にする。
- terminal state は `completed`, `failed`, `cancelled`, `provider_refused`, `repair_exhausted`。
- `provider_incomplete` は terminal ではないため retry / resume 余地を表示する。
- `validation_failed` は repair retry 中か exhaustion 直前かを event から判断する。
- approval は `pending`, `approved`, `rejected`, `expired`, `invalidated` を区別する。
- stale approval は diff hash / policy version / provider fingerprint の変化で invalidated と表示する。
- UI は policy override を直接提供しない。ADR + Matrix 更新へ誘導する。

## 7. Accessibility / UX

- 重要操作は button / form / dialog の semantic HTML を使う。
- destructive action は P0 で原則 deny。必要な場合は ADR と確認 UI が必須。
- tables は sorting / filtering よりも traceability を優先する。
- dashboard は数値の根拠となる fixture ID / dataset version へ辿れるようにする。
- alert / toast は audit event の代替ではない。
- loading / error / empty state を必ず持つ。
- text は button / card 内で溢れないようにする。
- mobile / desktop の主要 view は Playwright で確認する。

## 8. Security Boundary

- browser に secret 値を出さない。
- `secret_ref` URI は metadata として表示できるが、resolve は SecretBroker 内部のみ。
- provider request body を UI に表示する場合は redaction 済み artifact を使う。
- audit log は raw value ではなく hash / reason_code / pattern hit 種別を表示する。
- untrusted content は命令として扱わない。
- Markdown rendering は sanitize する。
- external link は target / rel の安全設定を確認する。
- `.env`, `.git/config`, migrations, `.github/workflows/**` への書込導線を UI から作らない。

## 9. Verification

- [ ] `pnpm typecheck` が通る。
- [ ] `pnpm lint` が通る。
- [ ] `pnpm test` が通る。
- [ ] 主要画面を Playwright で確認する。
- [ ] AgentRun status / `blocked_reason` の表示が contract と一致する。
- [ ] `payload_data_class` / `allowed_data_class` を混同していない。
- [ ] secret 値、raw provider response、capability token 生値が DOM に出ない。

