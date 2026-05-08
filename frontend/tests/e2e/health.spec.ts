import { expect, test } from "@playwright/test";

test("GET /api/healthz returns frontend health", async ({ request }) => {
  const response = await request.get("/api/healthz");

  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toBe("no-store");

  const payload: unknown = await response.json();
  expect(payload).toEqual({
    status: "ok",
    service: "frontend"
  });
});

