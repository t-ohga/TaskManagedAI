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
    { project_id: "p-aaa", slug: "alpha" },
    { project_id: "p-bbb", slug: "beta" }
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
    project_id: "ignored-by-loader"
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
});
