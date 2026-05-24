"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { markNotificationReadAction } from "../_actions/mark-read";
import {
  resolveNotificationTriageAction,
  snoozeNotificationTriageAction,
  type NotificationTriageActionResult
} from "../_actions/triage";

import type { NotificationTriageItem } from "@/lib/api/notifications";
import {
  formatNotificationRequiredAction,
  formatNotificationSeverity
} from "@/lib/i18n/notification-labels";

type NotificationTriageListItemProps = {
  notification: NotificationTriageItem;
};

export function NotificationTriageListItem({ notification }: NotificationTriageListItemProps) {
  const router = useRouter();
  const [result, setResult] = useState<NotificationTriageActionResult | null>(null);
  const [isPending, startTransition] = useTransition();
  const isRead = notification.read_at !== null;
  const isResolved = notification.resolved_at !== null;

  function runAction(
    formData: FormData,
    action: (formData: FormData) => Promise<NotificationTriageActionResult>
  ): void {
    setResult(null);
    startTransition(() => {
      void action(formData)
        .then((nextResult) => {
          setResult(nextResult);
          if (nextResult.ok) {
            router.refresh();
          }
        })
        .catch((error: unknown) => {
          setResult({
            ok: false,
            error: error instanceof Error ? error.message : "通知の更新に失敗しました"
          });
        });
    });
  }

  function markRead(formData: FormData): void {
    setResult(null);
    startTransition(() => {
      void markNotificationReadAction(formData)
        .then(() => {
          router.refresh();
        })
        .catch((error: unknown) => {
          setResult({
            ok: false,
            error: error instanceof Error ? error.message : "既読化に失敗しました"
          });
        });
    });
  }

  return (
    <li
      data-testid={`notification-triage-${notification.id}`}
      data-read={isRead ? "true" : "false"}
      data-resolved={isResolved ? "true" : "false"}
      className={`rounded-lg border bg-panel p-4 shadow-sm ${severityBorderClass(
        notification.severity
      )}`}
    >
      <div className="grid gap-4 md:grid-cols-[1fr_auto]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-md px-2 py-1 text-xs font-semibold ${severityBadgeClass(
                notification.severity
              )}`}
            >
              {formatNotificationSeverity(notification.severity)}
            </span>
            <span className="rounded-md bg-panel-muted px-2 py-1 text-xs font-semibold text-muted">
              {formatNotificationRequiredAction(notification.required_action)}
            </span>
            {isResolved ? (
              <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                解決済み
              </span>
            ) : null}
          </div>

          <p className="mt-3 break-all text-sm font-semibold">{notification.event_type}</p>
          <dl className="mt-2 grid gap-1 text-xs text-muted sm:grid-cols-2">
            <div>
              <dt className="font-medium text-foreground">作成</dt>
              <dd>{formatDateTime(notification.created_at)}</dd>
            </div>
            {notification.due_at ? (
              <div>
                <dt className="font-medium text-foreground">期限</dt>
                <dd>{formatDateTime(notification.due_at)}</dd>
              </div>
            ) : null}
            {notification.snoozed_until ? (
              <div>
                <dt className="font-medium text-foreground">スヌーズ</dt>
                <dd>{formatDateTime(notification.snoozed_until)}</dd>
              </div>
            ) : null}
            {notification.resolved_at ? (
              <div>
                <dt className="font-medium text-foreground">解決</dt>
                <dd>{formatDateTime(notification.resolved_at)}</dd>
              </div>
            ) : null}
          </dl>

          <div className="mt-3 flex flex-wrap gap-2">
            {notification.payload_keys.map((key) => (
              <span
                key={key}
                className="rounded-md border border-line bg-white px-2 py-1 font-mono text-xs text-muted"
              >
                {key}
              </span>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-start gap-2 md:justify-end">
          {!isRead ? (
            <form action={markRead}>
              <input type="hidden" name="notification_id" value={notification.id} />
              <button
                type="submit"
                disabled={isPending}
                className="rounded-md border border-line bg-white px-3 py-2 text-sm font-semibold text-muted outline-offset-2 hover:bg-panel-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                既読
              </button>
            </form>
          ) : null}

          {!isResolved ? (
            <>
              <form
                action={(formData) => {
                  runAction(formData, snoozeNotificationTriageAction);
                }}
              >
                <input type="hidden" name="notification_id" value={notification.id} />
                <input type="hidden" name="snooze_minutes" value="60" />
                <button
                  type="submit"
                  disabled={isPending}
                  className="rounded-md border border-line bg-white px-3 py-2 text-sm font-semibold text-muted outline-offset-2 hover:bg-panel-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  1時間スヌーズ
                </button>
              </form>
              <form
                action={(formData) => {
                  runAction(formData, resolveNotificationTriageAction);
                }}
              >
                <input type="hidden" name="notification_id" value={notification.id} />
                <button
                  type="submit"
                  disabled={isPending}
                  className="rounded-md bg-accent px-3 py-2 text-sm font-semibold text-white outline-offset-2 hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  解決
                </button>
              </form>
            </>
          ) : null}
        </div>
      </div>

      {result && !result.ok ? (
        <p className="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-700" role="status">
          {result.error}
        </p>
      ) : null}
    </li>
  );
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

function severityBorderClass(severity: NotificationTriageItem["severity"]): string {
  switch (severity) {
    case "critical":
      return "border-danger";
    case "high":
      return "border-attention";
    case "medium":
      return "border-accent";
    case "low":
    case "info":
      return "border-line";
  }
}

function severityBadgeClass(severity: NotificationTriageItem["severity"]): string {
  switch (severity) {
    case "critical":
      return "bg-rose-50 text-danger";
    case "high":
      return "bg-amber-50 text-attention";
    case "medium":
      return "bg-teal-50 text-accent";
    case "low":
      return "bg-slate-100 text-muted";
    case "info":
      return "bg-panel-muted text-muted";
  }
}
