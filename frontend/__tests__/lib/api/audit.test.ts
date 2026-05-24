import { describe, expect, it } from "vitest";

import { AuditEventSchema, AuditEventTypeEnum } from "@/lib/api/audit";

const baseAuditEvent = {
  id: "00000000-0000-4000-8000-00000000d001",
  event_type: "runner_blocked",
  actor_id: "00000000-0000-4000-8000-00000000d002",
  principal_id: null,
  tenant_id: 1,
  trace_id: null,
  correlation_id: null,
  reason_code: "dangerous_command",
  payload_keys: ["argv_hash", "deny_category"],
  payload_redaction_status: "keys_only",
  created_at: "2026-05-24T00:00:00Z"
};

describe("audit API schemas", () => {
  it("keeps audit event_type open while backend has no canonical registry", () => {
    expect(AuditEventSchema.parse(baseAuditEvent).event_type).toBe("runner_blocked");
    expect(
      AuditEventSchema.parse({
        ...baseAuditEvent,
        id: "00000000-0000-4000-8000-00000000d003",
        event_type: "future_backend_audit_event"
      }).event_type
    ).toBe("future_backend_audit_event");
  });

  it("keeps the frontend audit filter enum as suggestions only", () => {
    expect(AuditEventTypeEnum.options).toContain("policy_decision_created");
    expect(AuditEventTypeEnum.options).toContain("webhook_hmac_failed");
  });

  it("accepts redacted metadata with payload key names only", () => {
    expect(AuditEventSchema.parse(baseAuditEvent).payload_keys).toEqual([
      "argv_hash",
      "deny_category"
    ]);
  });

  it("rejects raw audit payload fields before DOM rendering", () => {
    expect(() =>
      AuditEventSchema.parse({
        ...baseAuditEvent,
        event_payload: { api_key: "sk-fakeButSecretShaped0123456789" }
      })
    ).toThrow();
  });
});
