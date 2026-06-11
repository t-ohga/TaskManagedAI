// A-3: mapWithConcurrency (bounded 並列 map) の不変条件を固定する。
//  - 入力順保持 / 全件 exactly-once 処理 / 同時実行数 <= limit / limit>=N で full 並列 /
//    error は fail-fast 伝播 / empty / limit の clamp (0・負・Infinity)。
import { describe, expect, it } from "vitest";

import { mapWithConcurrency } from "@/lib/map-with-concurrency";

// 同時 in-flight の最大値を観測する tracker。各 fn 呼び出しを wrap し、5ms の重なり窓で
// 並列度を決定的に測る。
function makeInFlightTracker() {
  let inFlight = 0;
  let max = 0;
  return {
    get max() {
      return max;
    },
    async run<T>(value: T): Promise<T> {
      inFlight += 1;
      max = Math.max(max, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 5));
      inFlight -= 1;
      return value;
    }
  };
}

describe("mapWithConcurrency", () => {
  it("結果を入力順で返す (完了順に依存しない)", async () => {
    // 後ろの要素ほど早く解決させ、戻り値が完了順でなく入力順であることを確認する。
    const items = [0, 1, 2, 3, 4];
    const result = await mapWithConcurrency(items, 2, async (n) => {
      await new Promise((resolve) => setTimeout(resolve, (items.length - n) * 3));
      return n * 10;
    });
    expect(result).toEqual([0, 10, 20, 30, 40]);
  });

  it("全要素を exactly-once で処理する", async () => {
    const items = ["a", "b", "c", "d", "e", "f", "g"];
    const seen: string[] = [];
    await mapWithConcurrency(items, 3, async (s) => {
      seen.push(s);
      return s;
    });
    expect(seen.slice().sort()).toEqual([...items].sort());
    expect(seen).toHaveLength(items.length);
  });

  it("同時実行数を limit で bound する (N > limit)", async () => {
    const tracker = makeInFlightTracker();
    const items = Array.from({ length: 10 }, (_, i) => i);
    await mapWithConcurrency(items, 3, (n) => tracker.run(n));
    expect(tracker.max).toBe(3);
  });

  it("limit >= N のときは全要素を並列に処理する", async () => {
    const tracker = makeInFlightTracker();
    const items = [1, 2, 3];
    await mapWithConcurrency(items, 6, (n) => tracker.run(n));
    expect(tracker.max).toBe(3);
  });

  it("fn が reject すると helper 全体が reject する (fail-fast)", async () => {
    const items = [1, 2, 3];
    await expect(
      mapWithConcurrency(items, 2, async (n) => {
        if (n === 2) throw new Error("boom");
        return n;
      })
    ).rejects.toThrow("boom");
  });

  it("空入力は空配列を返し fn を呼ばない", async () => {
    let called = 0;
    const result = await mapWithConcurrency([], 4, async (n) => {
      called += 1;
      return n;
    });
    expect(result).toEqual([]);
    expect(called).toBe(0);
  });

  it("limit <= 0 でも deadlock せず逐次 (worker=1) で全件処理する", async () => {
    const tracker = makeInFlightTracker();
    const items = [1, 2, 3];
    const result = await mapWithConcurrency(items, 0, (n) => tracker.run(n));
    expect(result).toEqual([1, 2, 3]);
    expect(tracker.max).toBe(1);
  });

  it("limit が非有限 (Infinity) なら全要素を並列に処理する", async () => {
    const tracker = makeInFlightTracker();
    const items = [1, 2, 3, 4];
    await mapWithConcurrency(items, Number.POSITIVE_INFINITY, (n) => tracker.run(n));
    expect(tracker.max).toBe(4);
  });
});
