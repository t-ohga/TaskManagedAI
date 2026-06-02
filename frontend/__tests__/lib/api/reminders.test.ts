import { describe, expect, it } from "vitest";

import { DateContextSchema, ReminderSummarySchema } from "@/lib/api/reminders";

// A-7 (ADR-00045): reminder / date_context の response schema は data 完全性 (fail-closed) を担保する。
// malformed (bucket 欠落 / count 型不正 / items 非配列 / reference_date 欠落) は safeParse 失敗 →
// loader (fetchBackendJson が schema.parse) が throw し、dashboard / 一覧 page が degraded に倒れる。

function validBucket(count: number, items: unknown[] = []) {
  return { count, truncated: count > items.length, items };
}

function validItem() {
  return {
    ticket_id: "11111111-1111-1111-1111-111111111111",
    project_id: "22222222-2222-2222-2222-222222222222",
    slug: "fix-login",
    title: "ログイン修正",
    status: "open",
    priority: "high",
    due_date: "2026-06-01",
    days_until: -1
  };
}

const validSummary = {
  reference_date: "2026-06-02",
  threshold_days: 7,
  overdue: validBucket(1, [validItem()]),
  due_today: validBucket(0),
  upcoming: validBucket(0)
};

describe("ReminderSummarySchema (fail-closed)", () => {
  it("正常 response を parse する", () => {
    const parsed = ReminderSummarySchema.safeParse(validSummary);
    expect(parsed.success).toBe(true);
  });

  it("bucket 欠落は reject", () => {
    const missingBucket: Record<string, unknown> = { ...validSummary };
    delete missingBucket.overdue;
    expect(ReminderSummarySchema.safeParse(missingBucket).success).toBe(false);
  });

  it("count 型不正 (string) は reject", () => {
    const bad = { ...validSummary, overdue: { count: "1", truncated: false, items: [] } };
    expect(ReminderSummarySchema.safeParse(bad).success).toBe(false);
  });

  it("items が配列でない場合は reject (絞り込み欠落を空と誤認しない)", () => {
    const bad = { ...validSummary, upcoming: { count: 0, truncated: false, items: null } };
    expect(ReminderSummarySchema.safeParse(bad).success).toBe(false);
  });

  it("reference_date 欠落は reject (基準日なしを完全と見せない)", () => {
    const missingRef: Record<string, unknown> = { ...validSummary };
    delete missingRef.reference_date;
    expect(ReminderSummarySchema.safeParse(missingRef).success).toBe(false);
  });

  it("priority は nullable だが他 item field 欠落は reject", () => {
    const itemNoTitle = { ...validItem(), title: undefined };
    const bad = { ...validSummary, overdue: validBucket(1, [itemNoTitle]) };
    expect(ReminderSummarySchema.safeParse(bad).success).toBe(false);
    const itemNullPriority = { ...validItem(), priority: null };
    const ok = { ...validSummary, overdue: validBucket(1, [itemNullPriority]) };
    expect(ReminderSummarySchema.safeParse(ok).success).toBe(true);
  });

  it("非実在の reference_date / item due_date は reject (R1 F-001、誤分類を取得失敗に倒す)", () => {
    expect(
      ReminderSummarySchema.safeParse({ ...validSummary, reference_date: "2026-13-40" }).success
    ).toBe(false);
    const badItem = { ...validItem(), due_date: "2026-02-31" };
    expect(
      ReminderSummarySchema.safeParse({ ...validSummary, overdue: validBucket(1, [badItem]) }).success
    ).toBe(false);
  });

  it("timestamp / junk suffix の reference_date / due_date は reject (R2 F-001、date 型 drift)", () => {
    expect(
      ReminderSummarySchema.safeParse({ ...validSummary, reference_date: "2026-06-02T00:00:00Z" })
        .success
    ).toBe(false);
    const tsItem = { ...validItem(), due_date: "2026-06-01T12:00:00Z" };
    expect(
      ReminderSummarySchema.safeParse({ ...validSummary, overdue: validBucket(1, [tsItem]) }).success
    ).toBe(false);
  });

  it("threshold_days が負 / 上限超は reject", () => {
    expect(ReminderSummarySchema.safeParse({ ...validSummary, threshold_days: -1 }).success).toBe(
      false
    );
    expect(ReminderSummarySchema.safeParse({ ...validSummary, threshold_days: 9999 }).success).toBe(
      false
    );
  });
});

describe("DateContextSchema (fail-closed)", () => {
  it("正常 response を parse する", () => {
    expect(
      DateContextSchema.safeParse({ reference_date: "2026-06-02", threshold_days: 7 }).success
    ).toBe(true);
  });

  it("reference_date 欠落は reject", () => {
    expect(DateContextSchema.safeParse({ threshold_days: 7 }).success).toBe(false);
  });

  it("threshold_days 型不正は reject", () => {
    expect(
      DateContextSchema.safeParse({ reference_date: "2026-06-02", threshold_days: "7" }).success
    ).toBe(false);
  });

  it("非実在の reference_date は reject (基準日 authority 破損を取得失敗に倒す、R1 F-001)", () => {
    expect(
      DateContextSchema.safeParse({ reference_date: "2026-02-31", threshold_days: 7 }).success
    ).toBe(false);
  });

  it("timestamp / junk suffix の reference_date は reject (R2 F-001、date 型 drift)", () => {
    expect(
      DateContextSchema.safeParse({ reference_date: "2026-06-02T00:00:00Z", threshold_days: 7 })
        .success
    ).toBe(false);
    expect(
      DateContextSchema.safeParse({ reference_date: "2026-06-02junk", threshold_days: 7 }).success
    ).toBe(false);
  });
});
