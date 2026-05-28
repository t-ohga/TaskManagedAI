import { afterEach, describe, expect, it, vi } from "vitest";

import { createTicketAction, type CreateTicketState } from "../app/(admin)/tickets/actions";

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: () => undefined,
  })),
}));

vi.mock("next/cache", () => ({
  revalidatePath: vi.fn(),
}));

// SP-012-11.1 BL-TCU-014: Server Action 内で getCurrentProjectId() を call、test では mock
vi.mock("@/lib/api/session", () => ({
  getCurrentProjectId: vi.fn(async () => "00000000-0000-4000-8000-000000000004"),
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

const idle: CreateTicketState = { kind: "idle" };

describe("createTicketAction (SP-012-11 BL-TCU-004)", () => {
  it("rejects invalid slug (non-kebab-case)", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    const formData = buildFormData({
      slug: "Invalid_Slug",
      title: "Some title",
    });
    const result = await createTicketAction(idle, formData);
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.message).toMatch(/slug/i);
    }
  });

  it("rejects empty title", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    const formData = buildFormData({ slug: "valid-slug", title: "" });
    const result = await createTicketAction(idle, formData);
    expect(result.kind).toBe("error");
  });

  it("POSTs to backend and returns ok on success", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");

    const ticketId = "00000000-0000-4000-8000-000000099001";
    const backendResponse = {
      id: ticketId,
      tenant_id: 1,
      project_id: "00000000-0000-4000-8000-000000000004",
      repository_id: null,
      slug: "valid-slug",
      title: "Valid Title",
      description: null,
      status: "open",
      priority: null,
      due_date: null,
      assignee_actor_id: null,
      created_by_actor_id: "00000000-0000-4000-8000-000000000001",
      metadata: { rls_ready: true, user_edited: true },
      created_at: "2026-05-22T20:00:00+00:00",
      updated_at: "2026-05-22T20:00:00+00:00",
    };

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify(backendResponse), { status: 201 }),
      );

    const formData = buildFormData({
      slug: "valid-slug",
      title: "Valid Title",
      status: "open",
    });
    const result = await createTicketAction(idle, formData);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.ticket_id).toBe(ticketId);
    }
    expect(fetchMock).toHaveBeenCalledOnce();
    const call = fetchMock.mock.calls[0];
    if (call === undefined) {
      throw new Error("fetch was not called");
    }
    const calledUrl = call[0];
    const calledInit = call[1];
    expect(String(calledUrl)).toContain(
      "/api/v1/projects/00000000-0000-4000-8000-000000000004/tickets",
    );
    expect(calledInit?.method).toBe("POST");
    expect(calledInit?.body).toBeDefined();
    const body = JSON.parse(String(calledInit?.body));
    expect(body.slug).toBe("valid-slug");
    expect(body.title).toBe("Valid Title");
  });

  it("returns error on backend 4xx response", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("conflict", { status: 409 }),
    );

    const formData = buildFormData({
      slug: "valid-slug",
      title: "Title",
    });
    const result = await createTicketAction(idle, formData);
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.message).toMatch(/409/);
    }
  });
});
