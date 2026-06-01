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
      />
    );
    // actor id は先頭 12 文字 + 省略記号で表示。
    expect(screen.getByText("human-actor-...")).toBeInTheDocument();
    expect(screen.getByText("セッション有効期限")).toBeInTheDocument();
    expect(screen.getByText("(あと約 3 時間 12 分)")).toBeInTheDocument();
    expect(screen.getByText("Tailscale 閉域")).toBeInTheDocument();
  });

  it("degrades to placeholders when session cannot be resolved", () => {
    render(<SessionInfo actorId={null} expiresAt={null} remainingLabel={null} />);
    // actor id / 有効期限とも null のとき em-dash を表示し、残り時間ラベルは出さない。
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/あと約/)).not.toBeInTheDocument();
  });

  it("omits the remaining label when only expiry is known", () => {
    render(
      <SessionInfo
        actorId="x"
        expiresAt="2026-06-01T18:30:00.000Z"
        remainingLabel={null}
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

  it("does not blanket-hide semantic header/form/button/input in print", () => {
    // display:none 対象セレクタに bare な header,/form,/button,/input, が無いこと。
    const hideSelectorLines = printBlock
      .split("\n")
      .filter((line) => !line.trim().startsWith("*")); // print-color-adjust の * は除外
    const joined = hideSelectorLines.join("\n");
    expect(joined).not.toMatch(/(^|\s)header\s*,/);
    expect(joined).not.toMatch(/(^|[,\s])form\s*[,{]/);
    expect(joined).not.toMatch(/(^|[,\s])button\s*[,{]/);
    expect(joined).not.toMatch(/(^|[,\s])input\s*[,{]/);
  });
});
