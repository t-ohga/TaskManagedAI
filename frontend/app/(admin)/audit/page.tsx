/**
 * Sprint 9 BL-0107: Audit Log (P0 UI skeleton).
 *
 * Append-only audit display. Raw secrets, raw provider responses, and
 * capability token values are excluded; only redacted metadata and reason codes
 * are shown.
 */

import {
  AdminPageShell,
  KeyboardReadinessStrip,
  Panel,
  SecretBoundaryNotice
} from "../_components/sprint9-admin-ui";

export const dynamic = "force-dynamic";

// F-P2R1-006 fix: reason_code (Provider Compliance / event-level) and
// blocked_reason (AgentRun status sub-category) are distinct invariants.
// blocked_reason is null unless the resulting status is `blocked`, while
// reason_code mirrors event-specific deny / allow codes (Provider Compliance
// Matrix has 13 reason_code values, runner_blocked has its own deny_category).
const AUDIT_EVENT_ROWS = [
  {
    event_type: "policy_decision_created",
    actor_id: "actor:user:reviewer-001",
    reason_code: "allow",
    blocked_reason: null,
    payload_data_class: "internal",
    allowed_data_class: "confidential",
    redaction: "hash reference のみ"
  },
  {
    event_type: "secret_canary_detected",
    actor_id: "system/provider-preflight",
    reason_code: "provider_request_preflight_violation",
    blocked_reason: null,
    payload_data_class: "confidential",
    allowed_data_class: "confidential",
    redaction: "pattern_hit のみ"
  },
  {
    event_type: "runner_blocked",
    actor_id: "system/runner-gateway",
    reason_code: "dangerous_command",
    blocked_reason: "runtime_blocked",
    payload_data_class: "internal",
    allowed_data_class: "internal",
    redaction: "argv_hash と deny_category のみ"
  },
  {
    event_type: "repo_pr_opened",
    actor_id: "system/repo-proxy",
    reason_code: "allow",
    blocked_reason: null,
    payload_data_class: "internal",
    allowed_data_class: "confidential",
    redaction: "branch と PR number metadata のみ"
  }
] as const;

export default function AuditLogPage() {
  return (
    <AdminPageShell
      description="Sprint 9 BL-0107 skeleton。append-only audit row に reason_code、actor_id、data-class separation、SecretBroker redaction marker を表示します。"
      eyebrow="管理 / 監査ログ"
      regionLabel="監査ログ"
      title="監査ログ"
    >
      <KeyboardReadinessStrip current="Audit Log" />

      <Panel
        description="CI と operator が event_type を確認できる一方、payload content は redaction 済みのままです。"
        title="監査 event stream"
        titleId="audit-event-stream"
      >
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
            <caption className="sr-only">
              event_type、actor_id、reason_code、blocked_reason、
              payload_data_class、allowed_data_class、redaction status を含む監査 event。
            </caption>
            <thead className="bg-slate-50 text-xs uppercase tracking-normal text-muted">
              <tr>
                <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
                  event_type
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
                  actor_id
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
                  reason_code
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
                  blocked_reason
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
                  payload_data_class
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
                  allowed_data_class
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
                  redaction
                </th>
              </tr>
            </thead>
            <tbody>
              {AUDIT_EVENT_ROWS.map((event) => (
                <tr key={event.event_type} className="align-top">
                  <th scope="row" className="border-b border-line px-3 py-2">
                    <code className="font-mono text-xs font-semibold text-ink">
                      {event.event_type}
                    </code>
                  </th>
                  <td className="border-b border-line px-3 py-2">
                    <code className="font-mono text-xs text-ink">{event.actor_id}</code>
                  </td>
                  <td className="border-b border-line px-3 py-2">
                    <code className="font-mono text-xs text-ink">{event.reason_code}</code>
                  </td>
                  <td className="border-b border-line px-3 py-2 text-muted">
                    {event.blocked_reason === null ? (
                      <span aria-label="該当なし" className="text-muted">
                        —
                      </span>
                    ) : (
                      <code className="font-mono text-xs text-attention">
                        {event.blocked_reason}
                      </code>
                    )}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-muted">
                    {event.payload_data_class}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-muted">
                    {event.allowed_data_class}
                  </td>
                  <td className="border-b border-line px-3 py-2 text-muted">
                    {event.redaction}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        description="secret や token の値を露出せず、AC-HARD-02 を確認できるようにします。"
        title="raw secret 非表示 invariant"
        titleId="audit-secret-boundary"
      >
        <SecretBoundaryNotice title="AC-HARD-02 audit redaction" />
      </Panel>

      <Panel
        description="この skeleton では audit row は表示専用です。AI output、shortcut、UI action のいずれも audit history を変更できません。"
        title="Append-only behavior"
        titleId="audit-append-only"
      >
        <ul className="grid gap-2 text-sm text-muted md:grid-cols-3">
          <li className="rounded-md border border-line bg-white p-3">
            すべての row で event_type と actor_id が必須です。
          </li>
          <li className="rounded-md border border-line bg-white p-3">
            policy_decision_created は policy source にならず、policy outcome だけを記録します。
          </li>
          <li className="rounded-md border border-line bg-white p-3">
            runner_blocked は raw command input ではなく deny_category と reason_code を記録します。
          </li>
        </ul>
      </Panel>
    </AdminPageShell>
  );
}
