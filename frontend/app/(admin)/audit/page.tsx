import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

import { BackendApiError } from "@/lib/api/client";
import { listAuditEvents, type AuditEvent } from "@/lib/api/audit";

export const dynamic = "force-dynamic";

type AuditLogPageProps = {
  searchParams?: Promise<{ event_type?: string; actor_id?: string }>;
};

type AuditState =
  | {
      kind: "ok";
      events: AuditEvent[];
      total: number;
      eventType?: string;
      actorId?: string;
    }
  | { kind: "error"; message: string };

async function readAuditEvents(
  eventType: string | undefined,
  actorId: string | undefined
): Promise<AuditState> {
  try {
    const options: {
      eventType?: string;
      actorId?: string;
      limit: number;
      offset: number;
    } = { limit: 50, offset: 0 };
    if (eventType !== undefined) {
      options.eventType = eventType;
    }
    if (actorId !== undefined) {
      options.actorId = actorId;
    }
    const response = await listAuditEvents(options);
    return {
      kind: "ok",
      events: response.events,
      total: response.total,
      ...(eventType !== undefined ? { eventType } : {}),
      ...(actorId !== undefined ? { actorId } : {})
    };
  } catch (error: unknown) {
    if (error instanceof BackendApiError) {
      return {
        kind: "error",
        message: `バックエンドが ${error.status} を返しました: ${error.message}`
      };
    }
    const message =
      error instanceof Error ? error.message : "監査ログの取得に失敗しました。";
    return { kind: "error", message };
  }
}

export default async function AuditLogPage({ searchParams }: AuditLogPageProps = {}) {
  const { event_type: eventType, actor_id: actorId } = searchParams
    ? await searchParams
    : {};
  const selectedEventType = eventType && eventType.trim() ? eventType.trim() : undefined;
  const selectedActorId = actorId && actorId.trim() ? actorId.trim() : undefined;
  const state = await readAuditEvents(selectedEventType, selectedActorId);
  const allFilterActive = selectedEventType === undefined && selectedActorId === undefined;

  return (
    <section aria-label="監査ログ" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">監査ログ</h1>
        <p className="mt-2 text-sm text-muted">
          {state.kind === "ok"
            ? `${state.total} 件の audit event を payload key のみで表示しています。`
            : "監査ログの取得に失敗しました"}
        </p>
      </header>

      <div className="flex flex-wrap gap-2" aria-label="監査ログフィルター">
        <FilterLink href="/audit" active={allFilterActive}>
          すべて
        </FilterLink>
        {[
          "policy_decision_created",
          "approval_decided",
          "runner_blocked",
          "provider_blocked",
          "secret_capability_redeemed"
        ].map((value) => (
          <FilterLink
            key={value}
            href={`/audit?event_type=${value}`}
            active={selectedEventType === value}
          >
            {value}
          </FilterLink>
        ))}
      </div>

      {state.kind === "error" ? (
        <article role="status" className="rounded-md border border-attention bg-amber-50 p-4">
          <h2 className="text-base font-semibold text-attention">監査ログを表示できません</h2>
          <p className="mt-1 text-sm text-muted">{state.message}</p>
        </article>
      ) : state.events.length === 0 ? (
        <article className="rounded-md border border-base p-4 text-sm text-muted">
          条件に一致する audit event はありません。
        </article>
      ) : (
        <article className="overflow-x-auto rounded-lg border border-line bg-panel shadow-sm">
          <table className="min-w-full divide-y divide-line text-sm">
            <caption className="sr-only">
              event_type、actor_id、reason_code、payload_keys、redaction status を含む監査 event。
            </caption>
            <thead className="bg-panel-muted text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-4 py-3 text-left font-medium">event_type</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">actor_id</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">reason_code</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">payload_keys</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">redaction</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">created_at</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {state.events.map((event) => (
                <tr key={event.id} className="align-top hover:bg-panel-muted">
                  <th scope="row" className="px-4 py-3 text-left">
                    <code className="font-mono text-xs font-semibold text-ink">
                      {event.event_type}
                    </code>
                  </th>
                  <td className="px-4 py-3">
                    {event.actor_id ? (
                      <code className="font-mono text-xs text-muted">{event.actor_id}</code>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <code className="font-mono text-xs text-muted">
                      {event.reason_code ?? "—"}
                    </code>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">
                    {event.payload_keys.length > 0 ? event.payload_keys.join(", ") : "—"}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">
                    {event.payload_redaction_status}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted">
                    {formatDate(event.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
      )}
    </section>
  );
}

function FilterLink({
  href,
  active,
  children
}: {
  href: string;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={
        active
          ? "rounded-md bg-teal-50 px-3 py-2 text-sm font-semibold text-accent"
          : "rounded-md border border-line px-3 py-2 text-sm font-medium text-muted hover:bg-panel-muted"
      }
      href={href as Route}
    >
      {children}
    </Link>
  );
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toISOString().slice(0, 16).replace("T", " ");
  } catch {
    return iso;
  }
}
