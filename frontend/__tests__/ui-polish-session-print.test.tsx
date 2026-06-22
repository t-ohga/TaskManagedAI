import { readFileSync } from "node:fs";
import { join } from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PrintButton } from "../components/print-button";
import { SessionInfo } from "../components/session-info";

describe("SessionInfo (R-1 セッションタイムアウト表示)", () => {
  it("renders actor id, expiry datetime and remaining label when session is present", () => {
    render(
      <SessionInfo
        actorId="human-actor-abcdef-0123456789"
        expiresAt="2026-06-01T18:30:00.000Z"
        remainingLabel="あと約 3 時間 12 分"
        lastLoginAt="2026-06-01T06:30:00.000Z"
      />
    );
    // actor id は先頭 12 文字 + 省略記号で表示。
    expect(screen.getByText("human-actor-...")).toBeInTheDocument();
    expect(screen.getByText("セッション有効期限")).toBeInTheDocument();
    expect(screen.getByText("(あと約 3 時間 12 分)")).toBeInTheDocument();
    expect(screen.getByText("Tailscale 閉域")).toBeInTheDocument();
    // R-2: 最終ログイン日時の行が出る。
    expect(screen.getByText("最終ログイン日時")).toBeInTheDocument();
  });

  it("degrades to placeholders when session cannot be resolved", () => {
    render(
      <SessionInfo
        actorId={null}
        expiresAt={null}
        remainingLabel={null}
        lastLoginAt={null}
      />
    );
    // actor id / 有効期限 / 最終ログインとも null のとき em-dash を表示し、残り時間ラベルは出さない。
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText(/あと約/)).not.toBeInTheDocument();
  });

  it("omits the remaining label when only expiry is known", () => {
    render(
      <SessionInfo
        actorId="x"
        expiresAt="2026-06-01T18:30:00.000Z"
        remainingLabel={null}
        lastLoginAt={null}
      />
    );
    expect(screen.queryByText(/あと約|期限切れ/)).not.toBeInTheDocument();
  });
});

describe("PrintButton (S-1 チケット印刷ビュー)", () => {
  it("invokes window.print on click and is excluded from print via .no-print", () => {
    const printSpy = vi.fn();
    vi.stubGlobal("print", printSpy);

    render(<PrintButton label="印刷" />);
    const button = screen.getByRole("button", { name: "印刷" });
    // 印刷ボタン自体は印刷物に出さない (.no-print)。
    expect(button.className).toContain("no-print");

    fireEvent.click(button);
    expect(printSpy).toHaveBeenCalledTimes(1);

    vi.unstubAllGlobals();
  });
});

describe("print CSS scope (Codex adversarial R1 F-MEDIUM regression guard)", () => {
  // @media print が generic な header/form/button を一律 display:none すると、意味を持つ
  // コンテンツ (チケットタイトルの <header>、設定フォームの現在値) まで消える。非表示は
  // 明示クラス (.no-print) とランドマークに限定されていることを CSS 内容で固定する。
  const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
  const printBlock = (() => {
    const start = css.indexOf("@media print");
    expect(start).toBeGreaterThanOrEqual(0);
    // 対応する閉じ括弧までを粗く抽出 (次の "@media" / "@theme" / EOF まで)。
    const rest = css.slice(start + "@media print".length);
    const nextAt = rest.search(/@media|@theme|@layer/);
    return nextAt >= 0 ? rest.slice(0, nextAt) : rest;
  })();

  it("hides explicit chrome (.no-print) in print", () => {
    expect(printBlock).toContain(".no-print");
  });

  it("does not blanket-hide semantic landmarks/controls in print", () => {
    // display:none 対象セレクタに bare な header/form/button/input/footer/aside/nav が無いこと
    // (これらは意味コンテンツ = チケットタイトル / 設定フォーム値 / 承認 aside 判定メタデータ等を含む)。
    const hideSelectorLines = printBlock
      .split("\n")
      .filter((line) => !line.trim().startsWith("*")); // print-color-adjust の * は除外
    const joined = hideSelectorLines.join("\n");
    for (const bare of ["header", "form", "button", "input", "footer", "aside", "nav"]) {
      expect(joined).not.toMatch(new RegExp(`(^|[,\\s])${bare}\\s*[,{]`, "m"));
    }
  });
});

describe("approvals print scope (Codex adversarial R3 F-MEDIUM regression guard)", () => {
  // print hide を .no-print 限定にしたため、各操作フォームは個別に .no-print が必要。
  // 承認詳細は「判定者/判定日時/理由 (判定メタデータ) は印刷に残るが、pending の判定/修正依頼
  // フォームは印刷物から消える」ことを source 構造で固定する (パケット/監査出力に操作 UI を混ぜない)。
  // Codex auto-review P2 fix で操作 form は ApprovalPendingActions (sibling 協調 wrapper) に分離。
  // .no-print container は wrapper 側に移ったため、page は委譲のみを検証する。
  const src = readFileSync(
    join(process.cwd(), "app/(admin)/approvals/[id]/page.tsx"),
    "utf8"
  );
  const wrapperSrc = readFileSync(
    join(process.cwd(), "app/(admin)/approvals/[id]/_components/approval-pending-actions.tsx"),
    "utf8"
  );

  it("keeps decision metadata printable and delegates pending forms to the no-print wrapper", () => {
    // 判定メタデータの DetailRow (判定者) は印刷対象。操作 form 本体 (ApprovalDecideForm) を
    // page に直接置かず ApprovalPendingActions へ委譲する (印刷除外を wrapper の .no-print に集約)。
    const metaIndex = src.indexOf('label="判定者"');
    // import 文ではなく JSX 描画位置 (<ApprovalPendingActions) で順序を見る。
    const actionsIndex = src.indexOf("<ApprovalPendingActions");
    expect(metaIndex).toBeGreaterThanOrEqual(0);
    expect(actionsIndex).toBeGreaterThanOrEqual(0);
    expect(metaIndex).toBeLessThan(actionsIndex);
    // page に操作 form 本体を直接描画しない (no-print の外に漏らさない)。
    expect(src).not.toContain("<ApprovalDecideForm");
    expect(src).not.toContain("<ApprovalRevisionRequestForm");
  });

  it("wraps the pending decision/revision forms in a .no-print container", () => {
    // pending branch の操作フォームは ApprovalPendingActions 内の no-print の div に置かれる。
    const wrapStart = wrapperSrc.indexOf('className="no-print grid gap-4"');
    expect(wrapStart).toBeGreaterThanOrEqual(0);
    const wrapEnd = wrapperSrc.indexOf("</div>", wrapStart);
    const wrapped = wrapperSrc.slice(wrapStart, wrapEnd);
    expect(wrapped).toContain("ApprovalDecideForm");
    expect(wrapped).toContain("ApprovalRevisionRequestForm");
  });
});

describe("I-3 inline anchor tap targets (Codex adversarial R2/R4 regression guard)", () => {
  // inline 非置換 <a> は min-height/width が効かないため、操作 anchor (filter chip / pagination)
  // は inline-flex 化して coarse pointer の 44px が効くようにする。runs だけでなく audit の
  // event-type filter anchor も対象 (R4 F-MEDIUM)。
  it("runs filter chips and pagination anchors are inline-flex", () => {
    const runs = readFileSync(join(process.cwd(), "app/(admin)/runs/page.tsx"), "utf8");
    expect(runs).toContain("inline-flex items-center justify-center rounded-full px-3 py-1");
    expect(runs).toContain(
      "inline-flex items-center justify-center rounded border border-line px-3 py-1"
    );
  });

  it("audit filter chips and pagination anchors are inline-flex", () => {
    const audit = readFileSync(join(process.cwd(), "app/(admin)/audit/page.tsx"), "utf8");
    expect(audit).toContain(
      "inline-flex items-center justify-center rounded-full px-3 py-1 text-xs font-medium transition-colors"
    );
    expect(audit).toContain(
      "inline-flex items-center justify-center rounded border border-line px-3 py-1"
    );
  });
});

describe("settings print scope (Codex adversarial R4 F-MEDIUM regression guard)", () => {
  // 設定スナップショット / 監査出力には現在値を残し、操作 UI (保存ボタン / データ管理の破壊的操作)
  // は印刷物に出さない。
  // 操作 UI (破壊的データ管理 / 緊急停止 kill switch) は印刷物に出さない。各 .no-print ブロックが
  // 当該 Panel を直後に含むことを検証する (複数の .no-print ブロックが存在するため、最初の 1 つだけを
  // 見るのではなく対象 Panel ごとに wrapping を確認する)。
  function assertWrappedInNoPrint(page: string, marker: string): void {
    const markerAt = page.indexOf(marker);
    expect(markerAt).toBeGreaterThanOrEqual(0);
    // marker の直前に現れる最も近い .no-print 開始タグを探す。
    const noPrintBefore = page.lastIndexOf('<div className="no-print">', markerAt);
    expect(noPrintBefore).toBeGreaterThanOrEqual(0);
    // その .no-print と marker の間に別の .no-print 開始が割り込んでいないこと (= marker が当該
    // .no-print ブロックに属する)。
    const intervening = page.indexOf(
      '<div className="no-print">',
      noPrintBefore + 1
    );
    expect(intervening === -1 || intervening > markerAt).toBe(true);
  }

  it("wraps the destructive DataManagementPanel in .no-print", () => {
    const page = readFileSync(join(process.cwd(), "app/(admin)/settings/page.tsx"), "utf8");
    assertWrappedInNoPrint(page, "<DataManagementPanel");
  });

  it("wraps the EmergencyStopPanel (kill switch operator UI) in .no-print", () => {
    const page = readFileSync(join(process.cwd(), "app/(admin)/settings/page.tsx"), "utf8");
    assertWrappedInNoPrint(page, "<EmergencyStopPanel");
  });

  it("marks every project settings save button .no-print", () => {
    const form = readFileSync(
      join(process.cwd(), "app/(admin)/settings/_components/project-settings-form.tsx"),
      "utf8"
    );
    // フォーム内の submit ボタンはすべて no-print の div 内に置かれる (基本情報 + 自律レベル)。
    const submitCount = form.split('type="submit"').length - 1;
    expect(submitCount).toBeGreaterThanOrEqual(2);
    for (const label of ["基本情報を保存", "自律レベルを保存"]) {
      const labelIndex = form.indexOf(label);
      expect(labelIndex).toBeGreaterThanOrEqual(0);
      // ボタン直前 (button の長い className を跨ぐため ~400 字) に no-print wrapper があること。
      const before = form.slice(Math.max(0, labelIndex - 400), labelIndex);
      expect(before).toContain('className="no-print"');
    }
  });
});

describe("list page print scope (Codex adversarial R5 F-MEDIUM regression guard)", () => {
  // 監査ログ / AI 実行ログは一覧 (証跡) としての印刷価値があるため、テーブル本体は印刷に残し、
  // フィルタ / ページネーションの操作子は .no-print で印刷から除外する。
  it("audit filter bar and pagination are .no-print", () => {
    const audit = readFileSync(join(process.cwd(), "app/(admin)/audit/page.tsx"), "utf8");
    expect(audit).toContain("no-print flex flex-wrap items-center gap-3");
    expect(audit).toMatch(/aria-label="ページネーション"\s+className="no-print/);
  });

  it("runs filter bar and pagination are .no-print", () => {
    const runs = readFileSync(join(process.cwd(), "app/(admin)/runs/page.tsx"), "utf8");
    expect(runs).toContain("no-print flex flex-wrap items-center gap-3");
    expect(runs).toMatch(/aria-label="ページネーション"\s+className="no-print/);
  });

  it("approvals inbox status filter and per-row review link are .no-print", () => {
    const inbox = readFileSync(join(process.cwd(), "app/(admin)/approvals/page.tsx"), "utf8");
    // ステータス絞り込み nav は印刷除外。
    expect(inbox).toMatch(/aria-label="承認ステータス"\s+className="no-print/);
    // 各 row の「レビュー」リンクは印刷除外 (承認メタデータは印刷に残す)。
    const reviewIndex = inbox.indexOf("レビュー");
    expect(reviewIndex).toBeGreaterThanOrEqual(0);
    const before = inbox.slice(Math.max(0, reviewIndex - 400), reviewIndex);
    expect(before).toContain('className="no-print');
  });

  it("audit and runs keep a print-only active-filter summary (Codex App P2)", () => {
    // フィルタ操作子を印刷で隠す代わりに、有効フィルタ + ページを print-only サマリで残し、
    // 印刷された証跡が「全件 / 全ログ」に誤読されないようにする。
    const audit = readFileSync(join(process.cwd(), "app/(admin)/audit/page.tsx"), "utf8");
    expect(audit).toMatch(/className="print-only[^"]*"[\s\S]{0,80}フィルタ/);
    const runs = readFileSync(join(process.cwd(), "app/(admin)/runs/page.tsx"), "utf8");
    expect(runs).toMatch(/className="print-only[^"]*"[\s\S]{0,80}フィルタ/);
  });

  it("globals.css defines a .print-only utility shown only in print", () => {
    const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
    // 既定で非表示。
    expect(css).toMatch(/\.print-only\s*\{\s*display:\s*none/);
    // @media print 内で表示。
    const printStart = css.indexOf("@media print");
    const printBlock = css.slice(printStart, printStart + 600);
    expect(printBlock).toMatch(/\.print-only\s*\{\s*display:\s*block/);
  });
});
