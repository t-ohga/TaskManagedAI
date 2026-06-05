import { describe, expect, it } from "vitest";

import {
  WebhookEventKindEnum,
  WebhookEventReadSchema,
  ciStateTone,
  webhookEventKindLabel,
  webhookEventReference,
  type WebhookEventRead
} from "@/lib/domain/webhook-event";

const EXPECTED_KINDS = ["pull_request", "check_run", "check_suite", "status", "push"] as const;

function makeEvent(overrides: Partial<WebhookEventRead> = {}): WebhookEventRead {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    repository_id: "22222222-2222-4222-8222-222222222222",
    event_kind: "pull_request",
    action: "opened",
    external_ref: "42",
    state: "open",
    title: "Fix bug",
    sender_login: "octocat",
    received_at: "2026-06-05T01:23:45Z",
    ...overrides
  };
}

describe("webhook event enum integrity", () => {
  it("matches backend WEBHOOK_EVENT_KINDS (5+ source 整合)", () => {
    expect(new Set(WebhookEventKindEnum.options)).toEqual(new Set(EXPECTED_KINDS));
  });
});

describe("webhookEventKindLabel", () => {
  it("returns a Japanese label for every kind", () => {
    for (const kind of EXPECTED_KINDS) {
      expect(webhookEventKindLabel(kind)).not.toBe("");
    }
    expect(webhookEventKindLabel("pull_request")).toBe("プルリクエスト");
  });
});

describe("ciStateTone", () => {
  it("maps success-like states to success", () => {
    expect(ciStateTone("success")).toBe("success");
    expect(ciStateTone("merged")).toBe("success");
    expect(ciStateTone("SUCCESS")).toBe("success");
  });

  it("maps failure-like states to failure", () => {
    expect(ciStateTone("failure")).toBe("failure");
    expect(ciStateTone("timed_out")).toBe("failure");
    expect(ciStateTone("cancelled")).toBe("failure");
  });

  it("maps pending-like states to pending", () => {
    expect(ciStateTone("pending")).toBe("pending");
    expect(ciStateTone("open")).toBe("pending");
    expect(ciStateTone("in_progress")).toBe("pending");
  });

  it("falls back to neutral for null / unknown (no false success/failure)", () => {
    expect(ciStateTone(null)).toBe("neutral");
    expect(ciStateTone("???")).toBe("neutral");
  });
});

describe("webhookEventReference", () => {
  it("prefixes pull_request with #", () => {
    expect(webhookEventReference(makeEvent({ event_kind: "pull_request", external_ref: "42" }))).toBe("#42");
  });

  it("truncates long sha for checks / status", () => {
    const ref = webhookEventReference(
      makeEvent({ event_kind: "check_run", external_ref: "0123456789abcdef0123" })
    );
    expect(ref).toBe("0123456789ab");
  });

  it("returns empty string when external_ref is null (no raw echo)", () => {
    expect(webhookEventReference(makeEvent({ external_ref: null }))).toBe("");
  });
});

describe("WebhookEventReadSchema", () => {
  it("parses a valid non-confidential event", () => {
    const parsed = WebhookEventReadSchema.parse(makeEvent());
    expect(parsed.event_kind).toBe("pull_request");
    expect(parsed.title).toBe("Fix bug");
  });

  it("accepts nullable fields", () => {
    const parsed = WebhookEventReadSchema.parse(
      makeEvent({ repository_id: null, action: null, state: null, title: null, sender_login: null })
    );
    expect(parsed.repository_id).toBeNull();
    expect(parsed.title).toBeNull();
  });

  it("rejects an unknown event_kind (drift guard)", () => {
    expect(() => WebhookEventReadSchema.parse(makeEvent({ event_kind: "issues" as never }))).toThrow();
  });
});
