import Link from "next/link";

import {
  listNotificationTriage,
  type NotificationTriageItem,
  type NotificationTriageState
} from "@/lib/api/notifications";
import { formatNotificationTriageState } from "@/lib/i18n/notification-labels";

import { NotificationTriageListItem } from "./_components/notification-triage-list-item";

export const dynamic = "force-dynamic";

type NotificationsPageProps = {
  searchParams?: Promise<{ state?: string }>;
};

const TRIAGE_STATES: readonly NotificationTriageState[] = [
  "open",
  "snoozed",
  "resolved",
  "all"
];

function parseTriageState(value: string | undefined): NotificationTriageState {
  return TRIAGE_STATES.includes(value as NotificationTriageState)
    ? (value as NotificationTriageState)
    : "open";
}

export default async function NotificationsPage({
  searchParams
}: NotificationsPageProps = {}) {
  const { state } = searchParams ? await searchParams : {};
  const selectedState = parseTriageState(state);
  let notifications: NotificationTriageItem[];

  try {
    notifications = await listNotificationTriage({ state: selectedState });
  } catch (error: unknown) {
    return (
      <section aria-label="通知" className="grid gap-4">
        <h1 className="text-2xl font-semibold">通知</h1>
        <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">
          通知の取得に失敗しました: {error instanceof Error ? error.message : "不明なエラー"}
        </p>
      </section>
    );
  }

  return (
    <section aria-label="通知" className="grid gap-5">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">通知</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {formatNotificationTriageState(selectedState)} の通知を表示しています。
        </p>
      </header>

      <nav aria-label="通知状態" className="flex flex-wrap gap-2">
        {TRIAGE_STATES.map((stateValue) => {
          const isActive = stateValue === selectedState;
          return (
            <Link
              key={stateValue}
              aria-current={isActive ? "page" : undefined}
              className={
                isActive
                  ? "rounded-md bg-teal-50 px-3 py-2 text-sm font-semibold text-accent"
                  : "rounded-md border border-line px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-panel-muted"
              }
              href={`/notifications?state=${stateValue}`}
            >
              {formatNotificationTriageState(stateValue)}
            </Link>
          );
        })}
      </nav>

      {notifications.length === 0 ? (
        <p className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-700">
          通知はありません。
        </p>
      ) : (
        <ul className="grid gap-3" data-testid="notification-triage-list">
          {notifications.map((notification) => (
            <NotificationTriageListItem
              key={notification.id}
              notification={notification}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
