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

const _YMD_FULL = /^\d{4}-\d{2}-\d{2}$/;

/**
 * 文字列全体が **実在する暦日** (`YYYY-MM-DD`) か厳密に検証する (adversarial R1 F-001 / R2 F-001)。
 *
 * regex の **全文字列 full-match** に加え、UTC で round-trip して年月日が一致するか確認する。
 * - `2026-13-40` / `2026-02-31` のような prefix だけ正しい非実在日を弾く (JS Date 正規化での誤分類防止)。
 * - `2026-06-01T23:30:00Z` / `2026-06-01junk` のような **timestamp / 余分な suffix も弾く**。
 *   reminder / date_context / ticket の `due_date` は backend の `date` 型 (厳密に `YYYY-MM-DD`、
 *   時刻なし) のため、timestamp は schema drift であり fail-closed で拒否する (R2: slice 検証は
 *   suffix を見逃し、JST 深夜境界で別暦日に誤分類しうる)。
 */
export function isValidYmd(value: string): boolean {
  if (!_YMD_FULL.test(value)) return false;
  const y = Number(value.slice(0, 4));
  const m = Number(value.slice(5, 7));
  const d = Number(value.slice(8, 10));
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

// `YYYY-MM-DD` (isValidYmd 済) に days を加算して `YYYY-MM-DD` を返す純粋関数。UTC で parse /
// format するため local timezone に依存しない (暦日の加算のみ)。
function addDaysYmd(ymd: string, days: number): string {
  const parts = ymd.split("-");
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
// A-7 (ADR-00045): 期限強調の対象 status。backend reminders query の
// `_REMINDER_ACTIONABLE_STATUSES` (backend/app/domain/reminders.py 参照経由、me.py で定義) と
// 同一集合に揃える。closed / cancelled は終了済で期限が actionable でないため強調しない
// (adversarial R3 F-001: dashboard reminder panel が除外するのに一覧/Kanban が赤/橙表示する
// 画面間不整合を防ぐ)。
export const REMINDER_ACTIONABLE_STATUSES: ReadonlySet<string> = new Set([
  "open",
  "in_progress",
  "blocked",
  "review"
]);

export function isReminderActionableStatus(status: string): boolean {
  return REMINDER_ACTIONABLE_STATUSES.has(status);
}

/**
 * ticket の status + 期限から強調用 bucket を返す共有 helper (一覧 / Kanban 共通)。
 *
 * - due_date なし / referenceDate・thresholdDays 未取得 (date_context 失敗) -> `null` (neutral)。
 * - **非 actionable status (closed / cancelled)** -> `null` (neutral)。backend reminders と同じ
 *   actionable 集合でゲートし、終了済 ticket を赤/橙の期限強調にしない (R3 F-001)。
 * - それ以外は `dueDateBucket` に委譲。
 */
export function ticketDueBucket(
  dueDate: string | null,
  status: string,
  referenceDate: string | undefined,
  thresholdDays: number | undefined
): DueDateBucket | null {
  if (!dueDate || referenceDate === undefined || thresholdDays === undefined) return null;
  if (!isReminderActionableStatus(status)) return null;
  return dueDateBucket(dueDate, referenceDate, thresholdDays);
}

export function dueDateBucket(
  dueDate: string,
  referenceDate: string,
  thresholdDays: number
): DueDateBucket | null {
  // 非実在日 / 形式不正 (timestamp / junk suffix 含む) / 不正な閾値は誤分類せず null
  // (強調なし、fail-safe、R1/R2 F-001)。
  if (!isValidYmd(dueDate) || !isValidYmd(referenceDate)) return null;
  if (!Number.isInteger(thresholdDays) || thresholdDays < 0) return null;
  if (dueDate < referenceDate) return "overdue";
  if (dueDate === referenceDate) return "due_today";
  const windowEnd = addDaysYmd(referenceDate, thresholdDays);
  if (dueDate <= windowEnd) return "upcoming";
  return null;
}
