# 06 RAG Evidence Eval Design

## Local-First Evidence Retrieval

Gemini repository examples are strongest around RAG / grounding / search / evaluation, but TaskManagedAI should not start with Vertex AI Search as the source of truth. The first implementation should be local-first:

```text
Task / Research question
-> SearchRun
-> lexical search + optional vector search + metadata filters
-> RRF / ranking policy
-> EvidenceSearchHit[]
-> EvidenceItem / EvidenceCard
-> Claim / citation trace
-> ReviewArtifact / EvalRun
```

## Proposed Entities

| Entity | Purpose |
|---|---|
| `SearchRun` | query, source set, ranking policy version, filters, top_k, actor/run context |
| `EvidenceSearchHit` | normalized hit from local or provider search |
| `GroundingSupport` | answer span, source chunk refs, URI/path, retrieval query, provider metadata |
| `RankingPolicyVersion` | lexical/vector weights, RRF alpha, boost/filter rules, feature contributions |
| `RetrievalEvalRun` | retrieval metric run with dataset version |
| `ResearchBenchmarkItem` | generated or human-authored Q&A / claim verification item |
| `EmbeddingSourceVersion` | model, dimension, task_type, source corpus hash, sanitizer, re-embedding policy |
| `UrlSourceSnapshot` | fetched URL, trust classification, retrieval metadata, content hash, fetch policy version |

## Existing Model Delta

These names are design candidates, not an instruction to create all-new tables immediately.

| Candidate | Existing surface | Recommended landing | Phase |
|---|---|---|---|
| `SearchRun` | `ResearchTask`, AgentRun artifact/event, audit event | new table or artifact schema after `BL-0113` / `BL-0114`; must include project boundary and ranking policy version | P0 backlog, Sprint Pack not yet created |
| `EvidenceSearchHit` | `EvidenceSource`, `EvidenceItem` | existing table extension or child table after `BL-0114` / `BL-0115`; store normalized hit metadata and payload hash, not raw provider response | P0 backlog |
| `GroundingSupport` | `Claim`, `EvidenceItem`, `provenance_json` | artifact schema or `provenance_json` extension first; table only if citation UI needs querying | P0 backlog `BL-0115` / `BL-0119` |
| `RankingPolicyVersion` | policy pack / eval dataset metadata | artifact or config version first; table can wait until multiple policies are actively compared | P0.1 defer unless SP-010 needs queryable history |
| `RetrievalEvalRun` | `eval_runs`, `eval_scores`, `dataset_versions` | existing eval tables; add metric names and fixture metadata rather than a separate table by default | P0 backlog `BL-0122`〜`BL-0130` |
| `ResearchBenchmarkItem` | `eval_cases`, `dataset_versions`, private gold tasks | eval fixture item; human validation required before acceptance fixture promotion | P0 backlog `BL-0122` / `BL-0163` |
| `EmbeddingSourceVersion` | retrieval config / artifact metadata | start as immutable artifact metadata before adding table; must block dimension/model mismatch | P0.1 defer unless vector retrieval is selected |
| `UrlSourceSnapshot` | EvidenceSource / EvidenceItem / artifact store | required before provider URL Context output can become evidence; provider metadata alone is not source of truth | P0 backlog if web fetch is enabled |

## EvidenceSearchHit Draft

```json
{
  "hit_id": "uuid",
  "search_run_id": "uuid",
  "source_kind": "doc|issue|pr|code|audit|external",
  "source_ref": "artifact or repo path",
  "project_id": "uuid",
  "title": "string",
  "snippet": "redacted short text",
  "score": 0.0,
  "rank": 1,
  "lexical_score": 0.0,
  "vector_score": 0.0,
  "metadata_filter_match": true,
  "ranking_policy_version": "string",
  "payload_hash": "sha256",
  "sanitizer_version": "string"
}
```

## Ranking Policy

Source evidence:

- `search/vais-building-blocks/ingesting_unstructured_documents_with_metadata.ipynb`: metadata can improve recall/precision and support filtering.
- `search/vais-building-blocks/query_level_boosting_filtering_and_facets.ipynb`: query-level boost/filter/facet examples.
- `search/vais-building-blocks/record_user_events.ipynb`: user event collection examples.
- `embeddings/hybrid-search.ipynb`: dense + sparse / hybrid retrieval pattern.

Adopt the pattern from Gemini search examples:

- lexical + semantic hybrid retrieval,
- RRF-style rank fusion,
- metadata filters as hard constraints,
- boost as soft preference,
- user/event feedback only after audit model, consent/retention, and project boundary are defined.

TaskManagedAI-specific ranking features:

| Feature | Use |
|---|---|
| project scope | hard filter |
| source trust level | boost / filter depending on query |
| freshness | boost for current design decisions |
| review verdict | boost accepted/reviewed artifacts |
| citation support | boost evidence with verified citation |
| contradictory evidence | do not suppress; surface as conflict |

## Embedding Metadata

The custom embedding and task-type embedding samples are useful, but direct provider embedding storage creates migration risk. TaskManagedAI should record enough metadata to safely rebuild or compare indexes:

```json
{
  "embedding_source_version": "string",
  "model": "provider/model id",
  "dimension": 768,
  "task_type": "RETRIEVAL_DOCUMENT|RETRIEVAL_QUERY|unspecified",
  "source_corpus_hash": "sha256",
  "sanitizer_version": "string",
  "created_at": "timestamp",
  "reembed_policy": "required_on_model_or_dimension_change",
  "provider_compliance_ref": "matrix feature id"
}
```

Rules:

- query/document task types must be explicit when the model supports asymmetric embeddings;
- vector indexes with different dimensions are separate indexes, not mixed rows;
- re-embedding is a planned migration with cost/budget and rollback, not an automatic side effect;
- provider embedding output is not sent internal data unless the feature-specific Matrix entry allows it.

## Eval Metrics

| Metric | Purpose |
|---|---|
| `recall@k` | required evidence appears in top-k |
| `precision@k` | top-k noise control |
| `ndcg@k` | ranking quality |
| `citation_coverage` | final claims linked to evidence |
| `grounded_answer_rate` | answer contains sufficient evidence |
| `tool_trajectory_match` | expected tools and order were followed |
| `approval_gate_compliance` | high-risk actions waited for approval |
| `secret_canary_no_leak` | no canary in provider/tool/audit output |

`citation_coverage` is not a retrieval ranking metric from the ranking notebooks themselves. It belongs to the grounding/evidence trace path: provider grounding metadata may seed it, but TaskManagedAI must compute final coverage from claims, evidence snapshots, and citation verifier status.

## Auto RAG Eval Adaptation

The Auto RAG Eval sample is useful as a pattern, but should be rewritten:

| Sample stage | TaskManagedAI adaptation |
|---|---|
| document selection | source set sampled from docs/issues/PRs/research artifacts |
| chunk processing | sanitizer + project boundary + artifact hash |
| clue generation | structured `ResearchQuestionSeed` |
| context retrieval | local-first `SearchRun` |
| Q&A generation | `ResearchBenchmarkItem` with provenance |
| critic review | multi-reviewer `ReviewArtifact` |
| incremental save | append-only artifact + dataset version |
| transform benchmark | export to Eval Harness format |

## URL Context Handling

The URL Context sample can retrieve URLs and return URL metadata, which is useful as a retrieval hint. It is not enough for TaskManagedAI evidence.

Before any URL Context result is treated as evidence:

1. URL must pass project/network/fetch policy.
2. Fetched content must be stored as `UrlSourceSnapshot` or equivalent artifact with hash, fetch time, sanitizer version, and trust classification.
3. Provider `url_context_metadata` is recorded as retrieval metadata, not as source truth.
4. Final claims cite TaskManagedAI snapshots, not transient provider context.
5. Missing or failed URL metadata produces `ungrounded` / `source_unverified`, not a silent pass.

## Custom Ranking / ClearBox Adaptation

The ClearBox custom-ranking sample is a reference for learning ranking formulas against a metric. TaskManagedAI should not depend on Vertex ranking backends in P0.

Adoptable pattern:

- represent ranking configuration as immutable `RankingPolicyVersion`;
- keep feature contribution explainable enough for review UI;
- evaluate against local gold sets with recall@k / precision@k / NDCG;
- require human review before a learned ranking policy becomes default.

Non-goals:

- no direct ClearBox / Vertex dependency in P0;
- no hidden provider ranking formula as the only explanation;
- no user-event feedback loop until consent, retention, and project boundary are designed.

## Grounding Caveats

- Provider grounding metadata is useful but optional; absence must be represented as `ungrounded`, not ignored.
- Provider citations are not enough. TaskManagedAI should verify source snapshots and evidence hash.
- Raw web/URL context should not be enabled until source snapshot, fetch policy, and project trust classification exist.
- Synthetic benchmark items require human validation before becoming acceptance fixtures.
- Batch prediction outputs are not evidence until input/output artifact refs, deletion policy, and job completion state are captured.
- Live API audio/video sessions are outside this evidence model until realtime retention and citation semantics are designed.
