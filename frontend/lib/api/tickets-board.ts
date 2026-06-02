import { z } from "zod";

import { fetchBackendRaw } from "@/lib/api/client";
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

export async function loadTickets(
  projectId: string,
  tagId?: string
): Promise<TicketBoardResult> {
  const params = new URLSearchParams({ limit: String(TICKET_BOARD_PAGE_LIMIT) });
  if (tagId) params.set("tag_id", tagId);
  const path = `/api/v1/projects/${projectId}/tickets?${params.toString()}` as `/${string}`;
  try {
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
  } catch (error) {
    // tag filter は正確性が重要。失敗 (auth / backend / network) を [] に潰さず caller へ伝播し、
    // 404 (無効 tag) も caller で絞り込み解除に倒す (silent な「該当なし」を防ぐ、Codex R2 HIGH)。
    if (tagId) {
      throw error;
    }
    // 通常取得 (tag なし / all view) は fail-soft (1 project の一時障害で全体を落とさない)。
    return { items: [], total: 0, truncated: false };
  }
}
