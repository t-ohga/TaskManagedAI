/**
 * プロジェクト設定ページ。
 *
 * Provider Compliance Matrix, policy profiles, and repository binding metadata
 * are rendered read-only. Secret refs are displayed as metadata concepts only;
 * SecretBroker remains the sole resolver.
 */

import { SessionInfo } from "@/components/session-info";
import { HelpLinks } from "@/components/help-links";
import {
  listCurrentProjects,
  listSecretRefs,
  type ProjectListItem,
  type SecretRefListItem
} from "@/lib/api/session";
import {
  AdminPageShell,
  KeyboardReadinessStrip,
  Panel,
  PolicyProfileList,
  ProviderComplianceMatrixTable,
  SecretBoundaryNotice
} from "../_components/sprint9-admin-ui";
import { ProjectSettingsForm } from "./_components/project-settings-form";
import { SecretRefsInventory } from "./_components/secret-refs-inventory";

export const dynamic = "force-dynamic";

async function loadCurrentProject(): Promise<ProjectListItem | null> {
  try {
    const res = await listCurrentProjects();
    return (
      res.projects.find((p) => p.project_id === res.current_project_id) ??
      res.projects[0] ??
      null
    );
  } catch {
    return null;
  }
}

async function loadSecretRefs(): Promise<SecretRefListItem[] | null> {
  try {
    const res = await listSecretRefs();
    return res.secret_refs;
  } catch {
    return null;
  }
}

export default async function ProjectSettingsPage() {
  const project = await loadCurrentProject();
  const secretRefs = await loadSecretRefs();

  return (
    <AdminPageShell
      description="プロバイダー準拠マトリクス、ポリシープロファイル、リポジトリ連携、シークレット管理の設定を表示します。"
      eyebrow="管理 / 設定"
      regionLabel="プロジェクト設定"
      title="プロジェクト設定"
    >
      <KeyboardReadinessStrip current="プロジェクト設定" />

      <Panel
        description="プロジェクト名・説明・AI 自律レベルを編集できます。policy_profile は autonomy_level から自動導出され UI から直接変更できません。"
        title="プロジェクト基本情報"
        titleId="settings-project-profile"
      >
        {project ? (
          <ProjectSettingsForm
            projectId={project.project_id}
            name={project.name}
            description={project.description}
            autonomyLevel={project.autonomy_level}
            policyProfile={project.policy_profile}
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            プロジェクト情報を読み込めませんでした。
          </p>
        )}
      </Panel>

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
        description="登録済シークレットのメタデータ (読み取り専用) を表示します。生のシークレット値は SecretBroker 内部でのみ解決され、UI には表示されません。"
        title="シークレット管理"
        titleId="settings-secret-handling"
      >
        <div className="grid gap-4">
          <SecretBoundaryNotice title="SecretBroker 境界" />
          {secretRefs ? (
            <SecretRefsInventory secretRefs={secretRefs} />
          ) : (
            <p className="text-sm text-muted-foreground">
              シークレット情報を読み込めませんでした。
            </p>
          )}
        </div>
      </Panel>

      <Panel
        description="現在のセッション情報。P0 は Dev Login + Tailscale 閉域を使用。"
        title="セッション"
        titleId="settings-session"
      >
        <SessionInfo actorId="dev-actor-default" />
      </Panel>

      <Panel
        description="各機能へのクイックアクセス。"
        title="ヘルプ"
        titleId="settings-help"
      >
        <HelpLinks />
      </Panel>
    </AdminPageShell>
  );
}
