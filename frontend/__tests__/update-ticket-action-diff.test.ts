// R8 (Codex adversarial HIGH) 回帰 test: updateTicketAction は original_* と一致する field を
// PATCH payload から落とす (「PATCH = ユーザーが実際に触った field のみ」)。
// stale な編集フォーム (reload 拒否後など) を保存しても、触っていない status を再送して
// 直前の status/bulk mutation を巻き戻すことはできない。
import { beforeEach, describe, expect, it, vi } from "vitest";

import { updateTicketAction } from "../app/(admin)/tickets/[id]/actions";

const sentBodies: Record<string, unknown>[] = [];
vi.mock("@/lib/api/client", () => ({
  fetchBackendJson: async (_path: string, _schema: unknown, init?: RequestInit) => {
    sentBodies.push(JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>);
    return {
      id: "00000000-0000-4000-8000-00000000a001",
      project_id: "00000000-0000-4000-8000-00000000a002",
      title: "t-updated",
      description: null,
      status: "blocked",
      priority: null,
      due_date: null,
      assignee_actor_id: null,
      created_at: "2026-06-10T00:00:00Z",
      updated_at: "2026-06-10T00:00:01Z",
      tags: []
    };
  },
  BackendApiError: class extends Error {}
}));
vi.mock("@/lib/api/session", () => ({
  getCurrentProjectId: async () => "00000000-0000-4000-8000-00000000a002"
}));

function formDataOf(entries: Record<string, string>): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(entries)) fd.set(k, v);
  return fd;
}

const TICKET_ID = "00000000-0000-4000-8000-00000000a001";

beforeEach(() => {
  sentBodies.length = 0;
});

describe("updateTicketAction unchanged-field drop (R8)", () => {
  it("stale form (status 未変更) の保存は status を payload に含めない — 巻き戻し不能", async () => {
    // DB は外部更新で blocked、stale form の original/select は open のまま。ユーザーは title だけ編集。
    const result = await updateTicketAction(
      { kind: "idle" },
      formDataOf({
        ticket_id: TICKET_ID,
        title: "edited title",
        description: "",
        due_date: "",
        status: "open",
        priority: "",
        original_title: "old title",
        original_description: "",
        original_due_date: "",
        original_status: "open",
        original_priority: "",
        original_assignee_actor_id: ""
      })
    );
    expect(result.kind).toBe("ok");
    expect(sentBodies).toHaveLength(1);
    expect(sentBodies[0]).toEqual({ title: "edited title" });
    expect(sentBodies[0]).not.toHaveProperty("status");
  });

  it("ユーザーが意図して status を変更した場合は送信される", async () => {
    const result = await updateTicketAction(
      { kind: "idle" },
      formDataOf({
        ticket_id: TICKET_ID,
        title: "same",
        status: "in_progress",
        original_title: "same",
        original_status: "open"
      })
    );
    expect(result.kind).toBe("ok");
    expect(sentBodies[0]).toEqual({ status: "in_progress" });
  });

  it("全 field 未変更なら『更新する項目を入力してください』で送信しない", async () => {
    const result = await updateTicketAction(
      { kind: "idle" },
      formDataOf({
        ticket_id: TICKET_ID,
        title: "same",
        status: "open",
        original_title: "same",
        original_status: "open"
      })
    );
    expect(result.kind).toBe("error");
    expect(sentBodies).toHaveLength(0);
  });

  it("description の explicit clear ('' → null) は original 非空なら送信される", async () => {
    const result = await updateTicketAction(
      { kind: "idle" },
      formDataOf({
        ticket_id: TICKET_ID,
        description: "",
        original_description: "had content",
        title: "same",
        original_title: "same"
      })
    );
    expect(result.kind).toBe("ok");
    expect(sentBodies[0]).toEqual({ description: null });
  });
});
