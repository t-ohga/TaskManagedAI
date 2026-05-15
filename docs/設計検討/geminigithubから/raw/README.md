# Raw Evidence Notes

このディレクトリは、Gemini GitHub 取り込み調査の raw evidence / extraction note を置くための予約領域です。

現時点では source repository のファイルをコピーしていません。理由は次の通りです。

- `/Users/tohga/sample/generative-ai` 自体がローカルに存在する。
- notebook / sample code を丸ごと転載すると、調査成果物よりもノイズが大きい。
- TaskManagedAI で必要なのはコード移植ではなく、設計パターンの採否判断。

代わりに `raw/evidence_index.md` に、finding ごとの source-root relative path、line/cell anchor、抽出 claim、TaskManagedAI interpretation を残す。

## 再調査コマンド例

```bash
cd /Users/tohga/sample/generative-ai
git rev-parse --short HEAD
find gemini agents search embeddings rag-grounding tools sdk -maxdepth 3 -type f | sort
rg -n "response_schema|FunctionDeclaration|MCP|grounding|include_citations|context caching|Evaluation|tool_uses|pending_signals|state_delta" gemini agents search embeddings tools
```

## Evidence Handling Rules

- raw secret / token / private project ID は保存しない。
- provider compliance はこの raw source では確定しない。公式 docs 確認結果を別 ADR / Provider Compliance Matrix に残す。
- source code snippet は必要最小限にし、基本は file path と設計判断を記録する。
