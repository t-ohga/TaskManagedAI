# M-2 ダークモード 色分類 audit (ADR-00047 D-3 / plan-review R1 F-006)

frontend の **122 unique ハードコード色クラス / 690 occurrence / 70 file** をダーク対応した際の分類。
**不変条件: light モードの見た目を一切変えない**(token 置換は light hex 完全一致のみ、それ以外は `dark:`
variant を追加するのみ)。

## ① token 置換 (light hex 完全一致のみ)

| light class | → | 理由 |
|---|---|---|
| `bg-white` (#fff) | `bg-panel` | panel の light 値 = #fff で完全一致。dark で #192734。modifier 付き (`hover:bg-white`) も token swap で正 |

`text-gray-600` (#4b5563) ≠ `--tm-muted` (#657083)、`border-gray-200` ≠ `--tm-line` 等の **非一致は token
置換しない** (light regression を避ける、R1 F-003)。これらは ② で `dark:` variant を追加する。

## ② `dark:` variant 追加 (light 不変、modifier-aware)

`modifier:` prefix (`hover:` / `focus:` / `focus-visible:` / `group-hover:` / `disabled:` / `active:` 等)
が付く場合は **dark variant にも同じ prefix を引き継ぐ** (例: `hover:bg-slate-50` →
`hover:bg-slate-50 dark:hover:bg-slate-800`、`dark:` だけだと dark で常時適用になる、自己検出した bug)。

### 背景 surface (50/100 → 暗色 tinted)
`bg-{c}-50` → `+ dark:bg-{c}-950/40`、`bg-{c}-100` → `+ dark:bg-{c}-900/40`
(c = amber/emerald/rose/red/blue/indigo/teal/orange/purple/pink/green/cyan/yellow/sky)。`bg-sky-50` も同型。

### muted / neutral surface
`bg-slate-50`/`bg-slate-100` → `dark:bg-slate-800`、`bg-gray-100` → `dark:bg-gray-800`、`bg-gray-200` →
`dark:bg-gray-700`。

### colored text (600-900 → 明色)
`text-{c}-600` → `dark:text-{c}-400`、`text-{c}-700`/`-800` → `dark:text-{c}-300`、`text-{c}-900` →
`dark:text-{c}-200`。neutral: `text-gray-{500,600,700}` → `dark:text-gray-{400,300,300}`、
`text-slate-{400,600,700,800}` → `dark:text-slate-{500,400,300,200}`。

### border (200-400 → 暗色)
`border-{c}-200` → `dark:border-{c}-800`、`border-{c}-300`/`-400` → `dark:border-{c}-700`。

## ③ 維持 (dark 対応しない、意図的)

- **solid fill `bg-{c}-{400,500,600,700}`**: 鮮やかな塗り (バッジ・インジケータ)。両モードで視認可、
  上に `text-white` が乗る。維持。
- **`text-white`** (40×): 色付き fill (`bg-accent` 等) 上の文字。両モード白で正。維持。
- **`bg-black/40`** (overlay backdrop)、**`bg-teal-800`** (light モードで使う濃色アクセント面): 維持。

## ④ token surface (自動対応)

`bg-panel` / `bg-canvas` / `text-ink` / `text-muted` / `border-line` / `bg-accent` / shadcn の
`bg-card`/`bg-muted`/`border-border` 等は `globals.css` の `.dark` で token 値が暗色化するため **自動対応**
(クラス変更不要)。

## 印刷 (D-4 / R2 F-002)

`@media print { html.dark { 両 token family を light 値に再宣言 } }` + **`THEME_INIT_SCRIPT` の beforeprint
で `.dark` を一時除去** (token reset だけでは `dark:bg-amber-950/40` 等の utility variant が `.dark` 残存で
dark 印刷されるため、class 除去で token + utility 両方を light 印刷にする)。afterprint で復元。

## 検証

- `next build` 成功、frontend 410 vitest、typecheck、実 source lint clean。
- bg-X-50/100 surface の `dark:` 取りこぼし 0、二重 dark 0、modifier scope 正 (grep 確認)。
- **ブラウザ目視検証 (大神さん側) 必須**: 全画面 light/dark/system でコントラスト・崩れ・light 不変・印刷 light。
