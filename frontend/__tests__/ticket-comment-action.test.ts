import { afterEach, describe, expect, it, vi } from "vitest";

import { addTicketCommentAction } from "../app/(admin)/tickets/actions";

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: () => undefined,
  })),
}));

vi.mock("next/cache", () => ({
  revalidatePath: vi.fn(),
}));

// ADR-00041 N-1: comment action は createTicketAction と同じく project を server-owned に
// 解決する (form の値ではなく getCurrentProjectId)。wrong-project write 防止。
const CURRENT_PROJECT_ID = "00000000-0000-4000-8000-000000000004";
vi.mock("@/lib/api/session", () => ({
  getCurrentProjectId: vi.fn(async () => CURRENT_PROJECT_ID),
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

function buildFormData(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) {
    data.set(key, value);
  }
  return data;
}

const TICKET_ID = "00000000-0000-4000-8000-0000000aa001";

describe("addTicketCommentAction (ADR-00041 N-1)", () => {
  it("rejects empty body before hitting backend", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const result = await addTicketCommentAction(
      buildFormData({ ticket_id: TICKET_ID, body: "   " })
    );
    expect(result.kind).toBe("error");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects non-uuid ticket_id before hitting backend", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const result = await addTicketCommentAction(
      buildFormData({ ticket_id: "../secrets", body: "hello" })
    );
    expect(result.kind).toBe("error");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects body over 4000 chars before hitting backend", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const result = await addTicketCommentAction(
      buildFormData({ ticket_id: TICKET_ID, body: "x".repeat(4001) })
    );
    expect(result.kind).toBe("error");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("POSTs to the current-project comment endpoint and returns ok", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    const backendResponse = {
      id: "00000000-0000-4000-8000-0000000cc001",
      message: "ありがとう",
      actor_id: "00000000-0000-4000-8000-000000000001",
      created_at: "2026-06-01T10:00:00+00:00",
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(backendResponse), { status: 201 }));

    const result = await addTicketCommentAction(
      buildFormData({ ticket_id: TICKET_ID, body: "ありがとう" })
    );

    expect(result.kind).toBe("ok");
    expect(fetchMock).toHaveBeenCalledOnce();
    const call = fetchMock.mock.calls[0];
    if (call === undefined) throw new Error("fetch was not called");
    // server-owned: form の ticket_id は使うが project は session 由来。
    expect(String(call[0])).toBe(
      `http://backend.test/api/v1/projects/${CURRENT_PROJECT_ID}/tickets/${TICKET_ID}/comments`
    );
    expect(call[1]?.method).toBe("POST");
    const body = JSON.parse(String(call[1]?.body));
    expect(body).toEqual({ message: "ありがとう" });
  });

  it("maps backend 422 (secret pattern) to a fixed message without leaking detail", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("comment rejected: message contains a forbidden secret pattern", {
        status: 422,
      })
    );
    const result = await addTicketCommentAction(
      buildFormData({ ticket_id: TICKET_ID, body: "leak sk-xxxxxxxxxxxxxxxxxxxxxxxx" })
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.message).toContain("機密情報");
      expect(result.message).not.toContain("sk-");
      expect(result.message).not.toContain("forbidden secret pattern");
    }
  });

  it("maps backend 404/409 to a project/archive guidance message", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("ticket not found", { status: 404 })
    );
    const result = await addTicketCommentAction(
      buildFormData({ ticket_id: TICKET_ID, body: "hi" })
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.message).toMatch(/プロジェクト外|アーカイブ/);
    }
  });
});
