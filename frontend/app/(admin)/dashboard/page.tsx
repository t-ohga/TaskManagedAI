import { getBackendHealth } from "@/lib/api/client";
import type { HealthResponse } from "@/lib/api/types";

export const dynamic = "force-dynamic";

type BackendHealthState =
  | { kind: "ok"; health: HealthResponse }
  | { kind: "error"; message: string };

async function readBackendHealth(): Promise<BackendHealthState> {
  try {
    return { kind: "ok", health: await getBackendHealth() };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Backend healthcheck failed.";
    return { kind: "error", message };
  }
}

export default async function DashboardPage() {
  const backendHealth = await readBackendHealth();

  return (
    <div className="grid gap-6">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">Admin</p>
        <h1 className="text-3xl font-semibold tracking-normal">Dashboard</h1>
      </header>

      <section aria-label="Service health" className="grid gap-4 md:grid-cols-2">
        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold">Frontend</h2>
              <p className="mt-1 text-sm text-muted">Next.js app health endpoint</p>
            </div>
            <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
              ok
            </span>
          </div>
          <dl className="mt-5 grid gap-3 text-sm">
            <div className="flex justify-between gap-4 border-t border-line pt-3">
              <dt className="text-muted">Endpoint</dt>
              <dd className="font-mono">/api/healthz</dd>
            </div>
            <div className="flex justify-between gap-4 border-t border-line pt-3">
              <dt className="text-muted">Service</dt>
              <dd className="font-mono">frontend</dd>
            </div>
          </dl>
        </article>

        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold">Backend</h2>
              <p className="mt-1 text-sm text-muted">FastAPI internal health endpoint</p>
            </div>
            {backendHealth.kind === "ok" ? (
              <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                {backendHealth.health.status}
              </span>
            ) : (
              <span className="rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-attention">
                unavailable
              </span>
            )}
          </div>

          {backendHealth.kind === "ok" ? (
            <dl className="mt-5 grid gap-3 text-sm">
              <div className="flex justify-between gap-4 border-t border-line pt-3">
                <dt className="text-muted">Service</dt>
                <dd className="font-mono">{backendHealth.health.service}</dd>
              </div>
              <div className="flex justify-between gap-4 border-t border-line pt-3">
                <dt className="text-muted">Version</dt>
                <dd className="font-mono">{backendHealth.health.version}</dd>
              </div>
            </dl>
          ) : (
            <p role="status" className="mt-5 border-t border-line pt-3 text-sm text-muted">
              {backendHealth.message}
            </p>
          )}
        </article>
      </section>
    </div>
  );
}

