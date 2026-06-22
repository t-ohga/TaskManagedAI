/**
 * プロジェクト設定ページ。
 *
 * Provider Compliance Matrix, policy profiles, and repository binding metadata
 * are rendered read-only. Secret refs are displayed as metadata concepts only;
 * SecretBroker remains the sole resolver.
 */

import { cookies } from "next/headers";

import { SessionInfo } from "@/components/session-info";
import { HelpLinks } from "@/components/help-links";
import {
  DEV_SESSION_COOKIE_NAME,
  readDevLoginCookieSecret,
  verifyDevSessionCookie
} from "@/lib/auth/dev-login";
import {
  listCurrentProjects,
  listSecretRefs,
  type ProjectListItem,
  type SecretRefListItem
} from "@/lib/api/session";
import { listTickets } from "@/lib/api/tickets";
import {
  getEmergencyStopStatus,
  getGlobalKillSwitchStatus
} from "@/lib/api/emergency-stop";
import {
  AdminPageShell,
  KeyboardReadinessStrip,
  Panel,
  PolicyProfileList,
  ProviderComplianceMatrixTable,
  SecretBoundaryNotice
} from "../_components/sprint9-admin-ui";
import { AppearanceSettings } from "./_components/appearance-settings";
import { DataManagementPanel } from "./_components/data-management-panel";
import { EmergencyStopPanel } from "./_components/emergency-stop-panel";
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

// Q-3 (ADR-00037): 一括削除 CAS の baseline として現在のアクティブ ticket 件数を取得。
// total は active scope (deleted_at IS NULL) の全件 (pagination 前)。失敗時は null。
async function loadActiveTicketCount(projectId: string): Promise<number | null> {
  try {
    const res = await listTickets(projectId, { limit: 1 });
    return res.total;
  } catch {
    return null;
  }
}

// B6 (ADR-00048): 緊急停止 (latch) の状態を server fetch。owner gate は backend で enforce。
// 取得失敗時は null (panel は "読み込めませんでした" を表示し操作を出さない、fail-closed)。
async function loadEmergencyStopStatus(): Promise<{
  engaged: boolean;
  generation: number | null;
  engagedAt: string | null;
} | null> {
  try {
    const res = await getEmergencyStopStatus();
    return {
      engaged: res.engaged,
      generation: res.generation,
      engagedAt: res.engaged_at
    };
  } catch {
    return null;
  }
}

// B6 (ADR-00048 §A-8): budget global kill switch (コスト緊急停止) の状態を server fetch。失敗時 null。
async function loadGlobalKillSwitchStatus(): Promise<{ engaged: boolean } | null> {
  try {
    const res = await getGlobalKillSwitchStatus();
    return { engaged: res.engaged };
  } catch {
    return null;
  }
}

// R-1 残り時間ラベルを組み立てる。現在時刻計算 (impure) は data loader 内に閉じ、
// SessionInfo component は pure に保つ。
function formatSessionRemaining(remainingMs: number): string {
  if (remainingMs <= 0) return "期限切れ";
  const totalMinutes = Math.floor(remainingMs / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0) return `あと約 ${hours} 時間 ${minutes} 分`;
  return `あと約 ${minutes} 分`;
}

// R-1 セッションタイムアウト表示: dev session cookie を検証し、実 actorId と有効期限を取得する
// (これまで SessionInfo に hardcode の "dev-actor-default" を渡していた)。失敗時は null。
async function loadSessionInfo(): Promise<
  {
    actorId: string;
    expiresAt: string;
    remainingLabel: string;
    lastLoginAt: string | null;
  } | null
> {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get(DEV_SESSION_COOKIE_NAME);
    if (!sessionCookie) return null;
    const session = await verifyDevSessionCookie(
      sessionCookie.value,
      readDevLoginCookieSecret()
    );
    if (!session) return null;
    const remainingMs = session.expiresAt.getTime() - Date.now();
    return {
      actorId: session.actor.actorId,
      expiresAt: session.expiresAt.toISOString(),
      remainingLabel: formatSessionRemaining(remainingMs),
      // R-2 (ADR-00043): iat 由来の最終ログイン日時。iat 無 cookie は null。
      lastLoginAt: session.issuedAt ? session.issuedAt.toISOString() : null
    };
  } catch {
    return null;
  }
}

export default async function ProjectSettingsPage() {
  const project = await loadCurrentProject();
  const secretRefs = await loadSecretRefs();
  const sessionInfo = await loadSessionInfo();
  const activeTicketCount = project
    ? await loadActiveTicketCount(project.project_id)
    : null;
  const emergencyStop = await loadEmergencyStopStatus();
  const budgetKillSwitch = await loadGlobalKillSwitchStatus();

  return (
    <AdminPageShell
      description="プロバイダー準拠マトリクス、ポリシープロファイル、リポジトリ連携、シークレット管理の設定を表示します。"
      eyebrow="管理 / 設定"
      regionLabel="プロジェクト設定"
      title="プロジェクト設定"
    >
      <KeyboardReadinessStrip current="プロジェクト設定" />

      {/* M-2 (ADR-00047): 外観 (テーマ) = この端末の表示設定。project 設定とは別の device-local
          preference であることを description で明示する (R1 F-008)。 */}
      <Panel
        description="この端末の表示テーマ（ライト / ダーク / システム）を選びます。ブラウザごとの表示設定で、プロジェクトの設定ではありません。"
        title="外観（この端末の表示設定）"
        titleId="settings-appearance"
      >
        <AppearanceSettings />
      </Panel>

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

      {/* B6 (ADR-00048): 緊急停止 (kill switch) の operator 導線。破壊的かつ安全弁の操作 UI のため
          印刷物には出さない (.no-print)。owner gate は backend で enforce。 */}
      <div className="no-print">
        <Panel
          description="人間がいつでも全 AI を即停止できる安全弁。新規 AI 活動の全面拒否と実行中エージェントの停止を行います。owner のみ操作でき、監査に記録されます。"
          title="緊急停止 (キルスイッチ)"
          titleId="settings-emergency-stop"
        >
          <EmergencyStopPanel
            latch={emergencyStop}
            budgetKillSwitch={budgetKillSwitch}
          />
        </Panel>
      </div>

      {/* S-1: データ管理は破壊的操作 (アーカイブ / 一括削除・復元・インポート) のみの操作 UI。
          印刷物 (設定スナップショット / 監査出力) には出さない (.no-print)。 */}
      <div className="no-print">
        <Panel
          description="プロジェクトのアーカイブ、ticket の一括削除・復元・インポート。いずれも owner のみ、監査に記録される破壊的操作です (soft / 可逆)。"
          title="データ管理"
          titleId="settings-data-management"
        >
          {project ? (
            <DataManagementPanel
              projectId={project.project_id}
              status={project.status}
              activeTicketCount={activeTicketCount ?? 0}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              プロジェクト情報を読み込めませんでした。
            </p>
          )}
        </Panel>
      </div>

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
          <div className="rounded-md border border-line bg-panel p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">
              write path
            </dt>
            <dd className="mt-2 text-sm text-ink">RepoProxy のみ</dd>
          </div>
          <div className="rounded-md border border-line bg-panel p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">
              branch policy
            </dt>
            <dd className="mt-2 text-sm text-ink">Draft PR のみ（main 直接 push 不可）</dd>
          </div>
          <div className="rounded-md border border-line bg-panel p-3">
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
        <SessionInfo
          actorId={sessionInfo?.actorId ?? null}
          expiresAt={sessionInfo?.expiresAt ?? null}
          remainingLabel={sessionInfo?.remainingLabel ?? null}
          lastLoginAt={sessionInfo?.lastLoginAt ?? null}
        />
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
