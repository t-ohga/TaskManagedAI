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

const BadgeCountSchema = z.object({
  unread_count: z.number().int().nonnegative()
});

export type BadgeCount = z.infer<typeof BadgeCountSchema>;

export async function listNotifications(): Promise<NotificationItem[]> {
  return fetchBackendJson("/api/v1/notifications", z.array(NotificationItemSchema), {
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

