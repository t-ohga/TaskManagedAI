import { beforeEach, describe, expect, it, vi } from "vitest";

import type { fetchBackendRaw as FetchBackendRawType } from "@/lib/api/client";
import { BackendApiError } from "@/lib/api/client";
import { loadTicket } from "@/app/(admin)/tickets/[id]/load-ticket";

type ClientModule = {
  fetchBackendRaw: typeof FetchBackendRawType;
};

// fetchBackendRaw のみ mock、BackendApiError は実クラスを使う (instanceof 判定のため)。
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<ClientModule>();
  return { ...actual, fetchBackendRaw: vi.fn() };
});

const { fetchBackendRaw } = await import("@/lib/api/client");
const mockFetch = vi.mocked(fetchBackendRaw);

// backend は ticket_id を UUID として扱う。loader の path 連結も UUID 前提。
const VALID_UUID = "11111111-2222-4333-8444-555555555555";

const PROJECTS = {
  projects: [
    { project_id: "p-aaa", slug: "alpha", name: "Alpha", status: "active" },
    { project_id: "p-bbb", slug: "beta", name: "Beta", status: "active" }
  ]
};

function ticketPayload(id: string) {
  return {
    id,
    title: "T",
    slug: "t-1",
    status: "open",
    description: null,
    priority: null,
    due_date: null,
    created_at: null,
    updated_at: null,
    project_id: "ignored-by-loader",
    // backend TicketRead は常に tags を返す (default_factory=list)。loader が fail-closed なので
    // fixture も explicit [] を持たせる。tags 欠落ケースは下の omitted test で別途検証する。
    tags: []
  };
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe("loadTicket (Codex B2b R2/R3/R4/R5 contract)", () => {
  it("by-id endpoint で解決し、所有 project の slug を project_slug に詰める", async () => {
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return PROJECTS;
      if (path === `/api/v1/projects/p-aaa/tickets/${VALID_UUID}`) throw new BackendApiError(404, "nf");
      if (path === `/api/v1/projects/p-bbb/tickets/${VALID_UUID}`) return ticketPayload(VALID_UUID);
      throw new BackendApiError(500, "unexpected");
    });

    const result = await loadTicket(VALID_UUID);

    expect(result).not.toBeNull();
    expect(result?.id).toBe(VALID_UUID);
    expect(result?.project_id).toBe("p-bbb");
    expect(result?.project_slug).toBe("beta");
  });

  it("全 project が 404 のときだけ null を返す (notFound 経路)", async () => {
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return PROJECTS;
      throw new BackendApiError(404, "nf");
    });

    await expect(loadTicket(VALID_UUID)).resolves.toBeNull();
  });

  it("degraded /me/projects (projects 欠落) を false 404 にせず throw する (R8 HIGH)", async () => {
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return {}; // projects envelope 欠落
      throw new BackendApiError(500, "unexpected");
    });
    await expect(loadTicket(VALID_UUID)).rejects.toThrow();
  });

  it("project row が id を欠く degraded response で throw する (R8 HIGH)", async () => {
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return { projects: [{ slug: "alpha", name: "Alpha" }] };
      throw new BackendApiError(500, "unexpected");
    });
    await expect(loadTicket(VALID_UUID)).rejects.toThrow();
  });

  it("malformed tag metadata は [] に潰さず throw する (fail-closed、Codex R6 HIGH)", async () => {
    // tag 付き ticket を「タグなし」と silent 誤表示しないため、palette 外 color を throw に倒す。
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return PROJECTS;
      if (path === `/api/v1/projects/p-aaa/tickets/${VALID_UUID}`) throw new BackendApiError(404, "nf");
      if (path === `/api/v1/projects/p-bbb/tickets/${VALID_UUID}`) {
        return {
          ...ticketPayload(VALID_UUID),
          tags: [{ id: "00000000-0000-4000-8000-00000000a001", name: "x", color: "magenta" }]
        };
      }
      throw new BackendApiError(500, "unexpected");
    });

    await expect(loadTicket(VALID_UUID)).rejects.toThrow();
  });

  it("tags metadata が欠落 (version skew / degraded) なら throw する (explicit [] と区別、R7 HIGH)", async () => {
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return PROJECTS;
      if (path === `/api/v1/projects/p-aaa/tickets/${VALID_UUID}`) throw new BackendApiError(404, "nf");
      if (path === `/api/v1/projects/p-bbb/tickets/${VALID_UUID}`) {
        // tags field を欠落させた degraded response
        const payload: Record<string, unknown> = { ...ticketPayload(VALID_UUID) };
        delete payload.tags;
        return payload;
      }
      throw new BackendApiError(500, "unexpected");
    });

    await expect(loadTicket(VALID_UUID)).rejects.toThrow();
  });

  it("explicit tags:[] は有効なタグなし ticket として扱う", async () => {
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return PROJECTS;
      if (path === `/api/v1/projects/p-aaa/tickets/${VALID_UUID}`) throw new BackendApiError(404, "nf");
      if (path === `/api/v1/projects/p-bbb/tickets/${VALID_UUID}`) return { ...ticketPayload(VALID_UUID), tags: [] };
      throw new BackendApiError(500, "unexpected");
    });

    const result = await loadTicket(VALID_UUID);
    expect(result?.tags).toEqual([]);
  });

  it("有効な tags は detail にそのまま詰める", async () => {
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return PROJECTS;
      if (path === `/api/v1/projects/p-aaa/tickets/${VALID_UUID}`) throw new BackendApiError(404, "nf");
      if (path === `/api/v1/projects/p-bbb/tickets/${VALID_UUID}`) {
        return {
          ...ticketPayload(VALID_UUID),
          tags: [{ id: "00000000-0000-4000-8000-00000000a001", name: "bug", color: "red" }]
        };
      }
      throw new BackendApiError(500, "unexpected");
    });

    const result = await loadTicket(VALID_UUID);
    expect(result?.tags).toHaveLength(1);
    expect(result?.tags[0]?.name).toBe("bug");
  });

  it("非 404 失敗は found より優先して rethrow する (fail-closed、R4)", async () => {
    // 所有 project (beta) で found だが、別 project (alpha) が 403 → found を隠さず throw。
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return PROJECTS;
      if (path === `/api/v1/projects/p-aaa/tickets/${VALID_UUID}`) throw new BackendApiError(403, "forbidden");
      if (path === `/api/v1/projects/p-bbb/tickets/${VALID_UUID}`) return ticketPayload(VALID_UUID);
      throw new BackendApiError(500, "unexpected");
    });

    await expect(loadTicket(VALID_UUID)).rejects.toMatchObject({ status: 403 });
  });

  it("所有 project の 5xx を false 404 に潰さず rethrow する", async () => {
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return PROJECTS;
      if (path === `/api/v1/projects/p-aaa/tickets/${VALID_UUID}`) throw new BackendApiError(404, "nf");
      if (path === `/api/v1/projects/p-bbb/tickets/${VALID_UUID}`) throw new BackendApiError(500, "server");
      throw new BackendApiError(500, "unexpected");
    });

    await expect(loadTicket(VALID_UUID)).rejects.toMatchObject({ status: 500 });
  });

  it("/me/projects 取得失敗は null に潰さず propagate する", async () => {
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") throw new BackendApiError(401, "unauth");
      return ticketPayload(VALID_UUID);
    });

    await expect(loadTicket(VALID_UUID)).rejects.toMatchObject({ status: 401 });
  });

  it("非 UUID の id は backend を呼ばず null を返す (R5、path traversal 防止)", async () => {
    await expect(loadTicket("not-a-uuid")).resolves.toBeNull();
    await expect(loadTicket("../../../me/projects")).resolves.toBeNull();
    await expect(loadTicket("11111111-2222-4333-8444-555555555555/../secrets")).resolves.toBeNull();
    // 検証で短絡するため fetchBackendRaw は一度も呼ばれない。
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("UUIDv7 等 v1-8 の id も ticket 契約どおり受理する (R6、契約 drift 防止)", async () => {
    // version nibble = 7 (3rd group 先頭), variant = 8 (4th group 先頭) の有効な UUIDv7。
    const uuidV7 = "01890a5d-ac96-7af0-8c3a-1234567890ab";
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return PROJECTS;
      if (path === `/api/v1/projects/p-aaa/tickets/${uuidV7}`) throw new BackendApiError(404, "nf");
      if (path === `/api/v1/projects/p-bbb/tickets/${uuidV7}`) return ticketPayload(uuidV7);
      throw new BackendApiError(500, "unexpected");
    });

    const result = await loadTicket(uuidV7);
    expect(result?.id).toBe(uuidV7);
    expect(result?.project_slug).toBe("beta");
  });

  it("大文字 route id は lowercase 正規化して backend 応答と照合する (R6)", async () => {
    // backend は canonical lowercase を返す。route param が大文字でも found 扱いにする。
    mockFetch.mockImplementation(async (path: string) => {
      if (path === "/api/v1/me/projects") return PROJECTS;
      // path には lowercase で連結される。
      if (path === `/api/v1/projects/p-aaa/tickets/${VALID_UUID}`) throw new BackendApiError(404, "nf");
      if (path === `/api/v1/projects/p-bbb/tickets/${VALID_UUID}`) return ticketPayload(VALID_UUID);
      throw new BackendApiError(500, "unexpected");
    });

    const result = await loadTicket(VALID_UUID.toUpperCase());
    expect(result?.id).toBe(VALID_UUID);
    expect(result?.project_id).toBe("p-bbb");
  });
});
