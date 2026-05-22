import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

import { BackendApiError } from "@/lib/api/client";
import {
  AgentRunStatusEnum,
  listAgentRuns,
  type AgentRunListItem,
  type AgentRunStatus
} from "@/lib/api/agent-runs";

export const dynamic = "force-dynamic";

type AgentRunsPageProps = {
  searchParams?: Promise<{ status?: string; role?: string }>;
};

type RunsState =
  | {
      kind: "ok";
      runs: AgentRunListItem[];
      total: number;
      status?: AgentRunStatus;
      role?: string;
    }
  | { kind: "error"; message: string };

function parseStatus(value: string | undefined): AgentRunStatus | undefined {
  if (!value) return undefined;
  const parsed = AgentRunStatusEnum.safeParse(value);
  return parsed.success ? parsed.data : undefined;
}

async function readRuns(
  status: AgentRunStatus | undefined,
  role: string | undefined
): Promise<RunsState> {
  try {
    const options: {
      status?: AgentRunStatus;
      role?: string;
      limit: number;
      offset: number;
    } = { limit: 50, offset: 0 };
    if (status !== undefined) {
      options.status = status;
    }
    if (role !== undefined) {
      options.role = role;
    }
    const response = await listAgentRuns(options);
    return {
      kind: "ok",
      runs: response.items,
      total: response.total,
      ...(status !== undefined ? { status } : {}),
      ...(role !== undefined ? { role } : {})
    };
  } catch (error: unknown) {
    if (error instanceof BackendApiError) {
      return {
        kind: "error",
        message: `バックエンドが ${error.status} を返しました: ${error.message}`
      };
    }
    const message =
      error instanceof Error ? error.message : "AI 実行一覧の取得に失敗しました。";
    return { kind: "error", message };
  }
}

export default async function AgentRunsPage({ searchParams }: AgentRunsPageProps = {}) {
  const { status, role } = searchParams ? await searchParams : {};
  const selectedStatus = parseStatus(status);
  const selectedRole = role && role.trim().length > 0 ? role.trim() : undefined;
  const state = await readRuns(selectedStatus, selectedRole);
  const allFilterActive = selectedStatus === undefined && selectedRole === undefined;

  return (
    <section aria-label="AI 実行一覧" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">AI 実行</h1>
        <p className="mt-2 text-sm text-muted">
          {state.kind === "ok"
            ? `${state.total} 件の AgentRun を read-only で表示しています。`
            : "AI 実行一覧の取得に失敗しました"}
        </p>
      </header>

      <div className="flex flex-wrap gap-2" aria-label="AI 実行フィルター">
        <FilterLink href="/runs" active={allFilterActive}>
          すべて
        </FilterLink>
        {["queued", "running", "waiting_approval", "blocked", "completed", "failed"].map(
          (statusValue) => (
            <FilterLink
              key={statusValue}
              href={`/runs?status=${statusValue}`}
              active={selectedStatus === statusValue}
            >
              {formatStatus(statusValue)}
            </FilterLink>
          )
        )}
      </div>

      {state.kind === "error" ? (
        <article role="status" className="rounded-md border border-attention bg-amber-50 p-4">
          <h2 className="text-base font-semibold text-attention">AI 実行を表示できません</h2>
          <p className="mt-1 text-sm text-muted">{state.message}</p>
        </article>
      ) : state.runs.length === 0 ? (
        <article className="rounded-md border border-base p-4 text-sm text-muted">
          条件に一致する AI 実行はありません。
        </article>
      ) : (
        <article className="overflow-x-auto rounded-lg border border-line bg-panel shadow-sm">
          <table className="min-w-full divide-y divide-line text-sm">
            <thead className="bg-panel-muted text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-4 py-3 text-left font-medium">Run ID</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">状態</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">blocked_reason</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">role</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">last_progress</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">更新日時</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {state.runs.map((run) => (
                <tr key={run.id} className="hover:bg-panel-muted">
                  <th scope="row" className="px-4 py-3 text-left">
                    <Link
                      className="font-mono text-xs font-semibold text-accent hover:underline"
                      href={`/runs/${run.id}`}
                    >
                      {run.id}
                    </Link>
                  </th>
                  <td className="px-4 py-3">
                    <span className={`rounded-md px-2 py-1 text-xs font-semibold ${statusClass(run.status)}`}>
                      {formatStatus(run.status)}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted">
                    {run.blocked_reason ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">
                    {run.role_id ? `${run.role_scope ?? "unknown"}:${run.role_id}` : "未設定"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted">
                    {run.last_progress_at ? formatDate(run.last_progress_at) : "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted">
                    {formatDate(run.updated_at)}
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

function formatStatus(status: string): string {
  return status.replaceAll("_", " ");
}

function statusClass(status: string): string {
  switch (status) {
    case "blocked":
    case "failed":
    case "provider_refused":
    case "repair_exhausted":
      return "bg-rose-100 text-rose-800";
    case "waiting_approval":
    case "provider_incomplete":
      return "bg-amber-100 text-attention";
    case "completed":
      return "bg-emerald-100 text-emerald-800";
    case "running":
    case "gathering_context":
      return "bg-teal-50 text-accent";
    default:
      return "bg-slate-100 text-slate-800";
  }
}
