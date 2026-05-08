import { describe, expect, it } from "vitest";

import { GET } from "../app/api/healthz/route";

describe("GET /api/healthz", () => {
  it("returns the frontend liveness payload without caching", async () => {
    const response = await GET();

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");

    const payload: unknown = await response.json();
    expect(payload).toEqual({
      status: "ok",
      service: "frontend"
    });
  });
});

