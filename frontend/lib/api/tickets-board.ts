import { z } from "zod";

import { fetchBackendRaw } from "@/lib/api/client";
import { listTags } from "@/lib/api/tags";
import { TagReadSchema, type TagRead } from "@/lib/domain/tag";

/**
 * ticket 看板 / 一覧用の ticket 取得 (server-only)。
 *
 * ADR-00044 (A-5) tag filter は backend の `?tag_id=` query を使う (client-side filter だと
 * limit を超えた tag 付き ticket を silent に隠すため、Codex frontend R1)。
 *
 * **fail-closed (Codex frontend R2 HIGH)**: tag filter request (tagId 指定) の失敗は `[]` に
 * 潰さず caller へ伝播する。auth / backend / network 障害を「該当なし」と誤表示すると、ユーザーが
 * 不完全データを業務判断に使う。caller は 404 (無効 tag) のみ絞り込み解除し、それ以外は error
 * boundary に流す。tag 指定なしの通常取得は従来通り fail-soft (all view で 1 project の一時障害が
 * 全体を落とさない)。
 */
// ticket row schema。enum 系は drift で過剰 throw しないよう緩めの string で受けるが、tags は必須
// (absent/null は metadata 不在として fail-closed、Codex R7)。backend の余分 field は strip される。
const TicketItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  status: z.string(),
  priority: z.string().nullable(),
  description: z.string().nullable(),
  due_date: z.string().nullable(),
  created_at: z.string().nullable(),
  tags: z.array(TagReadSchema)
});

export type TicketItem = z.infer<typeof TicketItemSchema>;

// board response 全体を fail-closed validate (Codex R8 HIGH)。items は明示 array、total は number が
// 必須。absent/null items や total 欠落を `{items:[], total:0}` に潰して complete empty board / non-
// truncated filtered result と誤表示しない (explicit items:[] は有効なので array 自体は許容)。
const TicketBoardResponseSchema = z.object({
  items: z.array(TicketItemSchema),
  total: z.number()
});

export const TICKET_BOARD_PAGE_LIMIT = 200;

/**
 * loadTickets の結果。`total` は backend が `tag_id` 適用後に返す **絞り込み後の全件数**。
 * `total > items.length` なら limit で truncate されており、結果は部分的。caller はこの flag で
 * 「該当なし」と「一部のみ表示」を区別し、不完全データを完全な結果として見せない (Codex R3 HIGH)。
 */
export type TicketBoardResult = {
  items: TicketItem[];
  total: number;
  truncated: boolean;
};

/**
 * 単一 project の ticket を取得する。
 *
 * **常に失敗を throw する (Codex R5 HIGH)**。fail-soft / fail-closed の policy は caller intent で
 * 決める: selected-project load と tag-filtered load (+ invalid-tag fallback) は throw を伝播して
 * error boundary に流し (fail-closed、不完全を完全と見せない)、all-project aggregation のみ caller が
 * catch して per-project omission を可視化する (fail-soft)。本 loader 自身は [] に潰さない。
 */
export async function loadTickets(
  projectId: string,
  tagId?: string
): Promise<TicketBoardResult> {
  const params = new URLSearchParams({ limit: String(TICKET_BOARD_PAGE_LIMIT) });
  if (tagId) params.set("tag_id", tagId);
  const path = `/api/v1/projects/${projectId}/tickets?${params.toString()}` as `/${string}`;
  const res = await fetchBackendRaw(path);
  // response 全体 (items 配列 + total number + 各 row の tags) を fail-closed validate。
  // items / total / tags の absent / null / malformed を complete empty board に潰さず throw する
  // (Codex R6/R7/R8 HIGH)。caller が intent で fail-closed / omission に倒す。
  const parsed = TicketBoardResponseSchema.safeParse(res);
  if (!parsed.success) {
    throw new Error("ticket board response missing or failed schema validation");
  }
  const { items, total } = parsed.data;
  return { items, total, truncated: total > items.length };
}

// project row は slug + (project_id | id) が必須。degraded response で欠落した row を成功扱いしない
// (Codex R6 HIGH: slug 欠落で selectedProject が解決できず空 board を誤表示する経路を塞ぐ)。
const ProjectBoardItemSchema = z
  .object({
    project_id: z.string().min(1).optional(),
    id: z.string().min(1).optional(),
    slug: z.string().min(1),
    name: z.string()
  })
  .refine((p) => Boolean(p.project_id ?? p.id), {
    message: "project row must include project_id or id"
  });

export type ProjectBoardItem = z.infer<typeof ProjectBoardItemSchema>;

/**
 * `/me/projects` を取得する。
 *
 * **fail-closed 分岐 (Codex R5/R6 HIGH)**: `failClosed=true` (具体 project / tag filter を選択中) のとき
 * (a) request の失敗、(b) project row shape (slug + project_id/id) の schema 不正、のどちらも [] に潰すと
 * slug 解決できず ticket fetch も走らないまま「0 件」board を完全な結果として描画してしまう。そのため
 * 両方を caller へ伝播し error boundary に流す。横断 (all view) 時は project 一覧が補助なので fail-soft ([])。
 */
export async function loadProjects(failClosed: boolean): Promise<ProjectBoardItem[]> {
  try {
    const res = await fetchBackendRaw("/api/v1/me/projects");
    const raw = res as Record<string, unknown>;
    const rawList = raw?.projects ?? raw?.items;
    // envelope (projects or items) が absent/null なら degraded response (Codex R8 HIGH)。`?? []` で
    // 空配列に潰すと slug 解決できないまま 0 件扱いになるため、failClosed では throw。explicit `projects:[]`
    // (= 配列) は valid。
    if (!Array.isArray(rawList)) {
      if (failClosed) {
        throw new Error("project list envelope missing or not an array");
      }
      return [];
    }
    const parsed = z.array(ProjectBoardItemSchema).safeParse(rawList);
    if (!parsed.success) {
      if (failClosed) {
        throw new Error("project list failed schema validation");
      }
      return [];
    }
    return parsed.data;
  } catch (error) {
    if (failClosed) {
      throw error;
    }
    return [];
  }
}

/**
 * project の tag 一覧 (TagFilter / 付与候補 用)。
 *
 * **fail-closed 分岐 (Codex frontend R4 HIGH)**: `failClosed=true` (tag filter 適用中) のとき
 * listTags の失敗を [] に潰すと、TagFilter / clear / notice が描画されないまま絞り込み済み subset を
 * 「全件」と誤認させる (どの tag で絞っているか UI で示せない)。そのため失敗を caller へ伝播し
 * error boundary に流す。tag filter なし (`failClosed=false`) のときは tag metadata が付加機能なので
 * fail-soft ([])。
 */
export async function loadProjectTags(
  projectId: string,
  failClosed: boolean
): Promise<TagRead[]> {
  try {
    return (await listTags(projectId)).items;
  } catch (error) {
    if (failClosed) {
      throw error;
    }
    return [];
  }
}
