"use server";

import {
  resolveNotification,
  snoozeNotification
} from "@/lib/api/notifications";

export type NotificationTriageActionResult =
  | { ok: true; notification_id: string }
  | { ok: false; error: string };

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const ALLOWED_SNOOZE_MINUTES = new Set([60, 1440]);

function readNotificationId(formData: FormData): string | null {
  const value = formData.get("notification_id");
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    return null;
  }
  return value;
}

// C-5 系統適用: Server Action 内 revalidatePath() は client transition の isPending を解除せず
// 確率的に未 commit になる Next.js 16 (16.2.6) + React 19 regression。撤去し、表示更新は呼び出し側の
// full reload (useDeferredRouterRefresh) に委譲する。navbar 通知バッジは full reload の layout 再取得で
// 更新される (撤去前: revalidateNotificationSurfaces = revalidatePath("/notifications") +
// revalidatePath("/", "layout"))。参照: vercel/next.js discussions #82289 / #88767。
// Next 修正後は呼び出し側 hook を router.refresh() へ戻すだけで復帰する。

export async function snoozeNotificationTriageAction(
  formData: FormData
): Promise<NotificationTriageActionResult> {
  const notificationId = readNotificationId(formData);
  if (notificationId === null) {
    return { ok: false, error: "通知 ID が不正です" };
  }

  const minutesValue = formData.get("snooze_minutes");
  const minutes = typeof minutesValue === "string" ? Number.parseInt(minutesValue, 10) : NaN;
  if (!ALLOWED_SNOOZE_MINUTES.has(minutes)) {
    return { ok: false, error: "スヌーズ時間が不正です" };
  }

  try {
    await snoozeNotification(notificationId, {
      snoozed_until: new Date(Date.now() + minutes * 60_000).toISOString()
    });
    return { ok: true, notification_id: notificationId };
  } catch (error: unknown) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "スヌーズに失敗しました"
    };
  }
}

export async function resolveNotificationTriageAction(
  formData: FormData
): Promise<NotificationTriageActionResult> {
  const notificationId = readNotificationId(formData);
  if (notificationId === null) {
    return { ok: false, error: "通知 ID が不正です" };
  }

  try {
    await resolveNotification(notificationId, { resolution_note: null });
    return { ok: true, notification_id: notificationId };
  } catch (error: unknown) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "解決に失敗しました"
    };
  }
}
