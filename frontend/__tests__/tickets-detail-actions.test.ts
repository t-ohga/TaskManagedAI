import { afterEach, describe, expect, it, vi } from "vitest";

import {
  updateTicketAction,
  type UpdateTicketState,
} from "../app/(admin)/tickets/[id]/actions";

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: () => undefined,
  })),
}));

vi.mock("next/cache", () => ({
  revalidatePath: vi.fn(),
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

const idle: UpdateTicketState = { kind: "idle" };

function buildForm(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [k, v] of Object.entries(values)) data.set(k, v);
  return data;
}

describe("updateTicketAction (SP-012-11 BL-TCU-005)", () => {
  it("rejects invalid ticket_id format", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    const formData = buildForm({ ticket_id: "not-uuid", status: "open" });
    const result = await updateTicketAction(idle, formData);
    expect(result.kind).toBe("error");
  });

  it("rejects empty payload (no fields to update)", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    const formData = buildForm({
      ticket_id: "00000000-0000-4000-8000-000000099001",
    });
    const result = await updateTicketAction(idle, formData);
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.message).toMatch(/更新する項目/);
    }
  });

  it("PATCHes to backend and returns ok on success", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");

    const ticketId = "00000000-0000-4000-8000-000000099001";
    const backendResponse = {
      id: ticketId,
      tenant_id: 1,
      project_id: "00000000-0000-4000-8000-000000000004",
      repository_id: null,
      slug: "test-slug",
      title: "Updated Title",
      description: null,
      status: "in_progress",
      priority: "high",
      assignee_actor_id: null,
      created_by_actor_id: "00000000-0000-4000-8000-000000000001",
      metadata: { rls_ready: true, user_edited: true },
      created_at: "2026-05-22T20:00:00+00:00",
      updated_at: "2026-05-22T21:00:00+00:00",
    };

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify(backendResponse), { status: 200 }),
      );

    const formData = buildForm({
      ticket_id: ticketId,
      title: "Updated Title",
      status: "in_progress",
      priority: "high",
    });
    const result = await updateTicketAction(idle, formData);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.ticket_id).toBe(ticketId);
    }

    expect(fetchMock).toHaveBeenCalledOnce();
    const call = fetchMock.mock.calls[0];
    if (call === undefined) {
      throw new Error("fetch was not called");
    }
    expect(String(call[0])).toContain(`/tickets/${ticketId}`);
    expect(call[1]?.method).toBe("PATCH");
    const body = JSON.parse(String(call[1]?.body));
    expect(body.title).toBe("Updated Title");
    expect(body.status).toBe("in_progress");
    expect(body.priority).toBe("high");
    expect(body).not.toHaveProperty("ticket_id");
  });

  it("returns error on backend 404", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("not found", { status: 404 }),
    );

    const formData = buildForm({
      ticket_id: "00000000-0000-4000-8000-000000099001",
      status: "closed",
    });
    const result = await updateTicketAction(idle, formData);
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.message).toMatch(/404/);
    }
  });

  // Codex PR #121 R1 F-PR121-001 (P1) fix regression test
  it("sends null for cleared description / priority (explicit clear via empty string)", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");

    const ticketId = "00000000-0000-4000-8000-000000099002";
    const backendResponse = {
      id: ticketId,
      tenant_id: 1,
      project_id: "00000000-0000-4000-8000-000000000004",
      repository_id: null,
      slug: "test",
      title: "Test",
      description: null,
      status: "open",
      priority: null,
      assignee_actor_id: null,
      created_by_actor_id: "00000000-0000-4000-8000-000000000001",
      metadata: { rls_ready: true, user_edited: true },
      created_at: "2026-05-22T20:00:00+00:00",
      updated_at: "2026-05-22T21:00:00+00:00",
    };

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify(backendResponse), { status: 200 }),
      );

    const formData = buildForm({
      ticket_id: ticketId,
      // user が UI で "" を入力 = explicit clear 意図
      description: "",
      priority: "",
    });
    const result = await updateTicketAction(idle, formData);
    expect(result.kind).toBe("ok");

    expect(fetchMock).toHaveBeenCalledOnce();
    const call = fetchMock.mock.calls[0];
    if (call === undefined) {
      throw new Error("fetch was not called");
    }
    const body = JSON.parse(String(call[1]?.body));
    // null として送られていることを verify (undefined ではない)
    expect(body.description).toBeNull();
    expect(body.priority).toBeNull();
  });
});
