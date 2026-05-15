# 修正まとめ

作成日: 2026-05-14

## 目的

このディレクトリは、次の3系統の重要文書 26 ファイルを統合し、TaskManagedAI を今後どう修正するべきかを実装判断に使える形でまとめたものです。

- `docs/設計検討/geminigithubから/`
- `docs/設計検討/openairealtimegithubから/`
- `docs/設計検討/設計問題点改善点/`

このまとめは、Google Gemini / Google Cloud sample、OpenAI Realtime Agents sample、TaskManagedAI 自身の設計問題点レビューを直接混ぜるのではなく、TaskManagedAI の既存 invariant に合わせて採否を再整理します。

## 統合結論

TaskManagedAI が先に直すべきことは、外部 AI sample の便利機能を増やすことではありません。P0 の false-positive 完了を防ぎ、Deep Research から Draft PR までの証拠付き gold flow、日次運用 UI、品質ループ artifact、Policy / Approval / Provider / Runner / SecretBroker gate、CLI ContextResolver を先に閉じるべきです。

Gemini / OpenAI Realtime から採用するのは pattern であり、runtime の丸ごと移植ではありません。Provider-managed code execution、computer use、URL context、Realtime MCP direct execution、browser-side business logic、unrestricted proxy、raw payload logging、audio recording default on は、gate が揃うまで採用しません。

## 読み順

1. [00_統合修正方針.md](./00_統合修正方針.md)
   - 3系統の文書を統合した基本方針と、採用/延期/却下の大原則。
2. [01_P0優先修正ロードマップ.md](./01_P0優先修正ロードマップ.md)
   - 次にどの Sprint Pack / ADR / 基本設計をどの順で直すべきか。
3. [02_領域別改善案.md](./02_領域別改善案.md)
   - Product、UI、Quality Loop、Autonomy、CLI、Provider、Evidence、Realtime、Gemini feature の領域別修正案。
4. [03_ゲートと非採用項目.md](./03_ゲートと非採用項目.md)
   - 実装前に止める条件、defer / reject、provider feature gate、rollback。
5. [04_出典トレースマトリクス.md](./04_出典トレースマトリクス.md)
   - 入力26ファイルがどこへ反映されたかを追うための見落とし防止表。
6. [05_次に編集する正本ファイル案.md](./05_次に編集する正本ファイル案.md)
   - 実際に次の Quality Loop / Sprint Pack 修正で触る正本候補と acceptance。
7. [06_検証基準.md](./06_検証基準.md)
   - 統合成果物が十分か、上流修正に進めるかを判定する確認手順。
8. [07_矛盾と正本優先順位.md](./07_矛盾と正本優先順位.md)
   - `BL-*`、action_class、no-approval、CLI 名、Realtime/Gemini 採否など、衝突しやすい前提の優先順位。
9. [08_実装担当引き継ぎ.md](./08_実装担当引き継ぎ.md)
   - 他の実装担当者へ渡すときの読み順、最初の run、禁止範囲、完了条件。

## 扱い

- このディレクトリの文書は、次の設計修正 Quality Loop の入力です。
- ここに書いたことだけで provider / Realtime / Gemini managed feature の利用許可にはなりません。
- 実装に入る場合は、該当 ADR、Sprint Pack、Provider Compliance Matrix、基本設計、Eval fixture、negative test へ落とし込みます。
- 他の実装担当者に渡す場合は、まず `08_実装担当引き継ぎ.md` から開始してください。
