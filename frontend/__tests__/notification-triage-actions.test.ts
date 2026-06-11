import { afterEach, describe, expect, it, vi } from "vitest";

import {
  resolveNotificationTriageAction,
  snoozeNotificationTriageAction
} from "@/app/(admin)/notifications/_actions/triage";

const apiMocks = vi.hoisted(() => ({
  resolveNotification: vi.fn(),
  snoozeNotification: vi.fn()
}));

const cacheMocks = vi.hoisted(() => ({
  revalidatePath: vi.fn()
}));

vi.mock("next/cache", () => ({
  revalidatePath: cacheMocks.revalidatePath
}));

vi.mock("@/lib/api/notifications", () => ({
  resolveNotification: apiMocks.resolveNotification,
  snoozeNotification: apiMocks.snoozeNotification
}));

afterEach(() => {
  apiMocks.resolveNotification.mockReset();
  apiMocks.snoozeNotification.mockReset();
  cacheMocks.revalidatePath.mockReset();
  vi.useRealTimers();
});

function buildForm(values: Record<string, string>): FormData {
  const formData = new FormData();
  for (const [key, value] of Object.entries(values)) {
    formData.set(key, value);
  }
  return formData;
}

describe("notification triage server actions", () => {
  it("rejects invalid notification ids before calling the backend", async () => {
    const result = await resolveNotificationTriageAction(
      buildForm({ notification_id: "not-a-uuid" })
    );

    expect(result.ok).toBe(false);
    expect(apiMocks.resolveNotification).not.toHaveBeenCalled();
  });

  it("snoozes with a server-owned future timestamp", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-24T00:00:00Z"));
    apiMocks.snoozeNotification.mockResolvedValueOnce({});

    const notificationId = "00000000-0000-4000-8000-00000000b301";
    const result = await snoozeNotificationTriageAction(
      buildForm({
        notification_id: notificationId,
        snooze_minutes: "60"
      })
    );

    expect(result).toEqual({ ok: true, notification_id: notificationId });
    expect(apiMocks.snoozeNotification).toHaveBeenCalledWith(notificationId, {
      snoozed_until: "2026-05-24T01:00:00.000Z"
    });
    // C-5 系統適用: action 内 revalidatePath は撤去済 (表示更新は client full reload)。回帰防止に非呼出を検証。
    expect(cacheMocks.revalidatePath).not.toHaveBeenCalled();
  });

  it("resolves without sending a free-form note body", async () => {
    apiMocks.resolveNotification.mockResolvedValueOnce({});

    const notificationId = "00000000-0000-4000-8000-00000000b302";
    const result = await resolveNotificationTriageAction(
      buildForm({ notification_id: notificationId })
    );

    expect(result).toEqual({ ok: true, notification_id: notificationId });
    expect(apiMocks.resolveNotification).toHaveBeenCalledWith(notificationId, {
      resolution_note: null
    });
    // C-5 系統適用: action 内 revalidatePath は撤去済 (表示更新は client full reload)。回帰防止に非呼出を検証。
    expect(cacheMocks.revalidatePath).not.toHaveBeenCalled();
  });
});
