import { z } from "zod";

import { BackendApiError, fetchBackendRaw } from "@/lib/api/client";
import { TagReadSchema, type TagRead } from "@/lib/domain/tag";

// ticket_id の検証は TicketReadSchema.id (z.string().uuid()) と同一契約に揃える。
// 狭い v1-5 限定 validator だと UUIDv7 等の backend-valid な id を frontend が false
// notFound にしてしまうため (Codex B2b R6 finding)。Zod 4 の uuid() は v1-8 + nil/max を許可。
const TICKET_ID_SCHEMA = z.uuid();

export type TicketDetail = {
  id: string;
  title: string;
  slug: string;
  status: string;
  description: string | null;
  priority: string | null;
  due_date: string | null;
  created_at: string | null;
  updated_at: string | null;
  project_id: string;
  // 看板への戻り導線で使う project slug (tickets 一覧の ?project= は slug を期待する)。
  project_slug: string;
  // ADR-00044 (A-5): backend が GET by-id で inject する per-ticket tag (active scope)。
  tags: TagRead[];
};

/**
 * ticket id から TicketDetail を解決する。
 *
 * 設計契約 (Codex B2b R2/R3/R4 findings):
 * - 各 project の by-id endpoint (GET /api/v1/projects/{pid}/tickets/{id}) を直接叩く。
 *   一覧 (default limit=50) 走査だと 51 件以上の project で新規 ticket が先頭 50 件に
 *   入らず 404 になり得たため (R2)。by-id 取得は project 内件数に依存しない。
 * - 別 project に存在しない 404 だけ skip する。
 * - 401 / 403 / 5xx / network 等の非 404 失敗は「存在しない」と区別できないため、
 *   found の有無に関わらず **最優先で rethrow** し error boundary に流す (R3/R4、fail-closed)。
 *   部分的な auth / backend 障害 / permission drift を false 404 や部分表示で隠さない。
 * - /me/projects 取得失敗も null に潰さず propagate する。
 * - 全 project が 404 / 該当なしのときだけ null を返す (page 側で notFound())。
 */
export async function loadTicket(id: string): Promise<TicketDetail | null> {
  // route param (caller-supplied) を内部 API path に連結する前に UUID として検証する。
  // slash / dot segment を含む値を path に通すと new URL 正規化で別の内部 endpoint へ
  // traversal され得るため、非 UUID は notFound 契約に倒す (Codex B2b R5 finding,
  // server-owned-boundary: dynamic route id は forward 前に検証必須)。
  if (!TICKET_ID_SCHEMA.safeParse(id).success) {
    return null;
  }
  // UUID は case-insensitive。backend は canonical lowercase を返すため、path 連結 /
  // 照合とも lowercase に正規化して大小不一致による false notFound を防ぐ (R6 finding)。
  const normalizedId = id.toLowerCase();

  const projectsRes = await fetchBackendRaw("/api/v1/me/projects");
  const projects = ((projectsRes as Record<string, unknown>)?.projects ?? []) as Record<
    string,
    string
  >[];

  const settled = await Promise.allSettled(
    projects.map(async (p): Promise<TicketDetail | null> => {
      const pid = String(p.project_id ?? p.id ?? "");
      const slug = String(p.slug ?? "");
      if (!pid) return null;
      try {
        const ticketRes = await fetchBackendRaw(
          `/api/v1/projects/${encodeURIComponent(pid)}/tickets/${encodeURIComponent(normalizedId)}` as `/${string}`
        );
        const ticket = ticketRes as (TicketDetail & { id?: string }) | null;
        if (ticket && ticket.id?.toLowerCase() === normalizedId) {
          // tags は backend が常に inject する。Zod で strict validate し、**malformed / absent / null は
          // [] に潰さず throw** する (Codex R6/R7 HIGH)。`?? []` を使わず直接 parse し、explicit `tags: []`
          // (タグなし) と version skew / degraded での metadata 不在を区別する。本ページは attach/detach/
          // rename/delete の write surface なので、false empty から始めると現在の分類を誤認させる。
          // throw は probe の rejected として最優先 surface され error boundary へ。
          const tagsParsed = z
            .array(TagReadSchema)
            .safeParse((ticketRes as Record<string, unknown>)?.tags);
          if (!tagsParsed.success) {
            throw new Error("ticket tag metadata missing or failed schema validation");
          }
          return {
            ...ticket,
            project_id: pid,
            project_slug: slug,
            tags: tagsParsed.data
          };
        }
        return null;
      } catch (error) {
        if (error instanceof BackendApiError && error.status === 404) {
          return null;
        }
        throw error;
      }
    })
  );

  // 1) 非 404 の probe 失敗を found より先に surface する (fail-closed)。
  for (const result of settled) {
    if (result.status === "rejected") {
      throw result.reason;
    }
  }
  // 2) 所有 project の by-id が 200 を返したものを返す。
  for (const result of settled) {
    if (result.status === "fulfilled" && result.value !== null) {
      return result.value;
    }
  }
  // 3) 全 project が 404 / 該当なし → 本当に存在しない。
  return null;
}
