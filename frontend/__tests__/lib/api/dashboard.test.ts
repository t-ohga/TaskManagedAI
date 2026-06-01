import { describe, expect, it } from "vitest";

import { foldTicketDisplayCounts, buildActivityTrendSeries } from "@/lib/api/dashboard";

function bucket(
  bucket_start: string,
  run_count: number,
  cost_usd: number | null,
  measured_run_count: number,
  unmeasured_run_count: number
) {
  return { bucket_start, run_count, cost_usd, measured_run_count, unmeasured_run_count };
}

describe("foldTicketDisplayCounts (ADR-00039 D-5 表示 bucket)", () => {
  it("in_progress = in_progress + blocked + review に折り畳む", () => {
    const out = foldTicketDisplayCounts([
      { status: "in_progress", count: 3 },
      { status: "blocked", count: 2 },
      { status: "review", count: 4 }
    ]);
    expect(out.in_progress).toBe(9);
    expect(out.open).toBe(0);
    expect(out.closed).toBe(0);
    expect(out.cancelled).toBe(0);
  });

  it("open / closed / cancelled はそのまま、未知 status は open に fallback", () => {
    const out = foldTicketDisplayCounts([
      { status: "open", count: 5 },
      { status: "closed", count: 7 },
      { status: "cancelled", count: 1 },
      { status: "weird_unknown", count: 2 }
    ]);
    expect(out.open).toBe(7); // 5 + 未知 2
    expect(out.closed).toBe(7);
    expect(out.cancelled).toBe(1);
    expect(out.in_progress).toBe(0);
  });

  it("4 bucket 合計が raw status_counts 合計 (ticket_total) と一致する (欠落・二重計上なし)", () => {
    const raw = [
      { status: "open", count: 5 },
      { status: "in_progress", count: 3 },
      { status: "blocked", count: 2 },
      { status: "review", count: 4 },
      { status: "closed", count: 7 },
      { status: "cancelled", count: 1 }
    ];
    const ticketTotal = raw.reduce((s, c) => s + c.count, 0);
    const out = foldTicketDisplayCounts(raw);
    const bucketTotal = out.open + out.in_progress + out.closed + out.cancelled;
    expect(bucketTotal).toBe(ticketTotal);
    expect(bucketTotal).toBe(22);
  });

  it("空入力は全 0 を返す", () => {
    expect(foldTicketDisplayCounts([])).toEqual({
      open: 0,
      in_progress: 0,
      closed: 0,
      cancelled: 0
    });
  });
});

describe("buildActivityTrendSeries (ADR-00040 D-3/D-4 trend)", () => {
  it("bucket_start を UTC で MM/DD ラベル化する (実行環境 timezone でずれない、R1-1)", () => {
    const { activity } = buildActivityTrendSeries([bucket("2026-05-01T00:00:00Z", 3, 1.0, 3, 0)]);
    // UTC で 5/1。getMonth/getDate (local) だと TZ 次第で 4/30 になり得るが UTC 固定。
    expect(activity[0]?.label).toBe("5/1");
    expect(activity[0]?.value).toBe(3);
  });

  it("cost 系列は cost_usd=null (未計測) bucket を value=0 に丸めず除外する (R1-2)", () => {
    const { activity, cost } = buildActivityTrendSeries([
      bucket("2026-05-01T00:00:00Z", 5, 3.21, 5, 0),
      bucket("2026-05-03T00:00:00Z", 4, null, 0, 4) // 全未計測 → cost 系列から除外
    ]);
    // activity は両 bucket 含む。
    expect(activity.map((p) => p.value)).toEqual([5, 4]);
    // cost は null bucket を除外 (0 に丸めない)。
    expect(cost).toHaveLength(1);
    expect(cost[0]?.value).toBe(3.21);
  });

  it("空 buckets は空系列を返す", () => {
    expect(buildActivityTrendSeries([])).toEqual({ activity: [], cost: [] });
  });
});
