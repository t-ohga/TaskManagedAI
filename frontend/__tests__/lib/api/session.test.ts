import { afterEach, describe, expect, it, vi } from "vitest";

import { updateProjectAutonomyLevel } from "@/lib/api/session";

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

describe("session API client", () => {
  it("updates autonomy level without exposing policy_profile", async () => {
    const projectId = "00000000-0000-4000-8000-000000049001";
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });

    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          tenant_id: 1,
          project_id: projectId,
          workspace_id: "00000000-0000-4000-8000-000000049002",
          slug: "taskmanagedai",
          name: "TaskManagedAI",
          status: "active",
          policy_profile: "default",
          autonomy_level: "L2"
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      )
    );

    await expect(updateProjectAutonomyLevel(projectId, "L2")).resolves.toMatchObject({
      project_id: projectId,
      policy_profile: "default",
      autonomy_level: "L2"
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://backend.test/api/v1/me/projects/${projectId}/autonomy`,
      expect.objectContaining({
        method: "PATCH"
      })
    );

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = init.headers as Headers;
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("cookie")).toBe("taskmanagedai_session=session-cookie-value");
    expect(init.body).toBe(JSON.stringify({ autonomy_level: "L2" }));
    expect(String(init.body)).not.toContain("policy_profile");
  });
});
