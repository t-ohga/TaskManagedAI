"use client";

import { useTransition } from "react";

import { markNotificationReadAction } from "../_actions/mark-read";

import type { NotificationItem } from "@/lib/api/notifications";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";

export function NotificationListItem({ notification }: { notification: NotificationItem }) {
  const requestRefresh = useDeferredRouterRefresh();
  const [isPending, startTransition] = useTransition();
  const isRead = notification.read_at !== null;

  return (
    <li
      data-testid={`notification-${notification.id}`}
      data-read={isRead ? "true" : "false"}
      className={`rounded-lg border p-4 ${
        isRead ? "border-line bg-panel" : "border-accent bg-emerald-50 dark:bg-emerald-950/40"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold">{notification.event_type}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {new Date(notification.created_at).toLocaleString()}
          </p>
        </div>
        {!isRead ? (
          <form
            action={(formData) => {
              startTransition(async () => {
                await markNotificationReadAction(formData);
                // C-5: action 側 revalidatePath 撤去のため client full reload で表示同期 (draft 源なし)
                requestRefresh();
              });
            }}
          >
            <input type="hidden" name="notification_id" value={notification.id} />
            <button
              type="submit"
              disabled={isPending}
              className="rounded-md bg-accent px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
              data-testid={`mark-read-${notification.id}`}
            >
              {isPending ? "Marking..." : "Mark read"}
            </button>
          </form>
        ) : null}
      </div>
    </li>
  );
}

