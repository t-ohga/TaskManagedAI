import { z } from "zod";

/**
 * ADR-00050 (SP-028): GitHub webhook event の client-safe な schema / 型 / 表示ヘルパー。
 *
 * **Client Component から import されるため `next/headers` 等 server-only 依存を持たない**
 * (A-6 / M-2 の RSC server/client 分離規約)。fetch 関数 (cookies 依存) は `@/lib/api/webhook-events`
 * に分離する。値は backend で allowlist 抽出 + 値レベル redaction 済の非機密 field のみ。表示は
 * **text node のみ** (dangerouslySetInnerHTML / Markdown は使わない、untrusted 由来のため)。
 *
 * event_kind は backend `WEBHOOK_EVENT_KINDS` (migration DB CHECK / ORM / Pydantic) と 5+ source 整合。
 */
export const WebhookEventKindEnum = z.enum([
  "pull_request",
  "check_run",
  "check_suite",
  "status",
  "push"
]);

export type WebhookEventKind = z.infer<typeof WebhookEventKindEnum>;

export const WebhookEventReadSchema = z.object({
  id: z.string().uuid(),
  repository_id: z.string().uuid().nullable(),
  event_kind: WebhookEventKindEnum,
  action: z.string().nullable(),
  external_ref: z.string().nullable(),
  state: z.string().nullable(),
  title: z.string().nullable(),
  sender_login: z.string().nullable(),
  received_at: z.string()
});

export type WebhookEventRead = z.infer<typeof WebhookEventReadSchema>;

export const WebhookEventListResponseSchema = z.object({
  items: z.array(WebhookEventReadSchema),
  limit: z.number().int()
});

export type WebhookEventListResponse = z.infer<typeof WebhookEventListResponseSchema>;

const EVENT_KIND_LABELS: Record<WebhookEventKind, string> = {
  pull_request: "プルリクエスト",
  check_run: "チェック実行",
  check_suite: "チェックスイート",
  status: "コミットステータス",
  push: "プッシュ"
};

export function webhookEventKindLabel(kind: WebhookEventKind): string {
  return EVENT_KIND_LABELS[kind];
}

export type CiStateTone = "success" | "failure" | "pending" | "neutral";

/**
 * CI / PR の state を badge tone に写像する。未知 / null は neutral に倒す (誤った成功/失敗表示を防ぐ)。
 * state は backend で長さ bound 済の短い enum-like 文字列 (success / failure / merged / open 等)。
 */
export function ciStateTone(state: string | null): CiStateTone {
  if (state === null) return "neutral";
  const normalized = state.toLowerCase();
  if (["success", "merged", "completed"].includes(normalized)) return "success";
  if (["failure", "failed", "error", "timed_out", "cancelled", "action_required"].includes(normalized)) {
    return "failure";
  }
  if (["pending", "queued", "in_progress", "open", "neutral"].includes(normalized)) return "pending";
  return "neutral";
}

/**
 * event の主たる識別子表示。PR は #number、check / status は短縮 sha、push は ref。
 * 値は backend allowlist 抽出済。null は空文字に倒す (raw echo しない)。
 */
export function webhookEventReference(event: WebhookEventRead): string {
  if (event.external_ref === null) return "";
  if (event.event_kind === "pull_request") return `#${event.external_ref}`;
  if (event.event_kind === "check_run" || event.event_kind === "check_suite" || event.event_kind === "status") {
    return event.external_ref.slice(0, 12);
  }
  return event.external_ref.slice(0, 12);
}
