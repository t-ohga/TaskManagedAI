# keyring framework intake (ADR-00020 §1 8-verify、SP-PHASE0 / PLAN-10 Phase 0)

`keyring` (PyPI) を `LocalSecretStore` (ADR-00058、Phase 0 default secret backend) の OS keychain backend として
dependency 採用したことの supply-chain intake evidence。ADR-00020 (Framework Intake Checklist) の 8-verify を
**非AI foundational dependency** として適用する (keyring は `dependency_to_framework_map.json` で
`OS Keyring / Secret Storage (non-AI)` 分類、`cryptography` と同列の基盤 lib)。

## dependency 基本情報

| 項目 | 値 |
|---|---|
| package | `keyring` (PyPI) |
| version | 25.7.0 (intake 時、`pyproject.toml` / `uv.lock` に pin) |
| license | **MIT** (`License-Expression: MIT`、source: https://github.com/jaraco/keyring) |
| maintainer | jaraco (Jason R. Coombs) ほか、Python community 長期保守 |
| 用途 | macOS Keychain / Secret Service 経由の secret material 保存 (`LocalSecretStore`、keyring 不在環境は cryptography Fernet 暗号化ファイルに fallback) |
| AI 関連性 | **non-AI** (OS keychain wrapper、AI framework ではない) |

## ADR-00020 §1 8-verify (keyring 適用)

| # | verify | keyring 判定 | 根拠 |
|---|---|---|---|
| 1 | License | ✅ PASS | MIT (denylist = Polyform/RUS/SSPL に非該当) |
| 2 | Attribution | ✅ PASS | `dependency_to_framework_map.json` + `framework_pattern_candidates.md` + 本 file に記録 |
| 3 | No code embed | ✅ N/A (非AI exception) | item 3 の「from-scratch 再実装のみ、`import` denylist」は **AI framework 大規模コード embed 防止**が趣旨。keyring は OS keychain への薄い wrapper の **foundational dependency** (cryptography と同様、`import keyring` が正規利用)。embed/再実装の対象ではない |
| 4 | Persistence | ✅ PASS | 独自 SQLite / PostgreSQL を持ち込まない。secret は **OS keychain** (macOS Keychain) に格納、fallback は repo 内 Fernet 暗号化ファイル (TaskManagedAI 既存 DB に raw secret を入れない、ADR-00058/00059) |
| 5 | External network | ✅ PASS | keyring は **local OS keychain** とのみ通信、external API endpoint なし (NETWORK_DENYLIST に非該当) |
| 6 | Telemetry off | ✅ PASS | telemetry なし (sentry/datadog 等を import しない) |
| 7 | Secret canary scan | ✅ PASS | keyring 自体は secret store。material は `LocalSecretStore` 境界で material lifecycle (writing/present/purging/purged) + broker の canary/redaction 経路を通る (S1)。raw secret は DB/log/artifact/audit に出さない (assert_no_raw_secret、S4 DB-gated test で検証) |
| 8 | tenant/project boundary | ✅ PASS | material key = `tenant_id + secret_ref_id` 束縛 (cross-tenant material identity test、S4 DB-gated) |

## intake 結論

keyring は **非AI foundational dependency** として 8-verify を満たす (item 3 は AI-embed 防止趣旨のため非該当)。
license MIT / telemetry なし / external network なし / local OS keychain のみ / secret 境界は broker + LocalSecretStore で
担保。supply-chain risk は LOW。

## ADR-00020 (generic checklist) との関係

ADR-00020 (Framework Intake Checklist) 本体は `status: proposed` で、`acceptance_blocked_by:
["ADR-00014/16 accepted", "P0 完了"]` を持つ。**ADR-00016 (Hermes agent integration) が現在 proposed のため
accept できない** (P0 完了 と ADR-00014 は充足済だが、ADR-00016 が未充足)。keyring (非AI MIT 基盤 lib) の intake を
無関係な AI-agent ADR でブロックするのは不合理なため、本 file で **keyring 固有の intake evidence を直接記録**する
(ADR-00020 §1 checklist を非AI lib として適用)。これは当初 completion gate (ADR-00020 §12.4 accept) からの **scope 変更**
であり、scope 変更の承認 (または ADR-00020 への非AI carve-out 正式追記) は user 判断事項。generic ADR-00020 の
accept は AI framework 取り込み track の別 governance 事項として proposed のまま残す。
