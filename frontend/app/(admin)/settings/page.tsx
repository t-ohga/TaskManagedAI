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
      description="プロジェクト設定 with Anthropic Console inspired provider matrix table, policy profile visibility, and SecretBroker-safe repository settings."
      eyebrow="管理 / 設定"
      regionLabel="プロジェクト設定"
      title="プロジェクト設定"
    >
      <KeyboardReadinessStrip current="プロジェクト設定" />

      <Panel
        description="P0 不変条件に準拠。allowed_data_class はマトリクス管理で、呼び出し元から入力不可。"
        title="プロバイダー準拠マトリクス"
        titleId="settings-provider-compliance"
      >
        <ProviderComplianceMatrixTable />
      </Panel>

      <Panel
        description="ポリシープロファイルは読み取り専用で表示。変更にはサーバー側のポリシーチェックと承認が必要。"
        title="ポリシープロファイル"
        titleId="settings-policy-profiles"
      >
        <PolicyProfileList />
      </Panel>

      <Panel
        description="リポジトリ操作は RepoProxy と GitHub App 経由。UI にインストールトークンは表示されません。"
        title="GitHub App リポジトリ連携"
        titleId="settings-repo-binding"
      >
        <dl className="grid gap-2 md:grid-cols-3">
          <div className="rounded-md border border-line bg-white p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">
              write path
            </dt>
            <dd className="mt-2 text-sm text-ink">RepoProxy のみ</dd>
          </div>
          <div className="rounded-md border border-line bg-white p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">
              branch policy
            </dt>
            <dd className="mt-2 text-sm text-ink">Draft PR のみ（main 直接 push 不可）</dd>
          </div>
          <div className="rounded-md border border-line bg-white p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">
              merge guard
            </dt>
            <dd className="mt-2 text-sm text-ink">
              <code className="font-mono text-xs text-danger">merge_deny</code>
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel
        description="secret_ref のメタデータは参照可能。生のシークレット値は SecretBroker 内部でのみ解決されます。"
        title="シークレット管理"
        titleId="settings-secret-handling"
      >
        <SecretBoundaryNotice title="SecretBroker 境界" />
      </Panel>
    </AdminPageShell>
  );
}
