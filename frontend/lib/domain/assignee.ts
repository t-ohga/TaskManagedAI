import { z } from "zod";

// A-6 (ADR-00046): 担当者割当の client-safe domain (zod schema + pure 表示/選択 helper)。
// Codex App F-C1 (P1): server-only fetch (`fetchBackendJson` -> next/headers) と同居させると Client
// Component が import した時に server-only 依存が client bundle へ混入し next build が壊れる。pure 部を
// 本 domain module に分離し、fetch は `lib/api/actors.ts` (server) に残す (A-7 の due-date / reminders と
// 同じ domain / api 分割規約)。

const AssignableActorSchema = z.object({
  id: z.string().uuid(),
  display_name: z.string().nullable()
});

export type AssignableActor = z.infer<typeof AssignableActorSchema>;

export const AssignableActorsSchema = z.object({
  actors: z.array(AssignableActorSchema),
  // R1 F-009: ASSIGNABLE_ACTOR_LIST_LIMIT 到達で一覧が切り詰められたか (silent cap の可視化)。
  truncated: z.boolean()
});

export type AssignableActors = z.infer<typeof AssignableActorsSchema>;

// 表示用 fallback (UUID 生表示はしない。secret/PII を露出せず人間可読にする)。
const UNASSIGNED_LABEL = "未割当";
const UNNAMED_LABEL = "担当者 (名称未設定)";
// map-miss: legacy 非 human assignee / assignable-actors fetch 失敗 (空 map) など、現 assignee が
// 解決できないとき。UUID を晒さず中立に倒す。
const UNKNOWN_LABEL = "担当者 (不明)";
// 現 assignee が assignable 一覧の cap 外 / 既に human でない等で「一覧には無いが値は保持したい」場合。
const OUT_OF_LIST_LABEL = "担当者 (一覧外)";

function displayNameOrFallback(displayName: string | null): string {
  return displayName && displayName.trim() !== "" ? displayName : UNNAMED_LABEL;
}

/** assignee UUID -> display_name (null 可) の map を構築する。display 解決に使う。 */
export function buildAssigneeNameMap(
  actors: readonly AssignableActor[]
): Map<string, string | null> {
  return new Map(actors.map((a) => [a.id, a.display_name]));
}

/**
 * assignee_actor_id を人間可読な label に解決する (UUID 生表示をしない)。
 * - null -> "未割当"
 * - map にあり display_name あり -> display_name
 * - map にあり display_name null -> "担当者 (名称未設定)"
 * - map-miss (legacy 非 human / fetch 失敗の空 map) -> "担当者 (不明)"
 */
export function assigneeLabel(
  nameById: Map<string, string | null>,
  assigneeActorId: string | null
): string {
  if (!assigneeActorId) return UNASSIGNED_LABEL;
  if (nameById.has(assigneeActorId)) {
    return displayNameOrFallback(nameById.get(assigneeActorId) ?? null);
  }
  return UNKNOWN_LABEL;
}

export type AssigneeOption = { value: string; label: string };

/**
 * 担当者セレクタの option を構築する。「未割当」は呼出側で value="" として別途置く。
 * R1 F-009: 現 assignee が assignable 一覧に無くても option に含め、select が現在値を失わない
 * (cap 外 / 既に非 human / fetch 部分失敗でも silent に未割当へ変えない)。
 */
export function assigneeSelectOptions(
  actors: readonly AssignableActor[],
  currentAssigneeId: string | null
): AssigneeOption[] {
  const options: AssigneeOption[] = actors.map((a) => ({
    value: a.id,
    label: displayNameOrFallback(a.display_name)
  }));
  if (currentAssigneeId && !actors.some((a) => a.id === currentAssigneeId)) {
    options.push({ value: currentAssigneeId, label: OUT_OF_LIST_LABEL });
  }
  return options;
}
