import { fetchBackendJson } from "@/lib/api/client";
import {
  WebhookEventListResponseSchema,
  type WebhookEventListResponse
} from "@/lib/domain/webhook-event";

/**
 * ADR-00050 (SP-028): project-scoped webhook event feed の server fetch。
 *
 * `fetchBackendJson` は `cache: "no-store"` + session cookie 転送を内包するため、tenant/user 固有の
 * activity を static cache に乗せず別ユーザーへ leak しない (F-008)。Server Component から call し、
 * Client Component には resolved data のみ渡す。
 */
export async function fetchWebhookEvents(
  projectId: string,
  options?: { repositoryId?: string; limit?: number }
): Promise<WebhookEventListResponse> {
  const params = new URLSearchParams();
  if (options?.repositoryId) params.set("repository_id", options.repositoryId);
  if (options?.limit !== undefined) params.set("limit", String(options.limit));
  const query = params.toString();
  const path = `/api/v1/projects/${projectId}/webhook_events${
    query ? `?${query}` : ""
  }` as `/${string}`;
  return fetchBackendJson(path, WebhookEventListResponseSchema);
}

/**
 * fail-closed loader: 取得失敗 (auth 失効 / schema drift / network) と「真の 0 件」を区別する
 * discriminated union を返す (L-2 / M-2 教訓: catch して空配列を返すと取得失敗を「0 件」と誤表示する)。
 */
export type WebhookEventsLoad =
  | { ok: true; data: WebhookEventListResponse }
  | { ok: false };

export async function loadWebhookEvents(
  projectId: string,
  options?: { repositoryId?: string; limit?: number }
): Promise<WebhookEventsLoad> {
  try {
    return { ok: true, data: await fetchWebhookEvents(projectId, options) };
  } catch {
    return { ok: false };
  }
}
