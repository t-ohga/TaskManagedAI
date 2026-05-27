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

### StatusIndicator コンポーネント
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
- TypeScript ビルド成功 (`pnpm build` in Docker)
- 日本語テキスト漏れチェック (英語 title/description grep = 0)
- ステータスインジケーター一貫性チェック
- モバイルレスポンシブ確認

## 参考資料
- shadcn/ui Kanban Board: WCAG 2.2 AAA + keyboard navigation
- dnd-kit: @dnd-kit/core + @dnd-kit/sortable (Phase 2 defer)
- Agent UX 2026: 透明性 + 介入ポイント + コスト可視化
- マルチエージェントダッシュボード: 統合ビュー + フィルター

## 現在位置
- Phase 0: Master Plan v2 策定完了
- 次: Codex Phase 1 正式レビュー → findings 反映 → 実装開始
