/**
 * Sprint 9 BL-0108: Project Settings (P0 UI skeleton).
 *
 * Provider Compliance Matrix, policy profiles, and repository binding metadata
 * are rendered read-only. Secret refs are displayed as metadata concepts only;
 * SecretBroker remains the sole resolver.
 */

import {
  AdminPageShell,
  KeyboardReadinessStrip,
  Panel,
  PolicyProfileList,
  ProviderComplianceMatrixTable,
  SecretBoundaryNotice
} from "../_components/sprint9-admin-ui";

export const dynamic = "force-dynamic";

export default function ProjectSettingsPage() {
  return (
    <AdminPageShell
      description="Sprint 9 BL-0108 skeleton with Anthropic Console inspired provider matrix table, policy profile visibility, and SecretBroker-safe repository settings."
      eyebrow="Admin / Settings"
      regionLabel="Project Settings"
      title="Project Settings"
    >
      <KeyboardReadinessStrip current="Project Settings" />

      <Panel
        description="Matrix columns match the P0 invariant names. allowed_data_class remains matrix-owned and is never caller input."
        title="Provider Compliance Matrix"
        titleId="settings-provider-compliance"
      >
        <ProviderComplianceMatrixTable />
      </Panel>

      <Panel
        description="Policy profiles are shown as operator-readable metadata; privileged mutation still requires server-side policy and approval checks."
        title="Policy Profiles"
        titleId="settings-policy-profiles"
      >
        <PolicyProfileList />
      </Panel>

      <Panel
        description="Repository operations are routed through RepoProxy and GitHub App binding. UI display does not expose installation tokens."
        title="GitHub App Repository Binding"
        titleId="settings-repo-binding"
      >
        <dl className="grid gap-2 md:grid-cols-3">
          <div className="rounded-md border border-line bg-white p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted">
              write path
            </dt>
            <dd className="mt-2 text-sm text-ink">RepoProxy only</dd>
          </div>
          <div className="rounded-md border border-line bg-white p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted">
              branch policy
            </dt>
            <dd className="mt-2 text-sm text-ink">Draft PR, no direct main push</dd>
          </div>
          <div className="rounded-md border border-line bg-white p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted">
              merge guard
            </dt>
            <dd className="mt-2 text-sm text-ink">
              <code className="font-mono text-xs text-danger">merge_deny</code>
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel
        description="Settings can reference secret_ref metadata, but raw secret resolution happens only inside SecretBroker-mediated operations."
        title="Secret handling"
        titleId="settings-secret-handling"
      >
        <SecretBoundaryNotice title="Settings SecretBroker boundary" />
      </Panel>
    </AdminPageShell>
  );
}
