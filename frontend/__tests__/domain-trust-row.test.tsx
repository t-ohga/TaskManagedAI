// Codex auto-review P2 回帰 test:
// domain-trust の編集 form を controlled 化したことで、保存成功後に reload が別 draft 確認で
// キャンセルされても (prop 未更新)、controlled 値が saved を保持し stale prop (旧 entry 値) へ
// 巻き戻らないこと、dirty が解除されること、再 save が saved 値を送ること (保存済み trust を
// 旧値再送で revert しない) を固定する。
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type * as FullReloadModule from "@/lib/full-reload";
import type { DomainTrust } from "@/lib/domain/research-advanced";

import { DomainTrustManager } from "../app/(admin)/domain-trust/_components";

const fullReloadSpy = vi.fn();
let reloadConfirmReturn = true;
vi.mock("@/lib/full-reload", async (importOriginal) => {
  const actual = await importOriginal<typeof FullReloadModule>();
  return {
    ...actual,
    fullReload: () => fullReloadSpy(),
    confirmDiscardUnsavedDrafts: () => reloadConfirmReturn,
    prepareDiscardOnCommit: () => ({ approved: true, commit: vi.fn() })
  };
});

const updateSpy = vi.fn();
vi.mock("@/app/(admin)/domain-trust/actions", () => ({
  createDomainTrustAction: vi.fn(async () => ({ kind: "idle" })),
  updateDomainTrustAction: (...args: unknown[]) => updateSpy(...args),
  deleteDomainTrustAction: vi.fn(async () => ({ kind: "idle" }))
}));

const ENTRY: DomainTrust = {
  id: "00000000-0000-4000-8000-00000000d001",
  tenant_id: 1,
  domain: "example.com",
  trust_tier: "medium",
  rationale: "r1",
  created_by_actor_id: "00000000-0000-4000-8000-00000000a001",
  created_at: "2026-06-11T00:00:00Z",
  updated_at: "2026-06-11T00:00:00Z"
};

beforeEach(() => {
  fullReloadSpy.mockClear();
  reloadConfirmReturn = true;
  updateSpy.mockReset();
});

describe("DomainTrustRow controlled edit (Codex auto-review P2)", () => {
  it("保存成功後 reload 拒否でも controlled 値が saved を保持し、form を lock して stale 再 save を防ぐ", async () => {
    updateSpy.mockResolvedValue({ kind: "ok", message: "更新しました" });
    reloadConfirmReturn = false; // reload 拒否 → prop 未更新のまま form mount 継続

    render(<DomainTrustManager entries={[ENTRY]} />);

    const editForm = screen.getByTestId("domain-trust-edit-form");
    const tierSelect = within(editForm).getByRole("combobox");
    const saveButton = within(editForm).getByRole("button", { name: "保存" });
    expect(tierSelect).toHaveValue("medium");

    // medium → low へ変更 → dirty
    fireEvent.change(tierSelect, { target: { value: "low" } });
    expect(editForm).toHaveAttribute("data-dirty", "true");
    // 1 回目の送信値は low (controlled)。
    fireEvent.click(saveButton);
    await waitFor(() => expect(updateSpy).toHaveBeenCalledTimes(1));
    const firstFormData = updateSpy.mock.calls[0]?.[1] as FormData | undefined;
    expect(firstFormData?.get("trust_tier")).toBe("low");

    // reload 拒否 (prop 未更新) でも controlled value は saved (low) を保持 → stale medium へ戻らない。
    await waitFor(() => expect(tierSelect).toHaveValue("low"));
    // saved=value=low なので dirty 解除 (reload を自分自身で阻害しない)。
    await waitFor(() => expect(editForm).not.toHaveAttribute("data-dirty"));
    expect(fullReloadSpy).not.toHaveBeenCalled();

    // R9: 保存後は form を lock し、stale baseline からの chained 再 save を物理禁止する。
    await waitFor(() => expect(tierSelect).toBeDisabled());
    expect(saveButton).toBeDisabled();
    expect(screen.getByText(/続けて編集するにはページを再読み込み/u)).toBeVisible();
  });

  it("prop (entry) が更新されたら controlled state を server 値に再同期し draft を破棄する", () => {
    const { rerender } = render(<DomainTrustManager entries={[ENTRY]} />);
    const editForm = screen.getByTestId("domain-trust-edit-form");
    const tierSelect = within(editForm).getByRole("combobox");

    // 未保存で low に変更 (draft)。
    fireEvent.change(tierSelect, { target: { value: "low" } });
    expect(tierSelect).toHaveValue("low");

    // server 側で high に更新され reload が新 entry を運んだ状況 (同一 instance に新 prop) を再現。
    rerender(<DomainTrustManager entries={[{ ...ENTRY, trust_tier: "high" }]} />);
    // 同一行 (key=entry.id) は render 中 state 調整で新 prop に同期し、古い draft (low) を破棄する。
    expect(tierSelect).toHaveValue("high");
    expect(editForm).not.toHaveAttribute("data-dirty");
  });
});
