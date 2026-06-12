import { expect, test } from "@playwright/test";

test("GET /api/healthz returns frontend health", async ({ request }) => {
  const response = await request.get("/api/healthz");

  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toBe("no-store");

  const payload: unknown = await response.json();
  // BL-UIW-012 で getFrontendHealth() は runtime / node_env を追加した。node_env は実 runtime 依存
  // (development / test / production) のため exact 値ではなく string であることだけ固定する。
  expect(payload).toEqual({
    status: "ok",
    service: "frontend",
    runtime: "nodejs",
    node_env: expect.any(String)
  });
});

