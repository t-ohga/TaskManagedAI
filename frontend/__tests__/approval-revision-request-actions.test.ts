import { afterEach, describe, expect, it, vi } from "vitest";

import { requestApprovalRevisionAction } from "@/app/(admin)/approvals/[id]/_actions/request-revision";

const apiMocks = vi.hoisted(() => ({
  requestApprovalRevision: vi.fn()
}));

const cacheMocks = vi.hoisted(() => ({
  revalidatePath: vi.fn()
}));

vi.mock("next/cache", () => ({
  revalidatePath: cacheMocks.revalidatePath
}));

vi.mock("@/lib/api/approvals", () => ({
  requestApprovalRevision: apiMocks.requestApprovalRevision
}));

afterEach(() => {
  apiMocks.requestApprovalRevision.mockReset();
  cacheMocks.revalidatePath.mockReset();
});

function buildForm(values: Record<string, string>): FormData {
  const formData = new FormData();
  for (const [key, value] of Object.entries(values)) {
    formData.set(key, value);
  }
  return formData;
}

describe("requestApprovalRevisionAction", () => {
  it("rejects invalid approval ids before calling the backend", async () => {
    const result = await requestApprovalRevisionAction(
      "not-a-uuid",
      buildForm({ rationale: "needs changes" })
    );

    expect(result.ok).toBe(false);
    expect(apiMocks.requestApprovalRevision).not.toHaveBeenCalled();
  });

  it("rejects blank rationale before calling the backend", async () => {
    const result = await requestApprovalRevisionAction(
      APPROVAL_ID,
      buildForm({ rationale: "   " })
    );

    expect(result.ok).toBe(false);
    expect(apiMocks.requestApprovalRevision).not.toHaveBeenCalled();
  });

  it("rejects overlong rationale before calling the backend", async () => {
    const result = await requestApprovalRevisionAction(
      APPROVAL_ID,
      buildForm({ rationale: "a".repeat(2001) })
    );

    expect(result.ok).toBe(false);
    expect(apiMocks.requestApprovalRevision).not.toHaveBeenCalled();
  });

  it("submits trimmed rationale and does not return the rationale in the result", async () => {
    apiMocks.requestApprovalRevision.mockResolvedValueOnce({
      approval: { status: "invalidated" },
      revision_request_id: REVISION_REQUEST_ID
    });

    const result = await requestApprovalRevisionAction(
      APPROVAL_ID,
      buildForm({ rationale: "  Please update the tests.  " })
    );

    expect(result).toEqual({
      ok: true,
      status: "invalidated",
      revisionRequestId: REVISION_REQUEST_ID
    });
    expect(JSON.stringify(result)).not.toContain("Please update the tests.");
    expect(apiMocks.requestApprovalRevision).toHaveBeenCalledWith(APPROVAL_ID, {
      rationale: "Please update the tests."
    });
    // C-5 系統適用: action 内 revalidatePath は撤去済 (表示更新は client full reload)。回帰防止に非呼出を検証。
    expect(cacheMocks.revalidatePath).not.toHaveBeenCalled();
  });
});

const APPROVAL_ID = "00000000-0000-4000-8000-00000000a201";
const REVISION_REQUEST_ID = "00000000-0000-4000-8000-00000000a202";
