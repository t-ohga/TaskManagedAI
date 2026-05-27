# Master Plan: UI 操作機能の完全実装

## Vision
ユーザーが UI だけで TaskManagedAI の全操作を完結できるようにする。
現在は MCP tool 経由のみで、UI からは閲覧しかできない。

## Server Action セキュリティ契約 (Codex R1 findings adopted)

### 全 Server Action の必須ガード
1. **認証**: セッション cookie から actor を resolve
2. **認可**: actor が target project/ticket/run にアクセス権があるか検証
3. **オブジェクトスコープ**: target row を (tenant_id, project_id, id) で load (IDOR 防止)
4. **遷移検証**: 許可された from→to 状態遷移のみ受理
5. **冪等性**: approve/reject/cancel は二重 submit で安全

### project_id 解決
- URL ?project=slug → session の許可済みプロジェクトリストから resolve
- 未認可 slug / 存在しない slug → 拒否 (403/404)
- tenant/workspace/slug 一意制約で解決

### negative テスト (必須)
- 他プロジェクトの ticket_id で更新 → 拒否
- 他プロジェクトの approval_id で approve → 拒否
- 他プロジェクトの run_id で cancel → 拒否
- 不正な状態遷移 (closed → in_progress) → 拒否
- 二重 submit (approve 2回) → 冪等

### 状態遷移表
| from | allowed to |
|------|-----------|
| open | in_progress, blocked, review, closed, cancelled |
| in_progress | blocked, review, closed, cancelled |
| blocked | in_progress, cancelled |
| review | in_progress, closed, cancelled |
| closed | (terminal — 再開不可) |
| cancelled | (terminal — 再開不可) |

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
- テスト: 作成 → 一覧表示 + 未認可 project slug で作成 → 拒否

### Unit 2: チケットステータス変更
- チケット詳細ページにステータス変更ドロップダウン or ボタン
- Server Action (updateTicketAction) でステータスを更新
- 更新後に看板のカラム移動が反映される
- テスト: 正常遷移 + 不正遷移 (closed→open) → 拒否 + 他 project の ticket → 拒否

### Unit 3: チケット編集 (タイトル/説明/優先度)
- チケット詳細ページにインライン編集フォーム
- Server Action で更新 → revalidate
- テスト: タイトル変更が反映される

### Unit 4: 承認 approve/reject
- /approvals/[id] ページに承認/却下ボタン
- Server Action → backend approve/reject API
- 却下時は理由入力フォーム
- テスト: approve/reject + 二重 submit 冪等 + 他 project approval → 拒否

### Unit 5: AgentRun キャンセル
- /runs/[id] ページにキャンセルボタン
- Server Action → backend cancel API
- テスト: cancel + 二重 cancel 冪等 + 他 project run → 拒否

### Unit 6: Playwright E2E テスト
- 看板ボード表示テスト
- チケット作成フロー
- ステータス変更フロー
- ダッシュボード→看板→詳細の導線

## 現在位置
- Unit 1 着手前
