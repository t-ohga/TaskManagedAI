import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";
import { isValidYmd } from "@/lib/domain/due-date";

// A-7 (ADR-00045): 期限リマインダー集約 (read-only、on-read 派生) + 一覧用 date_context。
// response 全 field を Zod で必須検証 (data 完全性: 不完全を完全と見せない)。malformed / auth 失効 /
// schema drift は parse で throw し、呼出側が degraded (ok/error) に倒す (fail-closed)。

// 実在する暦日 (YYYY-MM-DD) のみ許容 (adversarial R1 F-001)。非実在日 (2026-13-40 等) を取得失敗に
// 倒し、基準日 authority が壊れた状態で赤/橙を誤表示しない。
const ymdString = z.string().refine(isValidYmd, { message: "invalid calendar date (YYYY-MM-DD)" });
// reminder window は非負かつ妥当な上限内 (壊れた threshold で window を誤拡大しない)。
const thresholdDaysSchema = z.number().int().min(0).max(366);

const ReminderItemSchema = z.object({
  ticket_id: z.string(),
  project_id: z.string(),
  slug: z.string(),
  title: z.string(),
  status: z.string(),
  priority: z.string().nullable(),
  due_date: ymdString,
  days_until: z.number().int()
});

export type ReminderItem = z.infer<typeof ReminderItemSchema>;

// bucket 別 (plan-review R1 F-001): count は SQL COUNT (正確)、items は bucket ごとに独立 cap、
// truncated は count > items.length。overdue が due_today / upcoming の items を枯渇させない。
const ReminderBucketSchema = z.object({
  count: z.number().int(),
  truncated: z.boolean(),
  items: z.array(ReminderItemSchema)
});

export type ReminderBucket = z.infer<typeof ReminderBucketSchema>;

export const ReminderSummarySchema = z.object({
  reference_date: ymdString,
  threshold_days: thresholdDaysSchema,
  overdue: ReminderBucketSchema,
  due_today: ReminderBucketSchema,
  upcoming: ReminderBucketSchema
});

export type ReminderSummary = z.infer<typeof ReminderSummarySchema>;

export async function fetchReminders(): Promise<ReminderSummary> {
  return fetchBackendJson("/api/v1/me/reminders", ReminderSummarySchema);
}

// 一覧画面用の単一 "today" authority (R2 F-002)。reference_date (Asia/Tokyo 暦日) + reminder window。
// 一覧 page はこれを一度だけ取得し、全 ticket row の期限強調に同一基準を適用する。
export const DateContextSchema = z.object({
  reference_date: ymdString,
  threshold_days: thresholdDaysSchema
});

export type DateContext = z.infer<typeof DateContextSchema>;

export async function fetchDateContext(): Promise<DateContext> {
  return fetchBackendJson("/api/v1/me/date_context", DateContextSchema);
}
