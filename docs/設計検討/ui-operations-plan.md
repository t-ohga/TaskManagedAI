# Master Plan: UI 操作機能の完全実装

## Vision
ユーザーが UI だけで TaskManagedAI の全操作を完結できるようにする。
現在は MCP tool 経由のみで、UI からは閲覧しかできない。

## 現在の問題
- チケット作成: 作成ダイアログは実装したが、Server Action の project_id 解決が未確認
- チケットステータス変更: ボタンは表示のみ (実際に変更する機能なし)
- コメント追記: フォームなし
- 承認 approve/reject: ボタンなし
- AgentRun キャンセル: ボタンなし
- チケット編集 (タイトル/説明): フォームなし

## 実装 Units

### Unit 1: チケット作成の完全動作
- 看板ボードの作成ダイアログ → Server Action → DB → 看板に反映
- project_id は URL の ?project=slug から server 側で解決
- 作成後に revalidatePath で看板を自動更新
- テスト: 作成 → 一覧に表示される E2E

### Unit 2: チケットステータス変更
- チケット詳細ページにステータス変更ドロップダウン or ボタン
- Server Action (updateTicketAction) でステータスを更新
- 更新後に看板のカラム移動が反映される
- テスト: open → in_progress → closed の遷移 E2E

### Unit 3: チケット編集 (タイトル/説明/優先度)
- チケット詳細ページにインライン編集フォーム
- Server Action で更新 → revalidate
- テスト: タイトル変更が反映される

### Unit 4: 承認 approve/reject
- /approvals/[id] ページに承認/却下ボタン
- Server Action → backend approve/reject API
- 却下時は理由入力フォーム
- テスト: pending → approved / rejected の遷移

### Unit 5: AgentRun キャンセル
- /runs/[id] ページにキャンセルボタン
- Server Action → backend cancel API
- テスト: running → cancelled

### Unit 6: Playwright E2E テスト
- 看板ボード表示テスト
- チケット作成フロー
- ステータス変更フロー
- ダッシュボード→看板→詳細の導線

## 現在位置
- Unit 1 着手前
