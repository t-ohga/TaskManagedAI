---
id: "ADR-00047"
title: "ユーザー設定ページ + テーマ (ライト/ダーク/システム)、M-1/M-2/M-4"
status: "accepted"
date: "2026-06-04"
accepted_at: "2026-06-04"
deciders: ["t-ohga"]
adr_gate_criteria: [9]
related_adr:
  - "ADR-00035 (M-3 project settings 編集 / 設定ページの先例)"
  - "ADR-00045 (A-7 / dynamic rendering page の先例)"
related_dd:
  - "DD-00 (全体アーキテクチャ / Next.js frontend)"
related_sprints: []
supersedes: null
superseded_by: null
---

# ADR-00047: ユーザー設定ページ + テーマ (ライト/ダーク/システム)、M-1/M-2/M-4

最終更新: 2026-06-04

## 背景

UI 改善計画の **M 群「設定・テーマ」** は 4 件: M-1 ダークモード / M-2 ユーザー設定ページ /
M-3 設定ページ編集機能 (✅ ADR-00035 完了) / M-4 テーマ切替トグル。本 ADR は残る **M-1 + M-2 + M-4**
を 1 機能として完結させる。

**重要: 部分的なダークモードが既に存在する** (plan-review R1 F-002):

- `frontend/components/theme-toggle.tsx` (client) が **既存**。`localStorage` (key `theme`、値
  `light`/`dark`/`system`) を読み、`document.documentElement.classList` で `.dark` を add/remove する
  cycling button (☀/☾/⚙)。`frontend/components/navigation.tsx` が nav header で使用中。
- `globals.css` に **ダークモード token 完備**: `@custom-variant dark (&:is(.dark *))` + 8 `--tm-*` token +
  shadcn token、`:root` (light) + `.dark` (dark 値)。`html.dark { color-scheme: dark }`。

しかし現状は **未完成**: ① localStorage を `useEffect` で読むため **first paint 後に適用 → FOUC**
(再読込でライト→ダークのちらつき) ② **設定ページの明示的なテーマ選択 UI が無い** (cycling button のみ)
③ **token を使わないハードコード Tailwind 色 (122 unique class / 690 occurrence / 70 file)** が `.dark`
でも変わらず、ダークモードで多数画面が崩れる。

本 ADR は **既存ダークモードを完成させる** (重複実装しない、F-002): FOUC 解消 + 設定 UI + 全画面色対応。
**frontend のみ** (backend / DB / API / migration / cookie なし)。ハードコード色のアプリ全体対応が
70 file 横断のため **ADR Gate #9 (広範囲リファクタ)** に該当 (#1-#8/#10/#11 非該当)。

## 決定対象

### D-1. FOUC 解消 (localStorage + inline blocking script、server cookie 読込なし)

- テーマは引き続き **localStorage** (`theme`、既存 key を踏襲、cookie 化しない)。
- root layout (`app/layout.tsx`) の `<head>` に **inline blocking script** を注入する。script は
  first paint 前に同期実行され、`localStorage.theme` (無ければ `system`) を読み、`system` は
  `matchMedia('(prefers-color-scheme: dark)')` で解決して `document.documentElement.classList` に
  `.dark` を適用する。これで **再読込時の FOUC を解消** する。
- `<html>` に **`suppressHydrationWarning`** を付ける。inline script が hydration 前に class を変える
  ため、React の class 不一致警告を抑止する (server は class を制御せず、script が唯一の source。
  next-themes と同型)。
- **server は localStorage / cookie を読まない**ため root layout は **static のまま** (plan-review R1
  F-005: cookie 方式だと root が per-request dynamic 化し全 route を巻き込むのを回避)。

### D-2. テーマ機構の共通化 + 設定 UI (既存 toggle と状態共有)

- **`lib/theme.ts`** (新規、**hook なし pure module、`"use client"` 不要**): `Theme` 型、storage key、
  `resolveTheme(theme, prefersDark)`、`applyTheme(theme)` (classList、関数本体のみ browser API 参照)、
  `readStoredTheme()`、`THEME_INIT_SCRIPT` (inline script 文字列、固定・ユーザ入力なし)。**server の root
  layout が `THEME_INIT_SCRIPT` を import するため、hook / top-level browser API を置かない** (plan-review
  R2 F-001、A-6 F-C1 と同型の RSC 境界)。
- **`lib/use-theme.ts`** (新規、**`"use client"`**): `useTheme()` hook (state + 同一 tab 同期 = custom event
  `themechange` + 別 tab 同期 = `storage` event)。`lib/theme.ts` の pure helper を使う。Client Component
  (toggle / 設定 selector) のみが import し、既存 toggle と設定 selector が同 state を共有する。
- **`theme-toggle.tsx`** (既存を refactor): `useTheme` を使い localStorage 直接操作を共通化。a11y 改善
  (`aria-label` + 現在テーマの accessible name、F-010)。nav の compact button は維持。
- **設定ページ**: `settings/page.tsx` に **「外観 (この端末の表示設定)」section** を追加。project 設定とは
  **明確に区別** (device-local preference であり project scope でない旨を明示、F-008)。ライト/ダーク/
  システムの **3 択 radiogroup** (`useTheme` 共有、a11y: radiogroup + 各 option に accessible name +
  選択状態)。nav の cycling toggle を変えると設定 selector も即追従 (同 state)。

### D-3. ハードコード色のアプリ全体ダーク対応 (122 class / 690 箇所 / 70 file)

**light モードの見た目を一切変えずに** ダーク対応する (plan-review R1 F-003 厳格化):

- **構造色 → token 置換は light hex が完全一致するもののみ**: `bg-white` (#fff) → `bg-panel`
  (light #fff 一致 ✓)。**`text-gray-600` (#4b5563) ≠ `--tm-muted` (#657083)、`border-gray-200` ≠
  `--tm-line` 等の非一致は token 置換しない** (light regression を許さない)。
- **非一致の構造色 + muted surface (`bg-slate-50`/`bg-gray-100` 等) + semantic 色 (amber=warning /
  emerald=success / rose・red=error / blue・indigo=info / teal / orange / purple / sky 等のバッジ・通知)**:
  **`dark:` variant を追加** (light はそのまま、dark を足す。例: `bg-amber-50 dark:bg-amber-950/40
  text-amber-700 dark:text-amber-300`)。
- **意図的に light 固定すべき色** (`text-white` on `bg-accent` ボタン等): dark でも維持 (色付きボタンは
  両モードで同色)。
- **色分類 artifact (F-006)**: 122 unique class を ① token 置換 (light 一致) ② dark: variant 追加
  (構造非一致 / muted / semantic) ③ 維持 (text-white 等) ④ print 専用 に分類した一覧を
  `docs/設計検討/m2-color-audit.md` に作る。実装は分類に従い batch 化、各 batch 後に grep で残数を確認し
  drift を検知する。
- **不変条件**: 各変更は light の描画を変えない。dark の chip/badge は十分なコントラストを確保する。

### D-4. 印刷は常に light (F-004 + R2 F-002)

`@media print` で **`.dark` の全 token を light 値に戻す**。`globals.css` には **2 系統の token family** が
あり、両方を完全に light へ戻す (plan-review R2 F-002):

- **TaskManagedAI token**: `--tm-canvas/ink/muted/line/panel/accent/attention/danger`。
- **shadcn token**: `--background/foreground/card/card-foreground/popover/.../muted/border/input/ring/
  sidebar-*/chart-*/destructive` 等 (`components/ui/*` が `bg-card`/`bg-muted`/`border-border`/`bg-input/30`
  等で使用)。

`@media print { html.dark { /* 両 family の全変数を :root (light) と同値に再宣言 */ } }`。body だけの白背景
指定では token surface (`bg-panel` / `bg-card` 等) が dark のまま残り、既存 `print-color-adjust: exact` で
暗色が印刷されるため、print 時は両 family を light へ強制する。`html.dark { color-scheme: light }` も print
時に付ける。実装時に `.dark` の全変数を列挙して漏れなく light に戻す (片方の family だけ戻す実装ミスを防ぐ)。

## 前提 / 制約

- **frontend のみ。backend / DB / API / migration / cookie なし**。テーマは localStorage の device-local
  preference。secret は一切扱わない。
- **root layout は static のまま** (server cookie/localStorage 読込なし、F-005)。
- **no-FOUC + no hydration mismatch**: inline script が唯一の class source + `suppressHydrationWarning`。
- **light モード不変**: D-3 の全変更は light の見た目を変えない (token 置換は light 完全一致のみ)。
- **CSP (F-009)**: 現状 CSP 無し。将来 CSP を入れる場合 inline `THEME_INIT_SCRIPT` は nonce/hash が必要。
  script は固定文字列 (ユーザ入力埋め込みなし) のため hash-based CSP で許可可能。ADR に記録。
- **print は light** (D-4)。

## 選択肢

### テーマ永続化

- **(採用)** localStorage + inline blocking script (既存方式を踏襲)。server 読込不要で root が static の
  まま no-FOUC を実現。既存 toggle と統一。
- (却下) cookie + SSR 読込。root layout が per-request dynamic 化し全 route を巻き込む (F-005)。既存
  localStorage と二重化する (F-002)。device-local preference に server 読込は不要。
- (却下) backend (user_settings / actors.metadata)。migration + API、overkill。cross-device 同期が要れば別 ADR。

### "system" の解決

- **(採用)** inline script で matchMedia 解決 (first paint 前) + `useTheme` の matchMedia listener で OS 変更追従。

### ハードコード色

- **(採用)** light 完全一致のみ token 置換、それ以外は `dark:` variant 追加。light 不変。分類 artifact で網羅。
- (却下) 近似 token 置換。light regression を許す (F-003)。

## 採用案

D-1〜D-4 を採用。既存ダークモードを完成: localStorage + inline script で FOUC 解消、`useTheme` で
nav toggle と設定 selector を統一、設定ページに device-local テーマ 3 択、122 class を light 不変で
ダーク対応、print は light 強制。

## 却下案

- cookie / backend 永続化、theme-toggle 重複作成、近似 token 置換、テーマを project 設定に混在: いずれも
  却下 (上記)。

## リスク

| リスク | 対策 |
|---|---|
| FOUC | inline blocking script が first paint 前に localStorage + matchMedia で `.dark` 適用 |
| hydration mismatch (`<html>` class) | `suppressHydrationWarning` + script を唯一の class source に (server は class 非制御) |
| light regression (token 置換で色変化) | token 置換は light hex 完全一致のみ (F-003)。非一致は dark: 追加。next build + 目視 |
| nav toggle と設定 selector の状態不一致 | `useTheme` で同一 state 共有 (custom event 同 tab + storage event 別 tab) |
| dark で chip/badge コントラスト不足 | semantic dark variant は十分なコントラスト。ブラウザ目視 |
| 70 file の見落とし | 色分類 artifact + grep 残数確認 + ブラウザ全画面目視 (F-006) |
| dark surface が印刷に残る | print で `.dark` token を light へ強制 (D-4、F-004) |
| 将来 CSP で inline script block | script を固定文字列にし hash/nonce 対応可能と記録 (F-009) |

## rollback 手順

- **migration / cookie なし** → DB / cookie rollback 不要。
- コード rollback: PR revert で inline script + `lib/theme.ts` + toggle refactor + 設定 theme section +
  D-3 色変更 + D-4 print を戻す。既存 theme-toggle (localStorage) は本 ADR 以前から存在するため、revert で
  従来の FOUC ありダークモードに戻る (globals.css の `.dark` token は既存、削除しない)。

## 実装対象ファイル

**theme 機構**
- `frontend/lib/theme.ts` (新規、**hook なし pure**): 型 / key / resolve / apply / readStored /
  `THEME_INIT_SCRIPT` (server root layout が import、R2 F-001)。
- `frontend/lib/use-theme.ts` (新規、**`"use client"`**): `useTheme` hook (Client のみ import)。
- `frontend/app/layout.tsx`: `<html suppressHydrationWarning>` + `<head>` に `THEME_INIT_SCRIPT` 注入
  (`lib/theme.ts` から import)。server cookie/localStorage 読込なし (static 維持)。
- `frontend/components/theme-toggle.tsx` (既存 refactor): `useTheme` 利用 + a11y 改善。

**設定ページ**
- `frontend/app/(admin)/settings/page.tsx` (+ 必要なら新 `_components/appearance-settings.tsx`、client):
  「外観 (この端末の表示設定)」section + テーマ 3 択 radiogroup。

**色対応 (122 class / 70 file) + 分類 artifact**
- `docs/設計検討/m2-color-audit.md` (新規): 122 class 分類一覧。
- `frontend/app/**` + `frontend/components/**`: 分類に従い token 置換 (light 一致) + `dark:` variant 追加。
- `frontend/app/globals.css`: D-4 print で `.dark` token を light 強制。

## テスト指針

**frontend (vitest)**
- `lib/theme.ts`: `readStoredTheme` (light/dark/system/不正→system)、`resolveTheme` (system + prefersDark
  両分岐)、`applyTheme` (classList add/remove)、`THEME_INIT_SCRIPT` の健全性 (固定文字列・key 固定・XSS なし)、
  `useTheme` の event 同期。
- `theme-toggle.tsx`: cycling 遷移 (light→dark→system→light) / localStorage 書込 / classList / a11y
  (accessible name + 現在テーマ)。
- 設定 appearance section: 3 択 radiogroup 描画 / 選択で state + localStorage 更新 / 現在値反映 / nav toggle
  との同期。
- 既存 test regression なし (色変更は class のみ、role/label 不変)。

**build / 目視 (ブラウザ検証必須、`ブラウザ側検証依頼ルール` 準拠)**
- `next build` 成功 (RSC 境界、inline script の hydration、suppressHydrationWarning)。typecheck + lint clean。
- **ブラウザ目視検証 (大神さん側)**: 全主要画面 (ダッシュボード / チケット一覧・詳細・編集 / today /
  承認 / AgentRun / 監査 / 設定 / Eval / login) を light + dark + system で確認、**FOUC なし** (再読込で
  ちらつかない)、コントラスト十分、**light が従来と完全一致**、nav toggle と設定 selector の同期、印刷は
  light。検証手順は実装完了時に **一括で詳細提示** (小出し禁止)。

## レビュー記録

### codex-plan-review R1 (2026-06-04、Phase A、gpt-5.5 xhigh)

10 findings、**全 10 adopt**。主な設計変更:
- **F-002 (HIGH)**: theme-toggle.tsx が既存 (localStorage、nav 使用) と判明 → 重複作成せず **既存を
  refactor + localStorage 統一**。
- **F-001 + F-005 (HIGH/MEDIUM)**: cookie + SSR を取りやめ **localStorage + inline blocking script +
  `suppressHydrationWarning`** に変更。server 読込なしで root を static 維持、hydration mismatch 回避。
- **F-003 (HIGH)**: token 置換は **light hex 完全一致のみ** (gray-600≠tm-muted)。非一致は `dark:` variant。
- **F-004 (HIGH)**: print で `.dark` token を light へ強制 (D-4)。
- **F-006 (MEDIUM)**: 122 class の **色分類 artifact** (`m2-color-audit.md`) を作り網羅・drift 検知。
- **F-007 (MEDIUM)**: theme.ts / toggle / settings の unit test を追加 (resolution / event 同期)。
- **F-008 (MEDIUM)**: テーマを「この端末の表示設定」として project 設定と明確に区別。
- **F-009 (LOW)**: inline script の CSP nonce/hash 必要性を記録、固定文字列化。
- **F-010 (LOW)**: toggle / radiogroup の a11y (accessible name + 選択状態) を設計。

### codex-plan-review R2 (2026-06-04、Phase B 実コード突合、gpt-5.5 xhigh)

新規 2 HIGH、**全 2 adopt**:
- **F-001 (HIGH)**: `THEME_INIT_SCRIPT` (server root layout が import) と `useTheme()` hook (client 専用) を
  同 `lib/theme.ts` に置くと RSC 境界エラー (A-6 F-C1 同型) → **hook を `lib/use-theme.ts` (`"use client"`)
  に分離**、`lib/theme.ts` は hook なし pure に保つ。
- **F-002 (HIGH)**: `globals.css` は `--tm-*` と shadcn (`--background/card/muted/border/input/sidebar-*`等)
  の 2 token family に `.dark` 値を持つ。print で片方だけ light に戻すと `components/ui/*` が dark 印刷 →
  **D-4 で両 family の全 token を light へ再宣言**。

**Readiness Gate: READY** (R1+R2 で CRITICAL=0 / HIGH=0、全 12 findings adopt)。proposed → **accepted**
(2026-06-04)。

(実装後の adversarial-review / App review / ブラウザ検証の round はここに追記する)
