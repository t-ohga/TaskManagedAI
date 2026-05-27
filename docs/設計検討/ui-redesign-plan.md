# Master Plan: TaskManagedAI UI/UX 全面リデザイン v2

## Vision
TaskManagedAI を「人間が直感的に理解でき、AI agent の動作を透明に監視・制御できる、
日本語で完結した AI-native タスク管理 UI」にする。

## 調査結果に基づくデザイン原則 (2026 ベストプラクティス)

### 1. 看板ボード (Kanban Board)
- **3 カラム**: 未着手 (open) → 進行中 (in_progress) → 完了 (completed/closed)
- **WIP 制限表示**: 各カラムにアイテム数カウント
- **空カラム**: 「カードをここにドラッグ」のヒント表示
- **カード設計**: タイトル + ステータスインジケーター + プロジェクトバッジ + 作成日
- **Phase 1**: 静的レンダリング (Server Component)
- **Phase 2 (defer)**: dnd-kit + shadcn/ui でドラッグ&ドロップ

### TicketStatus → 看板カラム配置表

| TicketStatus | 看板カラム | 表示 |
|---|---|---|
| open | 未着手 | デフォルトカラム |
| in_progress | 進行中 | アクティブカラム |
| blocked | 進行中 (ブロック表示) | ブロックインジケーター付き |
| review | 進行中 (レビュー中) | レビューバッジ付き |
| completed | 完了 | 完了カラム |
| closed | 完了 | 完了カラム (closed バッジ) |
| cancelled | 完了 (中止) | 中止バッジ付き、グレーアウト |

→ 3 カラム (未着手 / 進行中 / 完了) に全 7 ステータスをマッピング。
blocked/review は進行中カラム内でサブインジケーターで区別。

### 2. ステータスインジケーター
- **色付きドット + ラベル**: 一目で状態がわかる
- **一貫性**: 全ページで同じインジケーターを使用
- **AgentRun 16 状態 → 7 グループ**: queued/running/completed/failed/cancelled/blocked/waiting

### 3. Agent UX (2026 パターン)
- **透明性**: AI が何をしているか、なぜそうしているかを表示
- **介入ポイント**: ユーザーがいつでもプロセスを停止・変更できる制御
- **リアルタイム進捗**: 実行中の run のステータスをリアルタイム更新
- **コスト可視化**: token 消費量とコストの表示

### 4. マルチプロジェクトダッシュボード
- **統合ビュー**: 全プロジェクトのチケット・run・承認を一画面で
- **プロジェクト切替**: タブまたはセレクターで素早く切替
- **クロスプロジェクト検索**: 横断的なチケット検索

### 5. アクセシビリティ
- **キーボード操作**: 全操作がキーボードで完結
- **スクリーンリーダー**: aria-label / aria-live で状態変更を通知
- **コントラスト**: WCAG AA 準拠 (oklch 0.35 以上)

## 全ページ改修マトリクス

| # | ページ | 現状 | 改修レベル | 主な変更 |
|---|--------|------|-----------|---------|
| 1 | /tickets | リスト表示 | **全面改修** | 看板ボード + プロジェクトタブ |
| 2 | /tickets/[id] | 実データ (基本) | **強化** | 詳細カード + AgentRun 紐付け + コメント |
| 3 | /dashboard | health + プロジェクト一覧 | **強化** | KPI サマリー + クイックアクション + 統合ビュー |
| 4 | /runs | skeleton | **全面改修** | 実データ + ステータスカード + role バッジ |
| 5 | /runs/[id] | skeleton | **全面改修** | 実データ + イベントタイムライン + 状態遷移 |
| 6 | /audit | skeleton | **全面改修** | 実 API + イベントストリーム + フィルター |
| 7 | /settings | skeleton + 英語 | **強化** | 完全日本語 + 読みやすいレイアウト |
| 8 | /approvals | 実データ | **強化** | インジケーター + アクションボタン |
| 9 | /approvals/[id] | 基本 | **強化** | 詳細 + 承認/却下アクション |
| 10 | /orchestrator/board | エラー修正済 | **強化** | Role カード + delegation ツリー |
| 11 | /eval-dashboard | 実データ + 英語混在 | **強化** | 完全日本語 + KPI カード |
| 12 | /eval-dashboard/analytics | skeleton | **全面改修** | 実データ + グラフ |
| 13 | /today | 実データ | **微調整** | カード形式 + 日本語完了 |
| 14 | /timeline | 実データ | **微調整** | 日本語化 |
| 15 | /research | skeleton | **基本実装** | 実データ or 準備中表示 |
| 16 | /notifications | 基本 | **微調整** | バッジ改善 |
| 17 | /onboarding | 基本 | **微調整** | ウィザード改善 |

## 共通コンポーネント設計

### TicketStatusIndicator コンポーネント (チケット用)
```tsx
const TICKET_STATUS_CONFIG = {
  open:        { color: "bg-blue-500",    label: "未着手" },
  in_progress: { color: "bg-amber-500",   label: "進行中" },
  blocked:     { color: "bg-orange-500",  label: "ブロック" },
  review:      { color: "bg-purple-500",  label: "レビュー中" },
  completed:   { color: "bg-emerald-500", label: "完了" },
  closed:      { color: "bg-emerald-500", label: "完了" },
  cancelled:   { color: "bg-gray-400",    label: "中止" },
};
```

### AgentRunStatusIndicator コンポーネント (AgentRun 用)
- `status` + `blocked_reason` を受け取る
- blocked 時: policy_blocked (赤) / budget_blocked (黄) / runtime_blocked (橙) で色分け

### StatusIndicator コンポーネント (レガシー互換)
```tsx
// 使い方: <StatusIndicator status="running" />
// 出力: ● 進行中 (amber ドット + ラベル)

const STATUS_CONFIG = {
  open:       { color: "bg-blue-500",    label: "未着手",   group: "todo" },
  queued:     { color: "bg-purple-500",  label: "待機中",   group: "todo" },
  running:    { color: "bg-amber-500",   label: "進行中",   group: "active" },
  gathering_context: { color: "bg-amber-400", label: "情報収集中", group: "active" },
  in_progress:{ color: "bg-amber-500",   label: "進行中",   group: "active" },
  generated_artifact: { color: "bg-teal-500", label: "成果物生成", group: "active" },
  schema_validated: { color: "bg-teal-500", label: "検証済み", group: "active" },
  policy_linted: { color: "bg-teal-500", label: "ポリシー通過", group: "active" },
  diff_ready: { color: "bg-teal-500",    label: "差分準備完了", group: "active" },
  waiting_approval: { color: "bg-purple-500", label: "承認待ち", group: "waiting" },
  blocked:    { color: "bg-orange-500",  label: "ブロック",  group: "blocked" },
  completed:  { color: "bg-emerald-500", label: "完了",     group: "done" },
  closed:     { color: "bg-emerald-500", label: "完了",     group: "done" },
  failed:     { color: "bg-red-500",     label: "失敗",     group: "error" },
  cancelled:  { color: "bg-gray-400",    label: "中止",     group: "cancelled" },
  provider_refused: { color: "bg-red-600", label: "拒否",   group: "error" },
  provider_incomplete: { color: "bg-amber-600", label: "未完了", group: "active" },
  validation_failed: { color: "bg-red-400", label: "検証失敗", group: "error" },
  repair_exhausted: { color: "bg-red-700", label: "修復不能", group: "error" },
};
```

### RoleBadge コンポーネント
```tsx
// 使い方: <RoleBadge role="orchestrator" />
const ROLE_CONFIG = {
  orchestrator: { color: "bg-indigo-100 text-indigo-700", label: "指揮" },
  dispatcher:   { color: "bg-blue-100 text-blue-700", label: "配分" },
  implementer:  { color: "bg-green-100 text-green-700", label: "実装" },
  reviewer:     { color: "bg-amber-100 text-amber-700", label: "レビュー" },
  researcher:   { color: "bg-purple-100 text-purple-700", label: "調査" },
  tester:       { color: "bg-cyan-100 text-cyan-700", label: "テスト" },
  security_agent: { color: "bg-red-100 text-red-700", label: "セキュリティ" },
  observer:     { color: "bg-gray-100 text-gray-700", label: "観察" },
};
```

### ProjectTab コンポーネント
```tsx
// 使い方: <ProjectTab projects={projects} selected={slug} />
// プロジェクト切替タブバー (全プロジェクト | kintone | ieshima-edu | ...)
```

### プロジェクト切替 URL 契約
- URL: `/tickets?project=<slug>` (query parameter)
- デフォルト: `?project=all` (全プロジェクト横断)
- チケット作成: 選択中の project_id を server action に渡す
- チケット詳細: `/tickets/[id]?project=<slug>` (パンくず用)
- mutation: URL の project slug → server 側で project_id に解決 (caller-supplied 禁止)
- E2E: 非デフォルトプロジェクトでの作成・詳細・更新を完了条件に含める

## 実装 Units (codex-quality-loop で各 Unit を回す)

### Unit 1: 共通コンポーネント基盤
- **scope**: StatusIndicator + RoleBadge + ProjectTab + KanbanColumn
- **phases**: 1 (Codex review), 2 (実装), 4 (最終確認)
- **完了条件**: コンポーネントが独立してレンダリング可能
- **files**: frontend/components/status-indicator.tsx, role-badge.tsx, project-tab.tsx, kanban-column.tsx

### Unit 2: チケット看板ボード
- **scope**: /tickets を看板ボードに全面改修
- **phases**: 1, 2, 3 (敵対), 4, 5 (PR)
- **完了条件**: 3 カラム看板 + プロジェクトタブ + ステータスインジケーター
- **依存**: Unit 1

### Unit 3: ダッシュボード強化
- **scope**: /dashboard をプロジェクトハブに
- **phases**: 2, 4
- **完了条件**: プロジェクトカード (クリック→チケット) + KPI サマリー

### Unit 4: AI 実行ページ全面改修 (/runs + /runs/[id])
- **scope**: skeleton → 実 API + ステータスカード + role バッジ
- **phases**: 2, 3, 4
- **完了条件**: 実 AgentRun データ表示 + イベントタイムライン

### Unit 5: 監査ログ全面改修 (/audit)
- **scope**: skeleton → 実 API + イベントストリーム
- **phases**: 2, 4

### Unit 6: 設定 + 承認 + AI 組織ボード強化
- **scope**: /settings + /approvals + /orchestrator/board の改善
- **phases**: 2, 4

### Unit 7: 評価ダッシュボード + 残りページ
- **scope**: /eval-dashboard + /today + /timeline + /research + /notifications
- **phases**: 2, 4

### Unit 8: 品質最終確認 + Docker ビルド + PR
- **scope**: 全ページ統合テスト + TypeScript ビルド + Codex auto-review
- **phases**: 4, 5

## 品質 Gate (各 Unit)

### 必須検証コマンド
- `pnpm typecheck` — TypeScript 型チェック
- `pnpm lint` — ESLint
- `pnpm test` — Vitest unit test
- `pnpm build` — Docker ビルド成功
- Playwright: `pnpm test:e2e` — 該当 route の E2E

### 各 Unit 固有の完了条件
| Unit | 追加検証 |
|---|---|
| 1 | StatusIndicator: 全 7 TicketStatus + 全 16 AgentRunStatus + blocked_reason 3 種の exact-set テスト |
| 2 | 看板: 全 7 TicketStatus のカードが正しいカラムに配置される fixture テスト |
| 3 | ダッシュボード→チケット→詳細の導線 E2E |
| 4 | /runs: 実 API データ表示 + role バッジ + ステータスインジケーター |
| 5 | /audit: 実 API データ表示 + イベントフィルター |
| 6 | /settings + /approvals + /orchestrator: 日本語 100% |
| 7 | /eval-dashboard + /today + /timeline: 日本語 100% + 導線確認 |
| 8 | 全ページ: 375/768/1024/1440px レスポンシブ + Tab/Enter/Escape キーボード操作 + aria-live |

## 使用する shadcn/ui コンポーネント一覧

### Phase 1 (Unit 1-7) で使用
| コンポーネント | 用途 | 既存/追加 |
|---|---|---|
| Card / CardHeader / CardContent | チケットカード、プロジェクトカード | 既存 |
| Badge | ステータスバッジ、Role バッジ | 既存 |
| Tabs / TabsList / TabsTrigger | プロジェクト切替 | 既存 |
| Select | ステータスフィルター | 追加 (`npx shadcn@latest add select`) |
| ScrollArea | 看板カラムのスクロール | 追加 (`npx shadcn@latest add scroll-area`) |
| Separator | カード間区切り | 既存 |

### Phase 2 (defer) で追加
| コンポーネント | 用途 |
|---|---|
| @dnd-kit/core + @dnd-kit/sortable | ドラッグ&ドロップ |

### Phase 1 でのドラッグ文言
- Phase 1 ではドラッグ&ドロップ非対応
- 空カラムには「チケットはありません」と表示 (「ドラッグ」文言は使わない)
- ステータス変更は ticket_update API 経由 (ボタン or ドロップダウン)

## 参考資料
- shadcn/ui: Card / Badge / Tabs (既存導入済み)
- dnd-kit: @dnd-kit/core + @dnd-kit/sortable (Phase 2 defer)
- Agent UX 2026: 透明性 + 介入ポイント + コスト可視化
- マルチエージェントダッシュボード: 統合ビュー + フィルター

## 現在位置
- Phase 0: Master Plan v2 策定完了
- 次: Codex Phase 1 正式レビュー → findings 反映 → 実装開始
