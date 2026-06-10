// R7 (Codex adversarial HIGH) 回帰 test: pre-commit gate 通過後〜reload 発火の間に
// 新しく作られた draft は、reload **直前の再評価**で確認され、拒否なら reload されない。
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";

const reload = vi.fn();
const discardConfirm = vi.fn(() => true);
vi.mock("@/lib/full-reload", () => ({
  fullReload: () => reload(),
  confirmDiscardUnsavedDrafts: () => discardConfirm()
}));

beforeEach(() => {
  reload.mockClear();
  discardConfirm.mockClear();
  discardConfirm.mockReturnValue(true);
});

describe("useDeferredRouterRefresh (R7: reload 直前再評価)", () => {
  it("draft なし (confirm true) なら reload する", () => {
    const { result } = renderHook(() => useDeferredRouterRefresh());
    act(() => result.current());
    expect(discardConfirm).toHaveBeenCalled();
    expect(reload).toHaveBeenCalledOnce();
  });

  it("mutation 中に作られた draft の破棄を拒否したら reload しない", () => {
    // gate 通過後に新規 draft ができた状況 = reload 直前の再評価が false を返す。
    discardConfirm.mockReturnValue(false);
    const { result } = renderHook(() => useDeferredRouterRefresh());
    act(() => result.current());
    expect(discardConfirm).toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
  });
});
