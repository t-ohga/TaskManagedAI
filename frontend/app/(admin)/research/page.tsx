import type { Route } from "next";
import Link from "next/link";

import {
  AdminPageShell,
  KeyboardReadinessStrip,
  Panel
} from "../_components/sprint9-admin-ui";
import {
  getAdminResearchProjectId,
  listResearchTasks,
  type ResearchTask,
  type ResearchTaskListResponse
} from "@/lib/api/research";
import { formatResearchStatus } from "@/lib/i18n/research-labels";
import { EmptyState } from "@/components/page-states";

export const dynamic = "force-dynamic";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toISOString();
}

function StatusBadge({ status }: { readonly status: ResearchTask["status"] }) {
  const tone =
    status === "completed"
      ? "border-teal-200 dark:border-teal-800 bg-teal-50 dark:bg-teal-950/40 text-accent"
      : status === "failed"
        ? "border-rose-200 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 text-danger"
        : "border-line bg-slate-50 dark:bg-slate-800 text-ink";

  return (
    <span className={`rounded-md border px-2 py-1 font-mono text-xs font-semibold ${tone}`}>
      {formatResearchStatus(status)}
    </span>
  );
}

function ResearchTaskTable({ tasks }: { readonly tasks: readonly ResearchTask[] }) {
  if (tasks.length === 0) {
    // O-5 (UI 監査 fix): 空状態に次アクションの導線を付ける。リサーチ task は MCP 経由で
    // 作成され、調査結果はチケットへ反映されるため、チケット一覧への遷移を促す。
    return (
      <EmptyState
        title="リサーチ task はまだありません"
        description="リサーチ task は MCP 経由で作成されます。調査結果はチケットの根拠として活用できます。"
        action={{ label: "チケット一覧へ", href: "/tickets" }}
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
        <caption className="sr-only">
          状態、タイトル、作成日時、project_id を含むリサーチ task 一覧。
        </caption>
        <thead className="bg-slate-50 dark:bg-slate-800 text-xs uppercase tracking-normal text-muted-foreground">
          <tr>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              状態 (status)
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              タイトル
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              作成日時 (created_at)
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              project_id
            </th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id} className="align-top">
              <td className="border-b border-line px-3 py-2">
                <StatusBadge status={task.status} />
              </td>
              <th scope="row" className="border-b border-line px-3 py-2 font-medium text-ink">
                <Link
                  className="outline-offset-2 hover:text-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  href={`/research/${task.id}` as Route}
                >
                  {task.title}
                </Link>
                <p className="mt-1 font-mono text-xs text-muted-foreground">{task.id}</p>
              </th>
              <td className="border-b border-line px-3 py-2 text-muted-foreground">
                <time dateTime={task.created_at}>{formatDate(task.created_at)}</time>
              </td>
              <td className="border-b border-line px-3 py-2">
                <code className="break-all font-mono text-xs text-ink">{task.project_id}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ErrorPanel({ error }: { readonly error: unknown }) {
  return (
    <Panel
      description="read-only Research API が表示可能な response を返しませんでした。"
      title="リサーチ読込エラー"
      titleId="research-load-error"
    >
      <p role="alert" className="rounded-md border border-rose-200 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-danger">
        リサーチ task の読込に失敗しました: {error instanceof Error ? error.message : "不明なエラー"}
      </p>
    </Panel>
  );
}

export default async function ResearchListPage() {
  let result: ResearchTaskListResponse;
  let loadError: unknown = null;

  try {
    result = await listResearchTasks();
  } catch (error) {
    result = { items: [], total: 0, limit: 50, offset: 0 };
    loadError = error;
  }

  const projectId = getAdminResearchProjectId();

  return (
    <AdminPageShell
      description={
        <>
          リサーチ・クレーム・エビデンス管理。対象 project は{" "}
          <code>{projectId}</code> です。Mutation UI は P1 まで defer しています。
        </>
      }
      eyebrow="管理 / リサーチ"
      regionLabel="リサーチ"
      title="リサーチ"
    >
      <KeyboardReadinessStrip current="リサーチ" />

      {loadError === null ? null : <ErrorPanel error={loadError} />}

      <Panel
        aside={
          <span className="rounded-md border border-line bg-panel px-3 py-2 font-mono text-xs text-muted-foreground">
            合計 {result.total}
          </span>
        }
        description="Project-scoped な GET-only 一覧です。tenant_id、project_id、actor_id は server side で解決します。"
        title="リサーチ task"
        titleId="research-task-list"
      >
        <ResearchTaskTable tasks={result.items} />
      </Panel>
    </AdminPageShell>
  );
}
