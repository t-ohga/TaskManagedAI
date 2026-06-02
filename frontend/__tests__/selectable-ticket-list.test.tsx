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
});
