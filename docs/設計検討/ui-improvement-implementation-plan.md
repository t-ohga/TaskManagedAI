# UI/UX 92件改善 実装計画

## 優先順位マトリクス

### Tier 1: 即効 (HIGH impact × LOW effort) — 15件

| ID | 改善 | 理由 |
|---|------|------|
| F-1 | ナビゲーション active 状態 | 全ページの視認性向上 |
| K-1〜K-4 | 日本語品質 4件 | 文字列置換のみ |
| D-5 | ダッシュボード KPI 重複修正 | 表示値修正 |
| O-5 | 空状態 CTA 追加 | テキスト追加 |
| F-5 | 承認詳細戻りリンク | Link 追加 |
| G-1 | Slug 自動生成 | 関数追加 |
| G-5 | 作成後リダイレクト | redirect 追加 |
| H-1,H-2 | API 並列化 | Promise.all |
| C-5 | 20件制限解除 | slice 削除 |
| O-4 | エラーメッセージ日本語化 | catch 修正 |
| G-2 | 二重実装解消 | 片方削除 |

### Tier 2: 基盤 (HIGH impact × MEDIUM effort) — 20件

| ID | 改善 |
|---|------|
| A-1 | ステータス変更ボタン (Server Action) |
| A-2 | インライン編集 |
| B-1 | グローバル検索バー |
| B-2 | ステータスフィルター |
| C-1,C-2 | リスト表示 + ビュー切替 |
| C-3,C-4 | ソート + ページネーション |
| E-1 | トースト通知 |
| F-2 | パンくずリスト統一 |
| J-1 | キャンセルボタン安全化 |
| N-1 | コメントフォーム |
| O-1〜O-3 | フィードバック + 確認 + ローディング |
| H-3 | ローディングスケルトン |
| T-1,T-2 | audit/runs フィルター |
| T-4,T-5 | tickets 編集/作成配線 |

### Tier 3: 高度 — 25件 (詳細は findings-92.md 参照)
### Tier 4: 将来 — 32件 (P1 以降に defer)

## 実装 Unit (10 Unit)

### Unit 1: 即効修正 15件 (Tier 1 全件)
### Unit 2: チケット操作完全化 (A-1, A-2, T-4, T-5)
### Unit 3: 検索・フィルター (B-1, B-2, C-3, C-4)
### Unit 4: ビュー切替 (C-1, C-2)
### Unit 5: UX 基盤 (E-1, O-1〜O-3, H-3)
### Unit 6: ナビゲーション (F-2, J-1)
### Unit 7: コメント (N-1〜N-3, J-4)
### Unit 8: データ可視化 (D-1, D-2, T-6)
### Unit 9: モバイル + ダークモード (I-1, I-2, M-1, M-4)
### Unit 10: 最終レビュー + 残り Tier 3

## セキュリティ契約
- 全 Server Action: 認証→認可→スコープ→遷移検証→冪等性
- チケット状態遷移表: open→{in_progress,blocked,review,closed,cancelled}
- closed/cancelled は terminal (再開不可)

## 品質 Gate
- Docker ビルド成功
- ESLint clean
- Unit 固有受け入れ条件
- Codex review (高リスク Unit + Unit 10)

## 現在位置
- 洗い出し: 3R / 92件 完了
- 計画: v1 完了
- 次: Codex Quality Loop で計画ブラッシュアップ
