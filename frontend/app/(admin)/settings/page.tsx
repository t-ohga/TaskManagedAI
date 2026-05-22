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
      description="Sprint 9 BL-0108 skeleton。Anthropic Console inspired provider matrix table、policy profile visibility、SecretBroker-safe repository settings を表示します。"
      eyebrow="管理 / 設定"
      regionLabel="設定"
      title="設定"
    >
      <KeyboardReadinessStrip current="Project Settings" />

      <Panel
        description="Matrix column は P0 invariant 名と一致します。allowed_data_class は Matrix-owned であり、caller input にはしません。"
        title="Provider Compliance Matrix"
        titleId="settings-provider-compliance"
      >
        <ProviderComplianceMatrixTable />
      </Panel>

      <Panel
        description="Policy profile は operator-readable metadata として表示します。privileged mutation には引き続き server-side policy と approval check が必要です。"
        title="Policy Profiles"
        titleId="settings-policy-profiles"
      >
        <PolicyProfileList />
      </Panel>

      <Panel
        description="Repository operation は RepoProxy と GitHub App binding 経由で処理します。UI 表示は installation token を露出しません。"
        title="GitHub App Repository Binding"
        titleId="settings-repo-binding"
      >
        <dl className="grid gap-2 md:grid-cols-3">
          <div className="rounded-md border border-line bg-white p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted">
              書込経路 (write path)
            </dt>
            <dd className="mt-2 text-sm text-ink">RepoProxy のみ</dd>
          </div>
          <div className="rounded-md border border-line bg-white p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted">
              ブランチ方針 (branch policy)
            </dt>
            <dd className="mt-2 text-sm text-ink">Draft PR、main への直接 push 禁止</dd>
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
        description="設定は secret_ref metadata を参照できますが、raw secret resolution は SecretBroker-mediated operation の内部でのみ行います。"
        title="Secret handling (シークレット管理)"
        titleId="settings-secret-handling"
      >
        <SecretBoundaryNotice title="Settings SecretBroker boundary" />
      </Panel>
    </AdminPageShell>
  );
}
