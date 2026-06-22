import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmergencyStopPanel } from "../app/(admin)/settings/_components/emergency-stop-panel";

// Server Action は vitest では実行しないため no-op に mock (useActionState 経由で参照)。
vi.mock("../app/(admin)/settings/emergency-stop-actions", () => ({
  engageEmergencyStopAction: vi.fn(async () => ({ kind: "idle" })),
  clearEmergencyStopAction: vi.fn(async () => ({ kind: "idle" })),
  engageGlobalKillSwitchAction: vi.fn(async () => ({ kind: "idle" })),
  clearGlobalKillSwitchAction: vi.fn(async () => ({ kind: "idle" }))
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() })
}));

afterEach(() => {
  vi.clearAllMocks();
});

describe("EmergencyStopPanel (SP-PHASE1 B6 / ADR-00048)", () => {
  it("shows a 稼働中 badge and an engage control when the latch is not engaged", () => {
    render(
      <EmergencyStopPanel
        latch={{ engaged: false, generation: null, engagedAt: null }}
        budgetKillSwitch={{ engaged: false }}
      />
    );
    expect(screen.getAllByText("稼働中").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: "全 AI を緊急停止する" })
    ).toBeInTheDocument();
    // engaged でないので解除ボタンは出ない。
    expect(
      screen.queryByRole("button", { name: "緊急停止を解除する" })
    ).not.toBeInTheDocument();
  });

  it("shows a 停止中 badge, generation, and a clear control when engaged", () => {
    render(
      <EmergencyStopPanel
        latch={{ engaged: true, generation: 3, engagedAt: "2026-06-22T00:00:00+00:00" }}
        budgetKillSwitch={{ engaged: false }}
      />
    );
    expect(screen.getAllByText("停止中").length).toBeGreaterThan(0);
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "緊急停止を解除する" })
    ).toBeInTheDocument();
    // engaged 中は engage 導線を出さない。
    expect(
      screen.queryByRole("button", { name: "全 AI を緊急停止する" })
    ).not.toBeInTheDocument();
  });

  it("requires a second confirmation step before engaging (two-stage, no JS confirm)", () => {
    render(
      <EmergencyStopPanel
        latch={{ engaged: false, generation: null, engagedAt: null }}
        budgetKillSwitch={{ engaged: false }}
      />
    );
    expect(
      screen.queryByRole("button", { name: "緊急停止を確定" })
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全 AI を緊急停止する" }));
    expect(
      screen.getByRole("button", { name: "緊急停止を確定" })
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "キャンセル" })).toBeInTheDocument();
  });

  it("submits the active generation as the clear CAS baseline (hidden field)", () => {
    const { container } = render(
      <EmergencyStopPanel
        latch={{ engaged: true, generation: 7, engagedAt: null }}
        budgetKillSwitch={{ engaged: false }}
      />
    );
    const hidden = container.querySelector<HTMLInputElement>(
      'input[name="expected_generation"]'
    );
    expect(hidden).not.toBeNull();
    expect(hidden?.value).toBe("7");
  });

  it("renders a fail-closed notice instead of controls when status is unavailable", () => {
    render(<EmergencyStopPanel latch={null} budgetKillSwitch={null} />);
    // latch notice (先頭が「緊急停止」) と budget notice (先頭が「コスト緊急停止」) を別々に検証。
    expect(
      screen.getByText(/^緊急停止の状態を読み込めませんでした/u)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/^コスト緊急停止の状態を読み込めませんでした/u)
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "全 AI を緊急停止する" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "コスト緊急停止を有効にする" })
    ).not.toBeInTheDocument();
  });

  it("shows a clear control for the budget kill switch when engaged", () => {
    render(
      <EmergencyStopPanel
        latch={{ engaged: false, generation: null, engagedAt: null }}
        budgetKillSwitch={{ engaged: true }}
      />
    );
    expect(
      screen.getByRole("button", { name: "コスト緊急停止を解除する" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "コスト緊急停止を有効にする" })
    ).not.toBeInTheDocument();
  });
});
