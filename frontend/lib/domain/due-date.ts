// A-7 (ADR-00045): 期限 (due_date) の bucket 判定。client-safe domain module
// (next/headers 非依存、Server Component / Client Component の両方が import する)。
//
// backend `compute_reminder_bucket(due, ref, threshold)` と **同一 signature / 同一 4 値**。
// "today" (referenceDate) と threshold は backend authority (`GET /api/v1/me/date_context`) から
// 受け取り、client では算出しない (plan-review R2 F-002)。
//
// 暦日比較は `YYYY-MM-DD` の **文字列 lexicographic 比較** で行い、`new Date(dueDate)` を介さない
// (local timezone 変換による日付ずれを排除、ADR-00034 暦日 semantics と整合)。

export type DueDateBucket = "overdue" | "due_today" | "upcoming";

const _YMD = /^\d{4}-\d{2}-\d{2}/;

function isYmd(value: string): boolean {
  return _YMD.test(value);
}

// `YYYY-MM-DD` に days を加算して `YYYY-MM-DD` を返す純粋関数。UTC で parse / format するため
// local timezone に依存しない (暦日の加算のみ)。
function addDaysYmd(ymd: string, days: number): string {
  const parts = ymd.slice(0, 10).split("-");
  const y = Number(parts[0]);
  const m = Number(parts[1]);
  const d = Number(parts[2]);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + days);
  const yyyy = dt.getUTCFullYear();
  const mm = String(dt.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(dt.getUTCDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

/**
 * due_date を基準日 + 閾値から bucket 分類する (backend `compute_reminder_bucket` と同一)。
 *
 * - `due < ref` -> `"overdue"` (下限なし)
 * - `due === ref` -> `"due_today"`
 * - `ref < due <= ref + thresholdDays` -> `"upcoming"`
 * - `due > ref + thresholdDays` -> `null` (window 外)
 *
 * いずれかの入力が `YYYY-MM-DD` 形式でない場合は `null` (誤分類せず強調なしに倒す、fail-safe)。
 */
export function dueDateBucket(
  dueDate: string,
  referenceDate: string,
  thresholdDays: number
): DueDateBucket | null {
  if (!isYmd(dueDate) || !isYmd(referenceDate)) return null;
  const due = dueDate.slice(0, 10);
  const ref = referenceDate.slice(0, 10);
  if (due < ref) return "overdue";
  if (due === ref) return "due_today";
  const windowEnd = addDaysYmd(ref, thresholdDays);
  if (due <= windowEnd) return "upcoming";
  return null;
}
