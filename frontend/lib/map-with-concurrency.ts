/**
 * items を最大 `limit` 件ずつ同時実行で map する (入力順を保持)。
 *
 * `Promise.all(items.map(fn))` は items 数だけ同時に fn を起動するため、要素数が増えると
 * 無制限 fan-out になり下流 (backend / DB / connection pool) を枯らす。本 helper は同時実行数を
 * `limit` で bound しつつ、結果を入力順 (index) で返す。
 *
 * - 同時実行数: `min(limit, items.length)` 個の worker が **共有 iterator** (`items.entries()`) から
 *   次の `[index, item]` を pull して処理する。JS は単一スレッドで `iterator.next()` が atomic な
 *   ため、worker 間で同じ要素を重複処理しない (index アクセスを避けるので型安全)。
 * - 順序: 戻り値 `results[i]` は `items[i]` に対応する (完了順ではなく入力順)。
 * - error: fn が reject するとその worker が伝播し helper 全体が reject する (`Promise.all` と同じ
 *   fail-fast)。fail-soft が必要な caller は fn 内で握って結果オブジェクトに正規化する
 *   (例: 横断ボードの per-project ticket fetch は "ok / omit / skip" に正規化する)。
 * - limit が 0 / 負 / 非有限 のときは安全側に矯正する (worker 0 個での deadlock を防ぐ)。
 */
export async function mapWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>
): Promise<R[]> {
  const results = new Array<R>(items.length);
  if (items.length === 0) return results;

  const requested = Number.isFinite(limit) ? Math.floor(limit) : items.length;
  const workerCount = Math.max(1, Math.min(requested, items.length));

  // 全 worker が共有する単一 iterator。各 worker は for-of で next() を pull し、
  // 取り出した [index, item] を処理する (重複なし・順序は results[index] で保持)。
  const entries = items.entries();
  async function worker(): Promise<void> {
    for (const [index, item] of entries) {
      results[index] = await fn(item, index);
    }
  }

  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return results;
}
