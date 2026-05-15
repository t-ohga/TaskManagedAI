# 08 Third Review Corrections

作成日: 2026-05-14

対象:

- source: `/Users/tohga/sample/generative-ai` at `75873ec1`
- output: `/Users/tohga/repo/TaskManagedAI/docs/設計検討/geminigithubから`

## Review Verdict

3 回目レビューでは、前回までの文書は大筋で正しい一方、次の 5 領域の分類が不足していた。

| ID | Finding | Resolution |
|---|---|---|
| R3-001 | `gemini/code-execution` と `gemini/computer-use` が、便利な tool example として読めてしまい、provider-managed execution/browser action の危険度が明示不足だった | `GMG-F-019` を追加し、direct execution は reject。将来採用する場合も Runner / Tool Gateway / sandbox / approval / artifact / audit 必須にした |
| R3-002 | `gemini/responsible-ai` の safety ratings、prompt/RAG attack、DLP bypass の知見が `OutputValidator` / Eval へ接続されていなかった | `GMG-F-020` と `GMG-D-025` を追加し、SafetyMetadataRef、secret canary、prompt/RAG/tool-output injection fixtures へ接続した |
| R3-003 | URL Context、Batch Prediction、Multimodal Live API が、feature 別の provider surface として分類されていなかった | `GMG-F-021`〜`GMG-F-023` を追加し、URL snapshot、async job ledger、realtime retention/token/tool-call gate が揃うまで defer とした |
| R3-004 | retry / model optimizer が provider reliability / routing audit へ接続されていなかった | `GMG-F-024` / `GMG-F-025` と Provider Reliability Policy を追加し、bounded retry、idempotency、resolved model trace を明示した |
| R3-005 | custom embeddings / custom ranking が local-first retrieval と ranking policy の設計に十分反映されていなかった | `GMG-F-026` / `GMG-F-027`、EmbeddingSourceVersion、RankingPolicyVersion の追加方針を反映した |

## Traceability Corrections

前回文書には、Sprint Pack への接続で誤解を生む余地があった。修正後の判断は次の通り。

- global P0 backlog の `BL-*` を正本として読む。
- Sprint Pack-local `BL-*` と ID が衝突する箇所は、実装前に namespace か translation table を作る。
- `SP-0045_tool_registry`, `SP-010_research_evidence`, `SP-011_eval_harness` は重要な受け皿だが、取り込み文書だけでは実装準備完了にならない。
- この文書群は、採用判断と gate を整理する成果物であり、managed Gemini feature の実利用許可ではない。

## Final Adopt / Defer Balance

| Area | Final treatment |
|---|---|
| Agent state / resume | adopt as design pattern |
| Structured output / tool schema | adopt through ProviderAdapter + OutputValidator |
| MCP / tool registry | adopt with Gateway, allowlist, sandbox, audit |
| Search / grounding / RAG eval | adopt local-first; provider metadata is only a seed |
| Retry / timeout | adopt as provider-neutral reliability policy |
| Safety ratings / attack mitigation | adopt as metadata + negative fixtures, not as final approval |
| Code Execution / Computer Use | reject direct use; defer any provider-managed execution until Runner/Tool Gateway gate exists |
| URL Context | defer until source snapshot and fetch policy exist |
| Batch Prediction | defer until async job ledger and retention/deletion policy exist |
| Multimodal Live API | defer high-risk / P1+ |
| Model Optimizer | defer until resolved model compliance/eval/cost trace exists |
| Custom embeddings / ranking | adopt concepts local-first; defer provider backend dependence |

## Remaining Non-Blocking Work

- Sprint Pack 正本化: `SP-0045`, `SP-010`, `SP-011` を作るか、既存 pack へ正式統合する。
- Provider Compliance Matrix: Gemini feature を `generate_content` から分離し、feature 単位 entry を作る。
- Eval fixtures: prompt injection、RAG injection、tool-output injection、secret canary、retry exhaustion、URL source missing を fixture 化する。

これらは TaskManagedAI 本体の後続 Sprint 作業であり、この Gemini intake 文書の完了条件からは切り離す。
