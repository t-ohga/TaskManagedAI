import { describe, expect, it } from "vitest";

import { dueDateBucket } from "@/lib/domain/due-date";

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

  it("時刻付き文字列でも先頭 YYYY-MM-DD で判定する", () => {
    expect(dueDateBucket("2026-06-01T00:00:00Z", REF, THRESHOLD)).toBe("overdue");
  });

  it("不正な日付形式は null (誤分類せず強調なしに倒す)", () => {
    expect(dueDateBucket("not-a-date", REF, THRESHOLD)).toBeNull();
    expect(dueDateBucket("2026-06-03", "garbage", THRESHOLD)).toBeNull();
    expect(dueDateBucket("", REF, THRESHOLD)).toBeNull();
  });
});
