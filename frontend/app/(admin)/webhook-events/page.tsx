import { getCurrentProjectId } from "@/lib/api/session";
import { loadWebhookEvents } from "@/lib/api/webhook-events";
import {
  ciStateTone,
  webhookEventKindLabel,
  webhookEventReference,
  type CiStateTone,
  type WebhookEventRead
} from "@/lib/domain/webhook-event";

export const dynamic = "force-dynamic";

const TONE_CLASS: Record<CiStateTone, string> = {
  success: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  failure: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  pending: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  neutral: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
};

// received_at は固定の ISO timestamp (server clock 採番、"now" 由来ではない) なので Server Component で
// 整形しても純粋。無効値は raw を echo せず空文字に倒す。
function formatReceivedAt(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function StateBadge({ state }: { state: string | null }) {
  if (state === null) return null;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASS[ciStateTone(state)]}`}
    >
      {state}
    </span>
  );
}

function WebhookEventRow({ event }: { event: WebhookEventRead }) {
  const reference = webhookEventReference(event);
  return (
    <li className="flex flex-col gap-1 border-b border-gray-100 py-3 dark:border-gray-800 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300">
            {webhookEventKindLabel(event.event_kind)}
          </span>
          {reference ? (
            <span className="font-mono text-sm text-gray-600 dark:text-gray-400">{reference}</span>
          ) : null}
          <StateBadge state={event.state} />
        </div>
        {event.title ? (
          <p className="truncate text-sm text-gray-900 dark:text-gray-100">{event.title}</p>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
        {event.sender_login ? <span>@{event.sender_login}</span> : null}
        <time dateTime={event.received_at}>{formatReceivedAt(event.received_at)}</time>
      </div>
    </li>
  );
}

export default async function WebhookEventsPage() {
  const projectId = await getCurrentProjectId();
  const result = await loadWebhookEvents(projectId, { limit: 100 });

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-6">
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Webhook アクティビティ</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          GitHub の PR / CI イベント (received 順)。表示は best-effort で、ingress の認証には影響しません。
        </p>
      </header>

      {!result.ok ? (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300"
        >
          アクティビティの取得に失敗しました。時間をおいて再読み込みしてください。
        </div>
      ) : result.data.items.length === 0 ? (
        <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600 dark:border-gray-800 dark:bg-gray-900/40 dark:text-gray-400">
          まだ Webhook イベントはありません。
        </p>
      ) : (
        <ul className="rounded-md border border-gray-200 bg-white px-4 dark:border-gray-800 dark:bg-gray-900">
          {result.data.items.map((event) => (
            <WebhookEventRow key={event.id} event={event} />
          ))}
        </ul>
      )}
    </main>
  );
}
