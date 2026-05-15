# 07 Second Review Corrections

作成日: 2026-05-14

## Verdict

前回成果物の大方向は妥当だったが、以下は修正が必要だった。

| Finding | Severity | Resolution |
|---|---|---|
| source evidence が省略 path で再検証しづらい | WARN | `00_source_inventory.md` と `01_findings_normalized.md` の evidence path を source-root relative に補正し、`raw/evidence_index.md` を追加 |
| 既存 `gemini/generate_content` public-only entry と managed Google service の defer が混ざっている | WARN | README / `03_adoption_decision.md` / `05_provider_adapter_and_tool_boundary.md` で `public-only narrow adapter` と managed service defer を分離 |
| `SP-010` / `SP-011` が未作成 Sprint Pack なのに直接配分されている | WARN | `04_sprint_pack_candidates.md` で `BL-0113`〜`BL-0121`、`BL-0122`〜`BL-0130` へ接続 |
| 新規 DTO 候補が既存 data model との関係を閉じていない | WARN | `06_rag_evidence_eval_design.md` に existing model delta 表を追加 |
| Tool / MCP の受け皿が SP-015 / SP-022 に寄りすぎている | WARN | P0 Tool Registry / Read-only Gateway、SP-014 network policy、SP-015、SP-022 に分解 |
| `payload_data_class` が caller 由来に読める | WARN | server-owned classifier computed from artifact/context と明記し、caller/UI/provider supplied values reject を追記 |
| hybrid search の TaskManagedAI 固有例が source sample の直接根拠のように読める | WARN | SKU/product/codename は source claim、Issue/path/error text は TaskManagedAI 類推ユースケースとして分離 |
| citation coverage が ranking eval sample の metric に見える | WARN | citation coverage は grounding/evidence trace metric として分離 |
| `README.md` / `02_existing_surface_mapping.md` で citation coverage が retrieval/ranking metric と同列に見える | WARN | retrieval/ranking は recall@k / precision@k / NDCG、citation coverage は grounding/evidence trace metric として別行・別 mapping に分離 |
| `raw/evidence_index.md` の一部 source anchor が file-level のまま | WARN | affected rows に line anchor を追加し、再検証時の参照粒度を明確化 |

## Remaining Position

- Google managed services の実利用可否はこの調査では確定しない。
- 既存 `gemini/generate_content` public-only entry は、SP-005 の narrow Gemini structured output adapter を扱うだけである。
- Vertex Search、Agent Platform Runtime、Memory Bank、Code Execution、managed grounding、internal 以上の送信は、feature 単位 Matrix entry と ADR-00010 gate が通るまで採用しない。
- RAG / Evidence は local-first を優先し、managed search は adapter candidate に留める。
