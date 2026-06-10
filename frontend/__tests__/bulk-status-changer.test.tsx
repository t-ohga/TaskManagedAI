// C-5 workaround の回帰 test (Codex adversarial R1 検証):
// BulkStatusChanger の deferred refresh (useDeferredRouterRefresh) が、全件成功 → onClear() で
// 親の selectedIds が空になっても失われないことを実証する。親は `bulkEnabled` (project view 固定、
// selectedIds 非依存) で条件 render するため、clear 後も component は mount されたまま
// `return null` になるだけ — tick state と effect は生存し、router.refresh() は確実に発火する。
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import { BulkStatusChanger } from "@/components/bulk-status-changer";

// C-5 第 2 round: hook は router.refresh ではなく full reload を行う (refresh/replace は
// Server Action 直後に確率的に適用されない regression を 3-run 実測で確認したため)。
const reload = vi.fn();
// jsdom の location.reload は non-configurable のため、window.location ごと差し替えて spy する。
const originalLocation = window.location;
beforeAll(() => {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, reload }
  });
});
afterAll(() => {
  Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
});

const updateCalls: Record<string, string>[] = [];
vi.mock("@/app/(admin)/tickets/[id]/actions", () => ({
  updateTicketAction: async (_state: unknown, fd: FormData) => {
    const entries: Record<string, string> = {};
    for (const [k, v] of fd.entries()) entries[k] = String(v);
    updateCalls.push(entries);
    return { kind: "ok" as const };
  }
}));

vi.mock("@/components/toast", () => ({
  useToast: () => ({ toast: vi.fn() })
}));

// 親の selectedIds 管理を再現: onClear で空にするが、BulkStatusChanger 自体は
// mount したまま (selectable-ticket-list の bulkEnabled は selectedIds 非依存)。
function Harness() {
  const [selectedIds, setSelectedIds] = useState(["00000000-0000-4000-8000-00000000c001"]);
  return (
    <BulkStatusChanger
      selectedIds={selectedIds}
      onClear={() => setSelectedIds([])}
      onSelectionChange={setSelectedIds}
    />
  );
}

beforeEach(() => {
  reload.mockClear();
  updateCalls.length = 0;
});

describe("BulkStatusChanger (C-5 deferred refresh)", () => {
  it("全件成功 → onClear で selectedIds が空になっても deferred reload が発火する", async () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "closed" } });
    fireEvent.click(screen.getByRole("button", { name: /適用|変更|更新/ }));

    await waitFor(() => expect(updateCalls).toHaveLength(1));
    expect(updateCalls[0]).toMatchObject({ status: "closed" });
    // clear 後 (component は return null) でも effect 経由の reload が到達する。
    await waitFor(() => expect(reload).toHaveBeenCalled());
  });
});
