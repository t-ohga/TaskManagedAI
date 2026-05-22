import { describe, expect, it } from "vitest";

import { GET } from "../app/api/healthz/route";

describe("GET /api/healthz", () => {
  it("returns the frontend liveness payload without caching", async () => {
    const response = await GET();

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");

    const payload: unknown = await response.json();
    // SP-012-9 BL-UIW-012: runtime info を含む real source 構築
    expect(payload).toMatchObject({
      status: "ok",
      service: "frontend",
      runtime: "nodejs",
    });
    // node_env は test 環境 (NODE_ENV=test) を反映、enum 化された値
    const typed = payload as { node_env: string };
    expect(typed.node_env).toMatch(/^(development|production|test|unknown)$/);
  });
});

