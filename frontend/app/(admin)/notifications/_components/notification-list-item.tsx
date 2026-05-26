"use client";

import { useTransition } from "react";

import { markNotificationReadAction } from "../_actions/mark-read";

import type { NotificationItem } from "@/lib/api/notifications";

export function NotificationListItem({ notification }: { notification: NotificationItem }) {
  const [isPending, startTransition] = useTransition();
  const isRead = notification.read_at !== null;

  return (
    <li
      data-testid={`notification-${notification.id}`}
      data-read={isRead ? "true" : "false"}
      className={`rounded-lg border p-4 ${
        isRead ? "border-line bg-panel" : "border-accent bg-emerald-50"
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
              startTransition(() => {
                void markNotificationReadAction(formData);
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

