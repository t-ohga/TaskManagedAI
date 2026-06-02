import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SelectableTicketList } from "@/components/selectable-ticket-list";

// BulkStatusChanger (= 一括 mutation 境界、updateTicketAction を全 selectedIds に適用する)
// が受け取る selectedIds を捕捉して、隠れたチケット ID が境界へ渡らないことを検証する。
const captured: { selectedIds: string[] } = { selectedIds: [] };
vi.mock("@/components/bulk-status-changer", () => ({
  BulkStatusChanger: ({ selectedIds }: { selectedIds: string[] }) => {
    captured.selectedIds = selectedIds;
    return <div data-testid="bulk-boundary">{selectedIds.length} 件</div>;
  }
}));

function ticket(id: string, title: string) {
  return {
    id,
    title,
    status: "open",
    priority: null,
    projectSlug: "taskmanagedai",
    due_date: null,
    created_at: null,
    tags: []
  };
}

beforeEach(() => {
  captured.selectedIds = [];
});

describe("SelectableTicketList", () => {
  it("never passes hidden (filtered-out) ticket IDs to the bulk mutation boundary", () => {
    const { rerender } = render(
      <SelectableTicketList tickets={[ticket("a", "チケットA"), ticket("b", "チケットB")]} showProjectBadge={false} />
    );

    // 両方のチケットを選択する。
    fireEvent.click(screen.getByLabelText("チケットA を選択"));
    fireEvent.click(screen.getByLabelText("チケットB を選択"));
    expect([...captured.selectedIds].sort()).toEqual(["a", "b"]);

    // フィルタ / プロジェクト切替で B が一覧から消える。App Router は client component の
    // selection state を保持したまま新しい tickets prop を渡す。
    rerender(<SelectableTicketList tickets={[ticket("a", "チケットA")]} showProjectBadge={false} />);

    // mutation 境界には表示中の a のみが渡り、隠れた b は渡らない (derive-during-render で
    // effect prune 前の最初の render race を排除)。
    expect(captured.selectedIds).toEqual(["a"]);
    expect(captured.selectedIds).not.toContain("b");
  });

  it("does not let a hidden selection re-enter the boundary after hide → uncheck → re-show", () => {
    const { rerender } = render(
      <SelectableTicketList tickets={[ticket("a", "チケットA"), ticket("b", "チケットB")]} showProjectBadge={false} />
    );

    // A+B を選択。
    fireEvent.click(screen.getByLabelText("チケットA を選択"));
    fireEvent.click(screen.getByLabelText("チケットB を選択"));
    expect([...captured.selectedIds].sort()).toEqual(["a", "b"]);

    // B が一覧から消える → cleanup effect が canonical state からも B を prune する。
    rerender(<SelectableTicketList tickets={[ticket("a", "チケットA")]} showProjectBadge={false} />);
    expect(captured.selectedIds).toEqual(["a"]);

    // 表示中の A を外す。
    fireEvent.click(screen.getByLabelText("チケットA を選択"));
    expect(captured.selectedIds).toEqual([]);

    // B が再び表示されても、prune 済なので自動再選択されない (re-entry なし)。
    rerender(
      <SelectableTicketList tickets={[ticket("a", "チケットA"), ticket("b", "チケットB")]} showProjectBadge={false} />
    );
    expect(captured.selectedIds).toEqual([]);
    expect(captured.selectedIds).not.toContain("b");
  });

  it("disables bulk selection (no checkboxes) when project badge is shown (横断表示)", () => {
    render(
      <SelectableTicketList tickets={[ticket("a", "チケットA")]} showProjectBadge={true} />
    );
    // showProjectBadge=true (project=all) では一括操作 UI を出さない。
    expect(screen.queryByLabelText("すべて選択")).not.toBeInTheDocument();
    expect(screen.queryByTestId("bulk-boundary")).not.toBeInTheDocument();
  });

  // A-7 (ADR-00045 R3 F-001): 期限強調は actionable status のみ。closed/cancelled は neutral。
  function dueTicket(id: string, status: string, due_date: string) {
    return { ...ticket(id, id), status, due_date };
  }

  it("actionable (open) の超過期限は『超過』強調を出す", () => {
    render(
      <SelectableTicketList
        tickets={[dueTicket("a", "open", "2026-05-01")]}
        showProjectBadge={false}
        referenceDate="2026-06-02"
        thresholdDays={7}
      />
    );
    expect(screen.getByText("超過 2026/5/1")).toBeInTheDocument();
  });

  it("closed の超過期限は neutral (『超過』を出さない、backend reminders と整合)", () => {
    render(
      <SelectableTicketList
        tickets={[dueTicket("a", "closed", "2026-05-01")]}
        showProjectBadge={false}
        referenceDate="2026-06-02"
        thresholdDays={7}
      />
    );
    // 日付は表示するが「超過」prefix / 赤強調は付かない (neutral)。
    expect(screen.getByText("2026/5/1")).toBeInTheDocument();
    expect(screen.queryByText(/超過/)).not.toBeInTheDocument();
  });

  it("cancelled の本日期限も neutral (『本日』を出さない)", () => {
    render(
      <SelectableTicketList
        tickets={[dueTicket("a", "cancelled", "2026-06-02")]}
        showProjectBadge={false}
        referenceDate="2026-06-02"
        thresholdDays={7}
      />
    );
    expect(screen.getByText("2026/6/2")).toBeInTheDocument();
    expect(screen.queryByText(/本日/)).not.toBeInTheDocument();
  });
});
