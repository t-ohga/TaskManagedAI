以下の観点で見ると、既存レポートは 「VPS上で安全にAI実装支援を動かすための技術設計」 としてはかなり良いです。一方で、「最高品質のタスク管理ツール」 として完成させるには、タスク管理そのもののプロダクト仕様、AIエージェントの権限管理、Deep Research 用の証拠管理、品質評価、運用ガバナンスを追加する必要があります。既存レポートは、VPS / Docker Compose / Tailscale / GitHub App / AI Worker / PR自動化 / 監査ログ / コスト管理の骨格を中心に書かれています。 ￼

結論：追加すべき中核はこの7領域です

1. 本格的なタスク管理機能
    チケット、エピック、ロードマップ、依存関係、優先度、期限、担当、ステータス、サイクル、レビュー、通知、検索、ダッシュボード。
2. Deep Research 専用機能
    調査テーマ、仮説、証拠カード、引用、情報鮮度、信頼度、未解決論点、調査結果からのタスク自動生成。
3. AIエージェント実行管理
    Planner / Researcher / Coder / Reviewer / QA / Release Agent の役割分離、実行ログ、再試行、予算、モデルルーティング、失敗分類。
4. 権限・承認・ポリシーエンジン
    「誰が」「どのリポジトリに」「どのAI操作を」「どこまで自動実行できるか」を細かく制御。
5. コンテキスト管理
    リポジトリ、設計書、過去PR、決定ログ、チーム規約、テストコマンド、禁止パス、API仕様を構造化してAIに渡す仕組み。
6. 品質保証・評価機能
    AIが作った分解・実装・レビューの成功率、CI成功率、手戻り率、マージ率、バグ混入率を測る評価基盤。
7. LLM / Agent セキュリティ
    プロンプトインジェクション、機密情報漏えい、過剰な自律性、MCPツール権限、出力検証、コスト暴走への防御。

OpenAIのStructured OutputsはJSON Schemaに沿った出力を安定化でき、Prompt Cachingは繰り返し文脈のコスト・レイテンシ削減に使えます。Codexはコードベースを読み、修正し、テストし、PR提案するクラウド型コーディングエージェントとして位置づけられています。したがって、今後の設計では「AIを1モデルに固定する」のではなく、モデル・エージェント・外部コーディングサービスを差し替え可能なアダプター構造にするのが重要です。

⸻

1. 既存レポートでカバーできているところ

既存レポートで十分にカバーされているのは、主に 技術基盤・安全な公開方式・AI実装支援の初期ワークフロー です。

領域	カバー状況	コメント
VPS / Docker Compose 構成	高	単一VPSから始める方針は妥当
Tailscale Serve / SSH	高	外部公開せずに限定アクセスする思想は良い
GitHub App / GitLab 連携	中〜高	PR作成・Webhook・権限設計の骨格あり
AIによるチケット分解	中	プロンプト例はあるが、評価・再学習・失敗管理が不足
AIによるPR作成	中	ワークフローはあるが、実行環境・安全制御・人間承認がさらに必要
セキュリティ	中〜高	ネットワーク・認証・監査は強いが、LLM固有リスク対策が不足
監査ログ・観測性	中	技術ログ中心。プロダクト品質指標が不足
コスト管理	中	モデル別コスト感はあるが、チケット単位予算・強制停止が必要

一方で、レポートはまだ 「AI実装支援付き開発基盤」 に寄っており、「日常的に使えるタスク管理SaaS級の機能」 と 「Deep Researchをタスク化する知識管理機能」 が薄いです。

⸻

2. 追加すべき詳細機能一覧

A. ワークスペース / プロジェクト管理

機能	必須度	詳細
ワークスペース	必須	個人・チーム・会社単位の最上位領域
チーム管理	必須	開発、デザイン、PM、運用、リサーチなど
プロジェクト	必須	アプリ単位、リポジトリ単位、施策単位で作成
リポジトリ紐付け	必須	GitHub / GitLab repo と project を紐付け
環境定義	必須	dev / staging / production、利用可能CI、デプロイ先
プロジェクトポリシー	必須	AI利用可否、対象ブランチ、禁止パス、承認ルール
メンバー権限	必須	owner / admin / maintainer / planner / reviewer / viewer
プロジェクトテンプレート	高	Webアプリ、API、LP、調査、改善、バグ修正など
アーカイブ	中	完了・停止プロジェクトの凍結保存

ここで重要なのは、タスク管理ツール側に「AIが何をしてよいか」をプロジェクト単位で定義することです。GitHub App の installation token は1時間で失効し、リポジトリ・権限を絞って発行できるため、AI実装支援には個人PATよりGitHub App方式が適しています。

⸻

B. タスク / チケット管理の基本機能

機能	必須度	詳細
チケット種別	必須	Epic / Feature / Bug / Task / Research / Chore / Incident
親子関係	必須	Epic → Story → Task → Subtask
依存関係	必須	blocked by / blocks / related / duplicate
ステータス	必須	Backlog / Ready / In Progress / Review / QA / Done / Blocked
優先度	必須	P0 / P1 / P2 / P3
リスク分類	必須	security / auth / db / billing / migration / infra
受け入れ条件	必須	acceptance criteria を必須項目化
Definition of Done	必須	テスト、レビュー、ドキュメント、CI成功条件
担当者	必須	owner、assignee、reviewer、approver
期限	高	due date、target release、SLA
見積もり	高	story point、想定LOC、想定時間、AIコスト見積もり
ラベル	高	frontend、backend、ai、bug、security、research など
コメント / メンション	必須	チーム内議論、AIへの追加指示
添付ファイル	中	画像、ログ、仕様書、スクリーンショット
履歴	必須	変更履歴、ステータス変更、AI実行履歴
一括編集	中	ラベル、担当、ステータス、プロジェクト変更
カスタムフィールド	高	顧客名、影響範囲、売上影響、契約区分など

このあたりは、既存レポートでは API レベルの tickets は出ていますが、プロダクトとしてのチケット属性がまだ不足しています。特に acceptance_criteria、risk_level、approval_policy、ai_allowed_actions、evidence_links は最初からDBスキーマに入れるべきです。

⸻

C. ビュー / 画面機能

画面	必須度	内容
Inbox	必須	未整理タスク、AIが生成した候補、外部連携から来たタスク
Backlog	必須	未着手チケット一覧
Kanban Board	必須	ステータス別のカード表示
List View	必須	フィルタ・ソートに強い一覧
Roadmap	高	Epic / Milestone / Release 単位の計画
Timeline / Gantt	中	依存関係と期間を可視化
Calendar	中	期限・レビュー・リリース予定
Dependency Graph	高	ブロッカー、並列実行可能性、クリティカルパス
AI Runs	必須	AIが今何をしているかの実行状況
PR / MR Dashboard	必須	AI作成PR、人間レビュー待ち、CI失敗
Research Board	必須	Deep Researchの証拠・仮説・引用・タスク化
Analytics	高	完了数、滞留、AI成功率、手戻り、コスト
Admin Console	必須	権限、モデル、APIキー、監査ログ、ポリシー

タスク管理ツールとして完成度を上げるなら、「チケット一覧」だけでは不十分です。最低でも、Inbox / Board / List / Roadmap / AI Runs / Research Board / Analytics は必要です。

⸻

3. Deep Research タスク管理として必要な専用機能

ここが今回のツールの差別化ポイントになります。通常のタスク管理ではなく、調査 → 判断 → 実装タスク化 → PR化 までつなげるなら、以下が必要です。

Deep Research オブジェクト

通常のチケットとは別に、ResearchTask を持つべきです。

項目	内容
research_question	何を明らかにしたいか
background	背景・前提
hypotheses	仮説
source_requirements	必須ソース種別。公式Docs、論文、GitHub、ニュースなど
freshness_requirement	最新性。30日以内、半年以内、安定情報なら制限なし
evidence_cards	証拠カード
findings	調査結果
confidence	高 / 中 / 低
open_questions	未解決論点
decision	採用判断
generated_tickets	調査から生成された実装チケット
citation_audit	引用確認ログ

証拠カード機能

Deep Research では、AIの文章だけを保存しても不十分です。根拠をカード化する必要があります。

機能	内容
Source Card	URL、タイトル、発行日、取得日、著者、種類
Evidence Extract	重要な要約、短い引用、該当箇所
Reliability Score	公式 / 一次情報 / 二次情報 / 個人ブログなど
Recency Score	最新性
Conflict Detection	ソース同士の矛盾検出
Citation Required Flag	この主張には引用が必要、という印
Evidence-to-Task Link	どの証拠からどの実装タスクが生まれたか

AIエージェントは、OWASP LLM Top 10 2025で示されている Prompt Injection、Sensitive Information Disclosure、Supply Chain、Improper Output Handling、Excessive Agency、Unbounded Consumption などのリスクを受けやすいため、Research結果をそのまま実行命令に変換せず、証拠・判断・実行を分離するべきです。

Research-to-Task 変換機能

調査結果から自動で以下を生成します。

生成物	内容
Epic	大きな実装テーマ
Child Tickets	実装可能な粒度に分解
Acceptance Criteria	完了条件
Risk Flags	auth / DB / security / infra など
Test Plan	必要なテスト
Docs Update	README / docs / ADR更新
Rollback Plan	失敗時の戻し方
Decision Record	なぜその設計にしたか

この機能があると、Deep Research が単なるレポート生成で終わらず、そのまま開発実行に接続できる資産になります。

⸻

4. AI実装支援に必要な詳細機能

AIエージェントの役割分離

1つのAIに全部やらせるのではなく、役割を分けるべきです。

エージェント	役割	自動実行範囲
Intake Agent	入力整理、重複検出、カテゴリ分類	低リスク
Research Agent	最新情報調査、証拠収集、要約	人間確認あり
Planner Agent	チケット分解、依存関係作成	人間承認前提
Estimator Agent	工数、リスク、AIコスト見積もり	自動可
Context Agent	repo map、関連ファイル、テスト検出	自動可
Coder Agent	ブランチ作成、実装、テスト	Draft PRまで
Reviewer Agent	差分レビュー、懸念点抽出	自動可
QA Agent	テスト不足、E2E観点、再現手順確認	自動可
Release Agent	changelog、release note、migration注意点	人間確認
Security Agent	secret、権限、依存関係、危険差分検出	必須
Cost Guard Agent	トークン・実行時間・再試行数の制御	必須

GitHub Copilot coding agent はIssueやUIなどからPR作成を依頼でき、完了後にレビューを求める仕組みを持ちます。ただし、GitHub Docs上ではCopilot coding agentは自身のPRを承認・マージできない設計が説明されているため、自作ツール側も AIはDraft PRまで、人間が承認 を基本原則にすべきです。

Claude Code GitHub Actions も、IssueやPRで @claude を使ってコード解析、PR作成、実装、バグ修正を行う流れを公式に提供しています。したがって、自作ツールは「全部を自前実装する」のではなく、Codex / Claude Code / Copilot / 自前Workerを統一的に呼び出せるAI Agent Adapter を持つ設計が現実的です。

⸻

AI Run 管理機能

AIが作業するたびに AgentRun を作成し、状態を追跡します。

状態	意味
queued	実行待ち
gathering_context	repo / docs / issue / PR を収集中
planning	実装計画作成中
waiting_for_approval	人間承認待ち
executing	実装中
testing	テスト実行中
ci_waiting	CI結果待ち
failed_retriable	再試行可能な失敗
failed_final	最終失敗
pr_created	PR作成済み
review_required	人間レビュー待ち
merged	マージ済み
cancelled	中止
rolled_back	ロールバック済み

各 AgentRun には、最低限以下を保存します。

項目	内容
ticket_id	対象チケット
agent_type	planner / coder / reviewer など
model_provider	OpenAI / Anthropic / GitHub / local など
model_name	実行時に使ったモデル名
prompt_version	プロンプトのバージョン
context_snapshot_id	渡した文脈のスナップショット
allowed_tools	使えたツール一覧
denied_tools	禁止されたツール
token_usage	入出力トークン
cost_estimate	概算コスト
files_changed	変更ファイル
commands_run	実行コマンド
test_results	テスト結果
ci_result	CI結果
approval_events	承認履歴
final_summary	最終要約

これを入れないと、AIが失敗した時に なぜ失敗したか、どこまで実行したか、どの文脈を渡したか が追えません。

⸻

5. AIコンテキスト管理で必要な機能

AI実装支援の品質は、モデル性能よりも 渡す文脈の質 に強く依存します。以下を「Project Context」として構造化するべきです。

コンテキスト	内容
Repository Map	ディレクトリ構造、主要ファイル、依存関係
CODEOWNERS	レビュー担当、責任範囲
Tech Stack	言語、FW、DB、テスト、ビルド
Coding Rules	命名規則、設計規約、禁止事項
Test Commands	unit / integration / e2e / lint
Deployment Rules	デプロイ対象、環境変数、release flow
Forbidden Paths	.env、secrets、migrations、billing、authなど
Architecture Docs	ADR、設計書、README
Past PRs	類似変更、レビューコメント
Open Issues	関連Issue、ブロッカー
API Specs	OpenAPI、GraphQL schema、DB schema
UI Specs	Figma、画面仕様、コンポーネント規約
Security Policy	secret、PII、権限、監査ルール

OpenAIのPrompt Cachingは、静的・反復的な文脈をプロンプト前方に置くことでコストとレイテンシを下げやすくなります。したがって、Project Context、Coding Rules、Repository Summary、Prompt Schema のような共通部分を安定した順序で渡す設計にすると、AI実装支援の費用対効果が上がります。

⸻

6. 権限・承認・ポリシー機能

既存レポートには認証・認可の方向性がありますが、最高品質にするなら ポリシーエンジン が必要です。

AI操作ポリシー

操作	デフォルト方針
チケット要約	自動可
チケット分解	自動可。ただし採用は人間確認
Research実行	自動可。ただし外部情報は引用必須
ブランチ作成	条件付き自動可
ファイル編集	target_paths 内のみ
DB migration作成	人間承認必須
auth / billing / security変更	人間承認必須
secrets参照	原則禁止
.env 編集	禁止
CI実行	自動可
staging deploy	条件付き承認
production deploy	人間承認必須
merge	原則人間承認
rollback	人間承認または緊急ポリシー

承認ルール

条件	必要承認
low risk / docs only	1名
frontend小変更	1名
backend API変更	1〜2名
DB migration	maintainer + admin
auth / permission変更	security approver
billing / payment変更	admin + business owner
production deploy	release approver
secret / infra変更	owner

Tailscale Serve はtailnet内アクセス時にユーザー識別ヘッダーをバックエンドへ渡せ、v1.92以降ではApp Capabilitiesをヘッダーとして転送できます。また、tsidp はTailscaleのネットワークアイデンティティをOIDC/OAuthに変換できる一方、Tailscale自身は実験的プロジェクトで破壊的変更の可能性があると説明しています。したがって、tsidp を使う場合でも、アプリ側に独立したRBAC・承認ログ・緊急管理者経路を残すべきです。

⸻

7. MCP / 外部ツール連携で追加すべき機能

今後のAIタスク管理ツールでは、MCP連携を入れる可能性が高いです。ただし、MCPは便利な反面、ツール権限の設計を誤ると危険です。

必要なMCP Gateway機能

機能	内容
MCP Server Registry	利用可能なMCPサーバー一覧
Tool Allowlist	AIが使えるツールを明示
Scope Management	read-only / write / admin など
Per-Project Tool Policy	プロジェクトごとに許可ツールを制限
Token Broker	短命トークン発行
Tool Call Audit	どのAIが、どのツールを、何のために呼んだか
Dry Run Mode	実行前に影響を表示
Human Confirmation	危険操作前に承認
Output Sanitization	ツール出力を検証・マスク
Secret Boundary	AIにsecretを直接渡さない

MCPの2025-06-18 Authorization仕様では、HTTP transport の認可、OAuth 2.1、PKCE、Resource Indicators、トークンのaudience validation、短命トークンなどが重要な要素として説明されています。また、MCP Security Best Practices は confused deputy 問題、最小権限スコープ、権限昇格イベントのログ化を重視しています。

⸻

8. セキュリティ面で不足している機能

既存レポートはネットワーク・VPS・GitHub権限には強いですが、LLM / Agent 固有の防御をさらに追加するべきです。

LLM / Agent セキュリティチェックリスト

リスク	必要機能
Prompt Injection	外部文書・Issue本文・PRコメントを信頼しない。システム指示とユーザー入力を分離
Sensitive Information Disclosure	secret / PII / 顧客情報の検出とマスキング
Supply Chain	dependency scan、SBOM、lockfile差分レビュー
Data / Model Poisoning	RAGソースの信頼度、更新者、取得日時を保存
Improper Output Handling	AI出力を直接コマンド実行・SQL実行・workflow生成に使わない
Excessive Agency	ツール権限、差分上限、承認ゲート、予算上限
System Prompt Leakage	prompt templateを権限管理し、ログ出力を制限
Vector / Embedding Weaknesses	ベクトルDBにもACLを適用。権限外文書を検索させない
Misinformation	Research結果には引用・信頼度・反証確認を必須化
Unbounded Consumption	token budget、run timeout、再試行上限、並列数制限

OWASP GenAI Security Project は、LLMアプリケーションに対するPrompt Injection、Sensitive Information Disclosure、Supply Chain、Excessive Agency、Unbounded Consumptionなどを主要リスクとして整理しています。AIがコード実行や外部ツール操作を行う本ツールでは、これらを設計初期からDB・API・UIに組み込む必要があります。

⸻

9. 品質保証・評価機能

AIタスク管理ツールは、作って終わりではなく、AIが本当に役に立っているか を測る必要があります。

AI品質メトリクス

指標	意味
decomposition_acceptance_rate	AI分解案が採用された割合
ticket_rework_rate	分解後に修正された割合
pr_creation_rate	チケットからPRまで到達した割合
ci_pass_rate	AI作成PRのCI成功率
human_review_reject_rate	人間レビューで却下された割合
merge_rate	AI作成PRがマージされた割合
bug_after_merge_rate	マージ後バグ率
avg_cost_per_ticket	1チケットあたりAIコスト
avg_time_saved	推定削減時間
retry_count	再試行回数
hallucination_incidents	根拠なし判断・誤情報の件数
security_block_count	セキュリティポリシーで止めた件数

評価データセット

社内用に、以下のようなベンチマークを作るべきです。

データセット	内容
decomposition_eval_set	過去の大きなIssueと理想分解
coding_eval_set	小さな修正タスクと期待diff
review_eval_set	バグ入りPRと期待レビュー指摘
research_eval_set	調査テーマと期待ソース・結論
security_eval_set	prompt injection、secret混入、危険コマンド例
cost_eval_set	同じタスクを複数モデルで実行したコスト比較

NISTのSSDFは、セキュアなソフトウェア開発のためにSDLCへセキュリティ実践を組み込む考え方を示しています。AIによる実装支援も通常の開発プロセスの一部として扱い、設計・実装・レビュー・リリース・運用の各段階に証跡と評価を残すべきです。

⸻

10. データモデルとして追加すべきテーブル

既存の tickets / agent_runs だけでは不足します。最低限、以下を考えるべきです。

テーブル	役割
organizations	組織
workspaces	ワークスペース
teams	チーム
users	ユーザー
memberships	所属・権限
projects	プロジェクト
repositories	GitHub / GitLab repo
environments	dev / staging / production
tickets	チケット
ticket_relations	依存・重複・関連
ticket_comments	コメント
ticket_attachments	添付
acceptance_criteria	受け入れ条件
research_tasks	Deep Researchタスク
evidence_sources	情報ソース
evidence_cards	証拠カード
decisions	意思決定ログ
project_contexts	AIに渡す文脈
context_snapshots	実行時点の文脈スナップショット
prompt_templates	プロンプト
prompt_versions	プロンプト履歴
model_registry	利用可能モデル
agent_runs	AI実行単位
agent_steps	AI実行内のステップ
tool_calls	MCP / API / shell呼び出し
approvals	承認
policies	プロジェクト・AI操作ポリシー
audit_events	監査ログ
notifications	通知
webhooks	外部連携
budgets	コスト上限
evaluations	AI評価結果
releases	リリース
incidents	障害・失敗記録

特に重要なのは、context_snapshots、prompt_versions、tool_calls、approvals、audit_events です。これがないと、AIが行った判断の再現性が失われます。

⸻

11. APIとして追加すべきもの

既存レポートのAPI案に加えて、以下を追加すると実装しやすくなります。

API	目的
POST /workspaces	ワークスペース作成
POST /projects	プロジェクト作成
POST /repos/connect	GitHub / GitLab repo接続
POST /repos/{id}/index	repo map作成
GET /projects/{id}/context	AI用コンテキスト取得
POST /research-tasks	Deep Research作成
POST /research-tasks/{id}/run	調査実行
POST /research-tasks/{id}/generate-tickets	調査からタスク生成
POST /tickets/{id}/estimate	工数・リスク・コスト見積もり
POST /tickets/{id}/plan	AI実装計画生成
POST /tickets/{id}/approve-plan	実装計画承認
POST /tickets/{id}/start-agent-run	AI実装開始
POST /agent-runs/{id}/cancel	実行中止
POST /agent-runs/{id}/retry	再試行
GET /agent-runs/{id}/steps	実行ステップ確認
GET /agent-runs/{id}/tool-calls	ツール呼び出し確認
POST /policies	AI操作ポリシー作成
POST /approvals	承認記録
GET /audit-events	監査ログ
GET /analytics/ai	AI品質・コスト分析
GET /search	横断検索

⸻

12. 既存レポートに記載が薄い・不足している項目

以下は、現時点で追加検討した方がよい不足領域です。

不足領域	なぜ必要か
プロダクト要件	ユーザーが実際に使う画面・ワークフローがまだ薄い
タスク種別設計	Research / Bug / Feature / Incident で必要項目が違う
Deep Research証拠管理	調査結果の根拠・引用・鮮度・信頼度が必要
AI実行状態管理	実行中・失敗・再試行・中止・承認待ちの管理が必要
ポリシーエンジン	AI操作をプロジェクト別に制御する必要がある
MCPセキュリティ	外部ツール権限を誤ると危険
モデルレジストリ	モデル名・価格・性能が変わるためハードコード禁止
プロンプトバージョン管理	どのプロンプトで失敗・成功したか追う必要がある
AI評価基盤	本当に開発効率が上がっているか測定する必要がある
通知設計	承認待ち、CI失敗、レビュー依頼を逃さない
インポート / エクスポート	GitHub Issues、Linear、Jira、CSVなどから移行できると強い
バックアップ復元テスト	バックアップ取得だけでなく復元確認が必要
データ保持ポリシー	AI入出力、ログ、証拠、監査ログの保存期間
ライセンス管理	AIが追加した依存関係・コードのOSSライセンス確認
アクセシビリティ	キーボード操作、色覚、モバイル対応
多言語対応	日本語・英語のチケット、プロンプト、UI
料金・利用制限	将来SaaS化するならプラン・使用量制限
サポート運用	障害時、誤実行時、AI暴走時の対応手順

⸻

13. 最初に作るべきMVP

完璧を目指す場合でも、最初から全部を作ると重くなります。MVPは以下に絞るのがよいです。

MVP Phase 1：安全なAIタスク管理の核

機能	内容
Workspace / Project	最小の組織・プロジェクト管理
GitHub repo接続	GitHub App方式
Ticket CRUD	チケット登録・編集・一覧
Ticket Decomposition	AIによる子チケット分解
Approval Gate	分解案と実装計画の承認
AgentRun管理	AI実行状態、ログ、コスト
Draft PR作成	AIはDraft PRまで
CI結果取得	GitHub Actions結果の表示
Audit Log	すべてのAI操作を記録
Basic Policy	禁止パス、差分上限、承認必須条件
Tailscale限定公開	外部公開せず運用

Phase 2：Deep Research機能

機能	内容
Research Task	調査テーマ管理
Evidence Cards	ソース・引用・信頼度
Research Summary	調査結果生成
Conflict Detection	ソース矛盾チェック
Research-to-Ticket	調査からタスク生成
Decision Log	採用判断の保存
Citation Audit	引用・出典チェック

Phase 3：高度なAI開発基盤

機能	内容
Model Registry	モデル・価格・用途管理
Agent Adapter	Codex / Claude / Copilot / 自前Worker切替
MCP Gateway	外部ツールの安全な利用
Context Indexing	repo / docs / PR / issue の文脈管理
Eval Harness	AI品質評価
Cost Dashboard	チケット別・モデル別コスト
Security Agent	secret / dependency / risky diff検出

Phase 4：チーム運用・SaaS品質

機能	内容
Roadmap	Epic / milestone / release
Analytics	生産性・AI成功率・ボトルネック
Notification	Slack / Email / GitHub通知
Import / Export	GitHub Issues / Jira / Linear / CSV
Advanced RBAC	チーム・プロジェクト・環境別権限
Backup / Restore UI	復旧確認
Billing / Usage	SaaS化する場合
Multi-tenant Security	組織間分離

⸻

14. 最終的な推奨仕様

最終的には、以下のようなプロダクトにすると非常に強いです。

「Deep Researchから実装PRまでを一気通貫で管理する、AI-nativeな開発タスク管理ツール」

中核コンセプトはこうです。

調査テーマを登録すると、AIが最新情報を調査し、証拠付きで結論をまとめ、実装可能なチケットに分解し、リポジトリ文脈を読んで実装計画を作り、人間承認後にブランチ・実装・テスト・Draft PR作成まで進める。すべての判断、引用、ツール呼び出し、コスト、承認、CI結果は監査可能に残る。

この方向であれば、単なるタスク管理でも、単なるAIコーディングツールでもなく、「調査・意思決定・実装・レビュー・運用」をつなぐ開発OS にできます。既存レポートに追加するべき最重要ポイントは、Deep Research証拠管理、AI Run管理、ポリシーエンジン、コンテキスト管理、評価基盤、LLMセキュリティ の6つです。
