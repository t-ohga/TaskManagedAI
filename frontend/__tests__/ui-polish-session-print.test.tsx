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
