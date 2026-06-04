import Link from "next/link";
import type { Route } from "next";

import type { ReminderBucket, ReminderItem, ReminderSummary } from "@/lib/api/reminders";

// A-7 (ADR-00045): dashboard の期限リマインダー section (read-only)。bucket 別 (overdue /
// due_today / upcoming) に count + 上位 items を表示し、bucket 別 truncated を「他に N 件」で明示する
// (plan-review R1 F-001: silent truncation 回避)。取得失敗 (ok:false) は page 側で degraded 表示。

type BucketStyle = {
  title: string;
  badge: string;
  border: string;
};

const BUCKET_STYLES: Record<"overdue" | "due_today" | "upcoming", BucketStyle> = {
  overdue: {
    title: "期限超過",
    badge: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300",
    border: "border-red-200 dark:border-red-800",
  },
  due_today: {
    title: "本日期限",
    badge: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300",
    border: "border-amber-200 dark:border-amber-800",
  },
  upcoming: {
    title: "まもなく期限",
    badge: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300",
    border: "border-blue-200 dark:border-blue-800",
  },
};

function relativeDueLabel(bucket: "overdue" | "due_today" | "upcoming", item: ReminderItem): string {
  if (bucket === "due_today") return "本日";
  if (bucket === "overdue") return `${Math.abs(item.days_until)}日超過`;
  return `あと${item.days_until}日`;
}

function BucketBlock({
  bucketKey,
  bucket,
}: {
  bucketKey: "overdue" | "due_today" | "upcoming";
  bucket: ReminderBucket;
}) {
  if (bucket.count === 0) return null;
  const style = BUCKET_STYLES[bucketKey];
  // bucket 別 truncated: count > items 長 のとき残件数を明示 (silent truncation 回避、R1 F-001)。
  const remaining = bucket.count - bucket.items.length;
  return (
    <div className={`rounded-md border ${style.border} bg-panel p-3`}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{style.title}</h3>
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums ${style.badge}`}>
          {bucket.count}
        </span>
      </div>
      <ul className="mt-2 divide-y divide-line">
        {bucket.items.map((item) => (
          <li key={item.ticket_id} className="flex items-center justify-between gap-3 py-1.5">
            <Link
              href={`/tickets/${item.ticket_id}` as Route}
              className="min-w-0 truncate text-sm text-accent hover:underline"
            >
              {item.title}
            </Link>
            <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
              {relativeDueLabel(bucketKey, item)}
            </span>
          </li>
        ))}
      </ul>
      {remaining > 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">他に {remaining} 件</p>
      ) : null}
    </div>
  );
}

export function RemindersPanel({ reminders }: { reminders: ReminderSummary }) {
  const total =
    reminders.overdue.count + reminders.due_today.count + reminders.upcoming.count;
  return (
    <section aria-label="期限リマインダー" className="rounded-lg border border-line bg-panel p-5 shadow-sm">
      <div className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold">期限リマインダー</h2>
        <span className="text-xs text-muted-foreground">
          {reminders.reference_date} 基準 / {reminders.threshold_days}日以内
        </span>
      </div>
      {total === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">期限が近い・超過したチケットはありません。</p>
      ) : (
        <div className="mt-3 grid gap-3">
          <BucketBlock bucketKey="overdue" bucket={reminders.overdue} />
          <BucketBlock bucketKey="due_today" bucket={reminders.due_today} />
          <BucketBlock bucketKey="upcoming" bucket={reminders.upcoming} />
        </div>
      )}
    </section>
  );
}
