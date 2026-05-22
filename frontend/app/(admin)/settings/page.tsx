import { BackendApiError } from "@/lib/api/client";
import { getCurrentProject, listCurrentProjects, type ProjectListItem } from "@/lib/api/session";

import {
  Panel,
  PolicyProfileList,
  ProviderComplianceMatrixTable,
  SecretBoundaryNotice
} from "../_components/sprint9-admin-ui";

export const dynamic = "force-dynamic";

type SettingsState =
  | {
      kind: "ok";
      currentProjectId: string;
      projects: ProjectListItem[];
    }
  | { kind: "error"; message: string };

async function readSettings(): Promise<SettingsState> {
  try {
    const [currentProject, projectList] = await Promise.all([
      getCurrentProject(),
      listCurrentProjects()
    ]);
    return {
      kind: "ok",
      currentProjectId: currentProject.project_id,
      projects: projectList.projects
    };
  } catch (error: unknown) {
    if (error instanceof BackendApiError) {
      return {
        kind: "error",
        message: `バックエンドが ${error.status} を返しました: ${error.message}`
      };
    }
    const message =
      error instanceof Error ? error.message : "設定情報の取得に失敗しました。";
    return { kind: "error", message };
  }
}

export default async function ProjectSettingsPage() {
  const state = await readSettings();

  return (
    <section aria-label="設定" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">設定</h1>
        <p className="mt-2 text-sm text-muted">
          project と policy/provider 境界を read-only で確認します。
        </p>
      </header>

      {state.kind === "error" ? (
        <article role="status" className="rounded-md border border-attention bg-amber-50 p-4">
          <h2 className="text-base font-semibold text-attention">設定を表示できません</h2>
          <p className="mt-1 text-sm text-muted">{state.message}</p>
        </article>
      ) : (
        <ProjectListPanel
          currentProjectId={state.currentProjectId}
          projects={state.projects}
        />
      )}

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
        description="設定は secret_ref metadata を参照できますが、raw secret resolution は SecretBroker-mediated operation の内部でのみ行います。"
        title="Secret handling (シークレット管理)"
        titleId="settings-secret-handling"
      >
        <SecretBoundaryNotice title="Settings SecretBroker boundary" />
      </Panel>
    </section>
  );
}

function ProjectListPanel({
  currentProjectId,
  projects
}: {
  currentProjectId: string;
  projects: ProjectListItem[];
}) {
  return (
    <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Project context</h2>
          <p className="mt-1 text-sm text-muted">
            current project は backend session から解決しています。切替 mutation は SP-018 で扱います。
          </p>
        </div>
        <span className="rounded-md bg-panel-muted px-2 py-1 font-mono text-xs text-muted">
          {currentProjectId}
        </span>
      </div>

      <div className="mt-4 overflow-x-auto rounded-md border border-line">
        <table className="min-w-full divide-y divide-line text-sm">
          <thead className="bg-panel-muted text-xs uppercase tracking-wide text-muted">
            <tr>
              <th scope="col" className="px-4 py-3 text-left font-medium">Project</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">Workspace</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">Status</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">Policy profile</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">Current</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {projects.map((project) => (
              <tr key={project.project_id} className="hover:bg-panel-muted">
                <th scope="row" className="px-4 py-3 text-left">
                  <div className="font-semibold">{project.name}</div>
                  <div className="font-mono text-xs text-muted">{project.slug}</div>
                </th>
                <td className="px-4 py-3 font-mono text-xs text-muted">
                  {project.workspace_id}
                </td>
                <td className="px-4 py-3">
                  <span className="rounded-md bg-panel-muted px-2 py-1 text-xs font-semibold">
                    {project.status}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-muted">
                  {project.policy_profile}
                </td>
                <td className="px-4 py-3 text-xs text-muted">
                  {project.project_id === currentProjectId ? "現在" : "切替は SP-018"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}
