import { z } from "zod";

import { BackendApiError, fetchBackendRaw } from "@/lib/api/client";
import { loadProjects } from "@/lib/api/tickets-board";
import { TagReadSchema, type TagRead } from "@/lib/domain/tag";
import { isValidYmd } from "@/lib/domain/due-date";

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
  // A-6 (ADR-00046): 担当者 actor id (UUID or null)。display_name は frontend が
  // assignable-actors map で解決する (TicketRead 契約不変)。
  assignee_actor_id: string | null;
  created_at: string | null;
  // C-5 R3 (Codex adversarial HIGH): updated_at は edit form の snapshot/props 新旧判定 version。
  // backend TicketRead は必須で返すため、loader で strict validate して required string に固定する
  // (null/欠落を許すと「古い成功 snapshot が version 不明 props を恒久遮断する」経路が型レベルで残る)。
  updated_at: string;
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

  // project list を envelope + row shape まで fail-closed validate する (Codex R8 HIGH)。
  // degraded /me/projects (projects 欠落/null、id 欠落 row、slug 欠落) を空 probe set に潰して
  // 実 ticket を false 404 / broken back-link にしない。loadProjects(true) が schema 不正/障害を throw する。
  const projects = await loadProjects(true);

  const settled = await Promise.allSettled(
    projects.map(async (p): Promise<TicketDetail | null> => {
      const pid = String(p.project_id ?? p.id ?? "");
      const slug = p.slug;
      if (!pid) return null;
      try {
        const ticketRes = await fetchBackendRaw(
          `/api/v1/projects/${encodeURIComponent(pid)}/tickets/${encodeURIComponent(normalizedId)}` as `/${string}`
        );
        const ticket = ticketRes as (TicketDetail & { id?: string }) | null;
        if (ticket && ticket.id?.toLowerCase() === normalizedId) {
          // A-7 (ADR-00045 R11/R12 F-001): detail loader は cast 直返しで strict schema を bypass
          // していたため、due_date を **strict YMD validate** する (reminders/board/TicketReadSchema と
          // 同じ strict-YMD all-surface 不変条件を detail/edit 経路でも enforce)。due_date は backend の
          // date 型 (required nullable)。null または実在する YYYY-MM-DD のみ許可し、timestamp / junk /
          // 非実在日 (2026-02-31) / 欠落は fail-closed で throw する (detail formatter が malformed を
          // 表示・隠蔽したり、edit form が malformed を date input に渡して保存で deadline を silent 改変
          // するのを防ぐ)。throw は probe の rejected として最優先 surface され error boundary へ。
          const rawDue = (ticketRes as Record<string, unknown>)?.due_date;
          const dueOk = rawDue === null || (typeof rawDue === "string" && isValidYmd(rawDue));
          if (!dueOk) {
            throw new Error("ticket due_date is missing or not a valid YYYY-MM-DD calendar date");
          }
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
          // A-6 (ADR-00046): assignee_actor_id を strict validate (null または canonical UUID のみ)。
          // 欠落 (version skew) / 非 UUID は fail-closed で throw し、detail 表示や edit form の select に
          // 壊れた値を渡さない (due_date と同じ strict-all-surface 方針)。
          const rawAssignee = (ticketRes as Record<string, unknown>)?.assignee_actor_id;
          const assigneeOk =
            rawAssignee === null ||
            (typeof rawAssignee === "string" &&
              TICKET_ID_SCHEMA.safeParse(rawAssignee).success);
          if (!assigneeOk) {
            throw new Error("ticket assignee_actor_id is missing or not a valid UUID");
          }
          // C-5 R3 (Codex adversarial HIGH): updated_at を strict validate (必須 + parseable timestamp)。
          // backend TicketRead は必須で返す。null / 欠落 / 非 timestamp を fail-closed で throw し、
          // edit form の snapshot/props 新旧判定 (resolveServerTicket) に「順序不明」な version を
          // 渡さない (due_date / tags / assignee と同じ strict-all-surface 方針)。
          const rawUpdatedAt = (ticketRes as Record<string, unknown>)?.updated_at;
          const updatedAtOk =
            typeof rawUpdatedAt === "string" && !Number.isNaN(Date.parse(rawUpdatedAt));
          if (!updatedAtOk) {
            throw new Error("ticket updated_at is missing or not a parseable timestamp");
          }
          return {
            ...ticket,
            project_id: pid,
            project_slug: slug,
            assignee_actor_id: rawAssignee as string | null,
            updated_at: rawUpdatedAt,
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
