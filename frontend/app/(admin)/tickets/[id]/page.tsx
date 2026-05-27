import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchBackendRaw } from "@/lib/api/client";

export const dynamic = "force-dynamic";

type TicketDetailPageProps = {
  params: Promise<{ id: string }>;
};

type TicketDetail = {
  id: string;
  title: string;
  slug: string;
  status: string;
  description: string | null;
  priority: string | null;
  created_at: string | null;
  updated_at: string | null;
  project_id: string;
};

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    open: "bg-blue-50 text-blue-700",
    in_progress: "bg-amber-50 text-amber-700",
    closed: "bg-gray-100 text-gray-500",
    cancelled: "bg-red-50 text-red-600",
  };
  const labels: Record<string, string> = {
    open: "未着手",
    in_progress: "進行中",
    closed: "完了",
    cancelled: "中止",
  };
  return (
    <span
      className={`rounded-full px-3 py-1 text-sm font-medium ${colors[status] ?? "bg-gray-100 text-gray-600"}`}
    >
      {labels[status] ?? status}
    </span>
  );
}

async function loadTicket(id: string): Promise<TicketDetail | null> {
  try {
    const projectsRes = await fetchBackendRaw("/api/v1/me/projects");
    const projects = ((projectsRes as Record<string, unknown>)?.projects ?? []) as Array<Record<string, string>>;

    for (const p of projects) {
      const pid = String(p.project_id ?? p.id ?? "");
      try {
        const ticketsRes = await fetchBackendRaw(
          `/api/v1/projects/${pid}/tickets` as `/${string}`
        );
        const items = ((ticketsRes as Record<string, unknown>)?.items ?? []) as TicketDetail[];
        const found = items.find((t) => t.id === id);
        if (found) {
          return { ...found, project_id: pid };
        }
      } catch {
        continue;
      }
    }
    return null;
  } catch {
    return null;
  }
}

export default async function TicketDetailPage({ params }: TicketDetailPageProps) {
  const { id } = await params;
  const ticket = await loadTicket(id);

  if (!ticket) {
    notFound();
  }

  return (
    <section aria-label="チケット詳細" className="grid gap-6">
      <header className="grid gap-2">
        <div className="flex items-center gap-2 text-sm">
          <Link href="/tickets" className="text-accent hover:underline">
            チケット一覧
          </Link>
          <span className="text-muted-foreground">/</span>
          <span className="text-muted-foreground">{ticket.slug}</span>
        </div>
        <div className="flex items-center gap-4">
          <h1 className="text-3xl font-semibold tracking-normal">{ticket.title}</h1>
          {statusBadge(ticket.status)}
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">基本情報</h2>
          <dl className="mt-4 grid gap-3 text-sm">
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">チケット ID</dt>
              <dd className="font-mono text-xs">{ticket.id.slice(0, 8)}...</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">スラッグ</dt>
              <dd className="font-mono">{ticket.slug}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">ステータス</dt>
              <dd>{statusBadge(ticket.status)}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">優先度</dt>
              <dd>{ticket.priority ?? "未設定"}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">作成日</dt>
              <dd>
                {ticket.created_at
                  ? new Date(ticket.created_at).toLocaleString("ja-JP")
                  : "—"}
              </dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">更新日</dt>
              <dd>
                {ticket.updated_at
                  ? new Date(ticket.updated_at).toLocaleString("ja-JP")
                  : "—"}
              </dd>
            </div>
          </dl>
        </article>

        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">説明</h2>
          <div className="mt-4 text-sm leading-relaxed text-muted-foreground">
            {ticket.description ? (
              <p className="whitespace-pre-wrap">{ticket.description}</p>
            ) : (
              <p className="italic">説明はまだありません</p>
            )}
          </div>
        </article>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">ステータス変更</h2>
          <div className="mt-4 flex flex-wrap gap-2">
            {[
              { status: "open", label: "未着手", color: "bg-blue-100 text-blue-700 hover:bg-blue-200" },
              { status: "in_progress", label: "進行中", color: "bg-amber-100 text-amber-700 hover:bg-amber-200" },
              { status: "review", label: "レビュー", color: "bg-purple-100 text-purple-700 hover:bg-purple-200" },
              { status: "blocked", label: "ブロック", color: "bg-orange-100 text-orange-700 hover:bg-orange-200" },
              { status: "closed", label: "完了", color: "bg-emerald-100 text-emerald-700 hover:bg-emerald-200" },
              { status: "cancelled", label: "中止", color: "bg-gray-100 text-gray-600 hover:bg-gray-200" },
            ].map(({ status: s, label, color }) => (
              <span
                key={s}
                className={`cursor-default rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  ticket.status === s ? color + " ring-2 ring-offset-1 ring-accent" : color + " opacity-50"
                }`}
              >
                {label}
                {ticket.status === s && " ✓"}
              </span>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            ※ ステータス変更は MCP tool (ticket_update) または API 経由で行えます
          </p>
        </article>

        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">アクション</h2>
          <div className="mt-4 grid gap-2">
            <a
              href={`/tickets?project=${ticket.project_id}`}
              className="rounded-md border border-line px-4 py-2 text-center text-sm font-medium text-muted-foreground transition-colors hover:bg-slate-50"
            >
              プロジェクトの看板に戻る
            </a>
          </div>
        </article>
      </div>
    </section>
  );
}
