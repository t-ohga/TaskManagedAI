// P-2 機能ツアー: 依存ゼロ自前実装の client-safe pure module。
// hook / top-level browser API は置かない (component 側が "use client" で使う)。
// 永続化は localStorage (device-local、cookie 化しない)。M-2 (lib/theme.ts) と同じ
// SecurityError-safe アクセサ pattern を踏襲する (localStorage プロパティ取得自体が throw し得る)。

import type { Route } from "next";

export type TourStep = {
  readonly id: string;
  readonly icon: string;
  readonly title: string;
  readonly description: string;
  readonly href: Route;
};

// content を変えたら bump して既存ユーザーに再表示する (完了 flag は version 一致で判定)。
export const TOUR_VERSION = "1";
export const TOUR_STORAGE_KEY = "taskmanagedai.feature-tour.completed";

export const TOUR_STEPS: readonly TourStep[] = [
  {
    id: "dashboard",
    icon: "📊",
    title: "ダッシュボード",
    description:
      "プロジェクト全体の状況、KPI、最近の AI 実行をひと目で把握できます。まずはここから。",
    href: "/dashboard"
  },
  {
    id: "tickets",
    icon: "🎫",
    title: "チケット",
    description:
      "タスクを作成・管理します。受け入れ条件・証拠・AI 実行をチケット単位で追跡できます。",
    href: "/tickets"
  },
  {
    id: "runs",
    icon: "🤖",
    title: "AI 実行",
    description:
      "AI エージェントの実行を管理します。16 の状態と実行ログ・コストを再現可能な形で記録します。",
    href: "/runs"
  },
  {
    id: "approvals",
    icon: "✅",
    title: "承認待ち",
    description:
      "AI が作成した変更案を人間が承認します。承認なしに破壊的操作は実行されません。",
    href: "/approvals"
  },
  {
    id: "research",
    icon: "🔎",
    title: "リサーチ",
    description:
      "Deep Research の主張・証拠を管理します。矛盾グループや証拠ドメインの信頼度も確認できます。",
    href: "/research"
  },
  {
    id: "domain-trust",
    icon: "🛡️",
    title: "ドメイン信頼度",
    description:
      "証拠の出典ドメインに信頼度 (低/中/高) を登録します。リサーチ詳細でバッジとして表示されます。",
    href: "/domain-trust"
  },
  {
    id: "eval-dashboard",
    icon: "📈",
    title: "評価ダッシュボード",
    description:
      "Hard Gates と Quality KPI の達成状況を確認します。数値は fixture / dataset version まで辿れます。",
    href: "/eval-dashboard"
  },
  {
    id: "audit",
    icon: "📜",
    title: "監査ログ",
    description:
      "すべての重要操作が追記専用で記録されます。秘密情報は値ではなくパターンとして扱われます。",
    href: "/audit"
  },
  {
    id: "settings",
    icon: "⚙️",
    title: "設定",
    description:
      "プロバイダー設定や AI 自律レベル、表示テーマを調整します。ツアーはいつでもナビから再表示できます。",
    href: "/settings"
  }
];

/** localStorage から完了状態を読む (version 一致のときだけ true)。SecurityError-safe。 */
export function readTourCompleted(): boolean {
  try {
    // localStorage **プロパティ取得自体** が SecurityError を投げ得る (storage がポリシーで拒否)。
    // typeof チェックを try 外に置くと mount 時に例外が漏れて admin UI を壊す (M-2 Codex F-G7)。
    // SSR (Node) では globalThis.localStorage が undefined になり throw しない。
    const storage = globalThis.localStorage;
    if (!storage) return false;
    return storage.getItem(TOUR_STORAGE_KEY) === TOUR_VERSION;
  } catch {
    // storage 失敗時は「未完了」扱いだが、session guard (component 側) が同一 session 内の再表示を防ぐ。
    return false;
  }
}

/** 完了をマークする (失敗は無視)。SecurityError-safe。 */
export function markTourCompleted(): void {
  try {
    const storage = globalThis.localStorage;
    if (!storage) return;
    storage.setItem(TOUR_STORAGE_KEY, TOUR_VERSION);
  } catch {
    // storage 書込不可 (private mode 等) でも UI は壊さない。session guard で再表示は抑制される。
  }
}

/** 0-indexed step から進捗ラベル (例: "3 / 9")。 */
export function progressLabel(index: number): string {
  return `${index + 1} / ${TOUR_STEPS.length}`;
}
