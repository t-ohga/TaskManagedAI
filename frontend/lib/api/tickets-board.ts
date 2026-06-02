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
export type TicketItem = {
  id: string;
  title: string;
  status: string;
  priority: string | null;
  description: string | null;
  due_date: string | null;
  created_at: string | null;
  tags: TagRead[];
};

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
  const raw = res as Record<string, unknown>;
  const rawItems = (raw?.items ?? []) as (TicketItem & { tags?: unknown })[];
  // tags は backend が inject するが Zod で strict validate し、欠落/palette drift は [] に倒す。
  const items = rawItems.map((t) => {
    const tagsParsed = z.array(TagReadSchema).safeParse(t.tags ?? []);
    return { ...t, tags: tagsParsed.success ? tagsParsed.data : [] };
  });
  const total = typeof raw?.total === "number" ? raw.total : items.length;
  return { items, total, truncated: total > items.length };
}

export type ProjectBoardItem = {
  project_id?: string;
  id?: string;
  slug: string;
  name: string;
};

/**
 * `/me/projects` を取得する。
 *
 * **fail-closed 分岐 (Codex R5 HIGH)**: `failClosed=true` (具体 project / tag filter を選択中) のとき
 * project metadata の取得失敗を [] に潰すと、slug 解決できず ticket fetch も走らないまま「0 件」board を
 * 完全な結果として描画してしまう。そのため失敗を caller へ伝播し error boundary に流す。横断 (all view)
 * 時は project 一覧が補助なので fail-soft ([])。
 */
export async function loadProjects(failClosed: boolean): Promise<ProjectBoardItem[]> {
  try {
    const res = await fetchBackendRaw("/api/v1/me/projects");
    const raw = res as Record<string, unknown>;
    return (raw?.projects ?? raw?.items ?? []) as ProjectBoardItem[];
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
