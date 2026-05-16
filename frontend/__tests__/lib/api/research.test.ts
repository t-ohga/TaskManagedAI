import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getResearchTask,
  listResearchTasks
} from "@/lib/api/research";

const cookieMocks = vi.hoisted(() => ({
  get: vi.fn()
}));

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: cookieMocks.get
  }))
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  cookieMocks.get.mockReset();
});

describe("research API client", () => {
  it("builds project-scoped URLs and forwards the dev session cookie", async () => {
    const projectId = "00000000-0000-4000-8000-000000049001";
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    vi.stubEnv("TASKMANAGEDAI_ADMIN_PROJECT_ID", projectId);
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });

    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [],
          total: 0,
          limit: 25,
          offset: 5
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      )
    );

    await expect(listResearchTasks({ limit: 25, offset: 5 })).resolves.toEqual({
      items: [],
      total: 0,
      limit: 25,
      offset: 5
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://backend.test/api/v1/projects/${projectId}/research-tasks?limit=25&offset=5`,
      expect.objectContaining({
        cache: "no-store"
      })
    );

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = init.headers as Headers;
    expect(headers.get("accept")).toBe("application/json");
    expect(headers.get("cookie")).toBe("taskmanagedai_session=session-cookie-value");
  });

  it("surfaces backend errors with status code", async () => {
    const projectId = "00000000-0000-4000-8000-000000049001";
    const researchTaskId = "00000000-0000-4000-8000-000000049002";
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    vi.stubEnv("TASKMANAGEDAI_ADMIN_PROJECT_ID", projectId);
    cookieMocks.get.mockReturnValue(undefined);

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "failed" }), {
        status: 503,
        headers: { "content-type": "application/json" }
      })
    );

    await expect(getResearchTask(researchTaskId)).rejects.toMatchObject({
      name: "BackendApiError",
      status: 503
    });
  });
});
