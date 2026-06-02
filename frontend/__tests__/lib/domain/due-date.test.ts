import { describe, expect, it } from "vitest";

import { dueDateBucket, isReminderActionableStatus, ticketDueBucket } from "@/lib/domain/due-date";

// A-7 (ADR-00045): dueDateBucket は backend compute_reminder_bucket と同一 semantics。
// 暦日文字列比較で overdue / due_today / upcoming / null を返す (window 外 = null)。
const REF = "2026-06-02";
const THRESHOLD = 7;

describe("dueDateBucket (ADR-00045 期限 bucket)", () => {
  it("due < today は overdue (下限なし)", () => {
    expect(dueDateBucket("2026-06-01", REF, THRESHOLD)).toBe("overdue");
    expect(dueDateBucket("2025-01-01", REF, THRESHOLD)).toBe("overdue");
  });

  it("due == today は due_today", () => {
    expect(dueDateBucket("2026-06-02", REF, THRESHOLD)).toBe("due_today");
  });

  it("today < due <= today + threshold は upcoming", () => {
    expect(dueDateBucket("2026-06-03", REF, THRESHOLD)).toBe("upcoming");
    // 上限境界 (today + 7) は upcoming
    expect(dueDateBucket("2026-06-09", REF, THRESHOLD)).toBe("upcoming");
  });

  it("due > today + threshold は null (window 外、off-by-one)", () => {
    // today + 8 は対象外
    expect(dueDateBucket("2026-06-10", REF, THRESHOLD)).toBeNull();
    expect(dueDateBucket("2027-01-01", REF, THRESHOLD)).toBeNull();
  });

  it("threshold を変えると window 上限が連動する", () => {
    expect(dueDateBucket("2026-06-05", REF, 3)).toBe("upcoming");
    expect(dueDateBucket("2026-06-06", REF, 3)).toBeNull();
  });

  it("月またぎ / 年またぎでも UTC 暦日加算で正しく判定する", () => {
    // 月末基準で window が翌月へ跨ぐ
    expect(dueDateBucket("2026-07-02", "2026-06-28", THRESHOLD)).toBe("upcoming");
    expect(dueDateBucket("2026-07-06", "2026-06-28", THRESHOLD)).toBeNull();
    // 年またぎ
    expect(dueDateBucket("2027-01-02", "2026-12-28", THRESHOLD)).toBe("upcoming");
  });

  it("timestamp / 余分な suffix は null (R2 F-001: due_date は date 型、schema drift を fail-closed)", () => {
    // backend の due_date は厳密に YYYY-MM-DD。timestamp / junk suffix は drift として拒否し、
    // JST 深夜境界で別暦日に誤分類しない。
    expect(dueDateBucket("2026-06-01T00:00:00Z", REF, THRESHOLD)).toBeNull();
    expect(dueDateBucket("2026-06-01junk", REF, THRESHOLD)).toBeNull();
    expect(dueDateBucket("2026-06-03", "2026-06-02T23:30:00Z", THRESHOLD)).toBeNull();
  });

  it("不正な日付形式は null (誤分類せず強調なしに倒す)", () => {
    expect(dueDateBucket("not-a-date", REF, THRESHOLD)).toBeNull();
    expect(dueDateBucket("2026-06-03", "garbage", THRESHOLD)).toBeNull();
    expect(dueDateBucket("", REF, THRESHOLD)).toBeNull();
    expect(dueDateBucket("2026-6-3", REF, THRESHOLD)).toBeNull(); // 非ゼロパディング
  });

  it("非実在の暦日は null (R1 F-001: JS Date 正規化で別日に化けて誤分類しない)", () => {
    // prefix だけ正しい非実在日 (13 月 / 2 月 31 日) を弾く。
    expect(dueDateBucket("2026-13-40", REF, THRESHOLD)).toBeNull();
    expect(dueDateBucket("2026-02-31", REF, THRESHOLD)).toBeNull();
    // 壊れた reference_date でも誤分類せず null。
    expect(dueDateBucket("2026-06-03", "2026-00-10", THRESHOLD)).toBeNull();
    expect(dueDateBucket("2026-06-03", "2026-02-30", THRESHOLD)).toBeNull();
  });

  it("不正な threshold (負 / 非整数) は null", () => {
    expect(dueDateBucket("2026-06-03", REF, -1)).toBeNull();
    expect(dueDateBucket("2026-06-03", REF, 1.5)).toBeNull();
  });
});

describe("isReminderActionableStatus / ticketDueBucket (R3 F-001 actionable ゲート)", () => {
  it("actionable status は open/in_progress/blocked/review のみ", () => {
    for (const s of ["open", "in_progress", "blocked", "review"]) {
      expect(isReminderActionableStatus(s)).toBe(true);
    }
    for (const s of ["closed", "cancelled", "unknown"]) {
      expect(isReminderActionableStatus(s)).toBe(false);
    }
  });

  it("closed / cancelled は過去/本日期限でも null (neutral、backend reminders と整合)", () => {
    expect(ticketDueBucket("2026-05-01", "closed", REF, THRESHOLD)).toBeNull();
    expect(ticketDueBucket("2026-06-02", "cancelled", REF, THRESHOLD)).toBeNull();
    expect(ticketDueBucket("2026-05-01", "closed", REF, THRESHOLD)).not.toBe("overdue");
  });

  it("actionable status は通常通り bucket を返す", () => {
    expect(ticketDueBucket("2026-05-01", "open", REF, THRESHOLD)).toBe("overdue");
    expect(ticketDueBucket("2026-06-02", "in_progress", REF, THRESHOLD)).toBe("due_today");
    expect(ticketDueBucket("2026-06-04", "review", REF, THRESHOLD)).toBe("upcoming");
  });

  it("due_date なし / 基準日未取得 (date_context 失敗) は null", () => {
    expect(ticketDueBucket(null, "open", REF, THRESHOLD)).toBeNull();
    expect(ticketDueBucket("2026-05-01", "open", undefined, THRESHOLD)).toBeNull();
    expect(ticketDueBucket("2026-05-01", "open", REF, undefined)).toBeNull();
  });
});
