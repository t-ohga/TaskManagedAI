# OpenAI Realtime Agents サンプルの TaskManagedAI 適用検討

最終更新: 2026-05-14

対象サンプル: `/Users/tohga/sample/openai-realtime-agents`

## 結論

今回のサンプルは **TaskManagedAI にそのまま実装として取り込むものではなく、Realtime UX・会話オーケストレーション・イベント可視化・段階的 supervisor 活用の参考資料** として扱うのが妥当です。

再レビュー後の補正結論として、Realtime runtime は **text-only low-latency intake** と **STT -> ProviderAdapter -> TTS の chained voice pipeline** を先に比較し、明確な latency / task quality / cost / consent burden の優位が出る場合だけ P0.1 prototype に進めます。P0 runtime には入れません。

採用価値が高いのは、次の 5 つです。

1. **Chat-Supervisor pattern**: 低遅延の対話 UI と、既存の構造化 ProviderAdapter / supervisor 実行を分離する考え方。
2. **Sequential Handoff pattern**: specialist role を UI / orchestration 表現として扱う考え方。
3. **Sideband server control**: ブラウザ音声体験と server-side tool / policy / audit を分離する公式推奨に近い境界。
4. **Transcript + event log UI**: AgentRunEvent / AuditEvent / approval / cost をユーザーが追える UI の参考。
5. **Realtime adoption gate pattern**: client secret minting、sideband、Provider Matrix、BudgetGuard、retention を分けて止める考え方。

一方で、次は TaskManagedAI では **採用不可または延期** です。

- ブラウザ側で tool / business logic / session update を直接握る構成。
- `/api/responses` のような任意 body proxy。
- SecretBroker を経由しない `OPENAI_API_KEY` 利用。
- Realtime output guardrail を TaskManagedAI Output Validator の代替にすること。
- Realtime MCP tool をそのまま mutating tool 実行経路にすること。
- Tool/MCP gateway を経由しない Realtime MCP の直接実行。
- `gpt-realtime-2` / Realtime を structured-output ProviderAdapter の置換にすること。

## 文書一覧

- [00_source_inventory.md](00_source_inventory.md): 調査対象、サンプルの構成、公式仕様、TaskManagedAI 側の前提。
- [01_reusable_patterns.md](01_reusable_patterns.md): 使えそうな機能・実装候補・採用判断。
- [02_invariant_traceability.md](02_invariant_traceability.md): TaskManagedAI の不変条件、必須ゲート、Realtime event mapping。
- [03_adoption_plan.md](03_adoption_plan.md): 今後の段階的ロードマップ。
- [04_risks_and_deferred_items.md](04_risks_and_deferred_items.md): リスク、延期・却下項目、未決事項。
- [05_deepcheck_recommendations.md](05_deepcheck_recommendations.md): 再深掘りレビューで見つけた改善方針、InteractionGateway、unified `/v1/realtime/calls` 優先化。
- [06_eval_fixture_plan.md](06_eval_fixture_plan.md): text-only / chained voice / Realtime sideband を比較する eval fixture 計画。

## 使い方

今後 Realtime 連携を検討する場合は、まず `02_invariant_traceability.md` の gate を満たせるか確認してください。特に Provider Compliance Matrix、SecretBroker、Sideband server control、Output Validator、データ保持、予算制御、Tailscale/Origin/CSRF 境界を満たせない段階では、実装に進めない判断が安全です。

実装前には、公式 OpenAI docs の current endpoint / model / data controls を再確認してください。このサンプルの接続コードは historical demo reference として扱い、現時点の WebRTC / client secret / calls / sideband docs から TaskManagedAI 向けに再設計します。
