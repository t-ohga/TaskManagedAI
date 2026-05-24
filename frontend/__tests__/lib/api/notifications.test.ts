import { describe, expect, it } from "vitest";

import {
  NotificationTriageItemSchema,
  NotificationTriageStateEnum
} from "@/lib/api/notifications";

const baseTriageItem = {
  id: "00000000-0000-4000-8000-00000000b101",
  event_type: "approval_pending",
  payload_keys: ["action_class", "approval_id", "resource_ref"],
  payload_redaction_status: "keys_only",
  severity: "high",
  required_action: "review_approval",
  due_at: "2026-05-25T00:00:00Z",
  snoozed_until: null,
  resolved_at: null,
  resolved_by_actor_id: null,
  created_at: "2026-05-24T00:00:00Z",
  read_at: null
};

describe("notification API schemas", () => {
  it("parses redacted triage items without raw payload values", () => {
    const parsed = NotificationTriageItemSchema.parse(baseTriageItem);

    expect(parsed.payload_redaction_status).toBe("keys_only");
    expect(parsed.payload_keys).toEqual(["action_class", "approval_id", "resource_ref"]);
    expect("payload" in parsed).toBe(false);
  });

  it("rejects unknown triage severity and state values", () => {
    expect(() =>
      NotificationTriageItemSchema.parse({
        ...baseTriageItem,
        severity: "urgent"
      })
    ).toThrow();
    expect(() => NotificationTriageStateEnum.parse("pending")).toThrow();
  });
});
