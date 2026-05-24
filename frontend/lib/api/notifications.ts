import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";

const NotificationItemSchema = z.object({
  id: z.string().uuid(),
  event_type: z.string(),
  payload: z.record(z.string(), z.unknown()),
  created_at: z.string(),
  read_at: z.string().nullable()
});

export type NotificationItem = z.infer<typeof NotificationItemSchema>;

export const NotificationSeverityEnum = z.enum(["info", "low", "medium", "high", "critical"]);

export const NotificationRequiredActionEnum = z.enum([
  "acknowledge",
  "review_approval",
  "inspect_run",
  "resolve_blocker",
  "external_followup"
]);

export const NotificationTriageStateEnum = z.enum(["open", "snoozed", "resolved", "all"]);

export const NotificationTriageItemSchema = z.object({
  id: z.string().uuid(),
  event_type: z.string(),
  payload_keys: z.array(z.string()),
  payload_redaction_status: z.literal("keys_only"),
  severity: NotificationSeverityEnum,
  required_action: NotificationRequiredActionEnum,
  due_at: z.string().nullable(),
  snoozed_until: z.string().nullable(),
  resolved_at: z.string().nullable(),
  resolved_by_actor_id: z.string().uuid().nullable(),
  created_at: z.string(),
  read_at: z.string().nullable()
});

export type NotificationSeverity = z.infer<typeof NotificationSeverityEnum>;
export type NotificationRequiredAction = z.infer<typeof NotificationRequiredActionEnum>;
export type NotificationTriageState = z.infer<typeof NotificationTriageStateEnum>;
export type NotificationTriageItem = z.infer<typeof NotificationTriageItemSchema>;

const BadgeCountSchema = z.object({
  unread_count: z.number().int().nonnegative()
});

export type BadgeCount = z.infer<typeof BadgeCountSchema>;

export async function listNotifications(): Promise<NotificationItem[]> {
  return fetchBackendJson("/api/v1/notifications", z.array(NotificationItemSchema), {
    headers: { accept: "application/json" }
  });
}

export async function listNotificationTriage(
  options: { state?: NotificationTriageState } = {}
): Promise<NotificationTriageItem[]> {
  const params = new URLSearchParams();
  if (options.state) {
    params.set("state", NotificationTriageStateEnum.parse(options.state));
  }
  const query = params.toString();
  const path = query ? `/api/v1/notifications/triage?${query}` : "/api/v1/notifications/triage";
  return fetchBackendJson(path as `/${string}`, z.array(NotificationTriageItemSchema), {
    headers: { accept: "application/json" }
  });
}

export async function getBadgeCount(): Promise<BadgeCount> {
  return fetchBackendJson("/api/v1/notifications/badge_count", BadgeCountSchema, {
    headers: { accept: "application/json" }
  });
}

export async function markNotificationRead(notificationId: string): Promise<NotificationItem> {
  return fetchBackendJson(
    `/api/v1/notifications/${notificationId}/mark_read`,
    NotificationItemSchema,
    {
      method: "POST",
      headers: { accept: "application/json" }
    }
  );
}

export async function snoozeNotification(
  notificationId: string,
  body: { snoozed_until: string }
): Promise<NotificationTriageItem> {
  return fetchBackendJson(
    `/api/v1/notifications/${notificationId}/snooze`,
    NotificationTriageItemSchema,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json"
      },
      body: JSON.stringify(
        z
          .object({
            snoozed_until: z.string()
          })
          .parse(body)
      )
    }
  );
}

export async function resolveNotification(
  notificationId: string,
  body: { resolution_note?: string | null } = {}
): Promise<NotificationTriageItem> {
  return fetchBackendJson(
    `/api/v1/notifications/${notificationId}/resolve`,
    NotificationTriageItemSchema,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json"
      },
      body: JSON.stringify(
        z
          .object({
            resolution_note: z.string().max(2000).nullable().optional()
          })
          .parse(body)
      )
    }
  );
}
