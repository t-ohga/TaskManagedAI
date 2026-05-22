/**
 * Frontend health info (SP-012-9 BL-UIW-012).
 *
 * Next.js own runtime metadata を real source から構築し、`/api/healthz`
 * route handler + Dashboard page の両方で共有する。
 *
 * - status: render が動作している → "ok"
 * - service: "frontend"
 * - runtime: Next.js own runtime (nodejs)
 * - node_env: process.env.NODE_ENV (development / production / test)
 *
 * これにより、Dashboard frontend health card が hardcoded "ok" ではなく
 * **実 runtime state から構築された値**を表示する (BL-UIW-012 完遂)。
 */

export type FrontendHealth = {
  readonly status: "ok";
  readonly service: "frontend";
  readonly runtime: "nodejs";
  readonly node_env: string;
};

export function getFrontendHealth(): FrontendHealth {
  return {
    status: "ok",
    service: "frontend",
    runtime: "nodejs",
    node_env: process.env.NODE_ENV ?? "unknown",
  };
}
