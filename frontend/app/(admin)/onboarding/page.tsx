import Link from "next/link";
import type { Route } from "next";

import { BackendApiError } from "@/lib/api/client";
import {
  getCurrentProject,
  listCurrentProjects,
  type ProjectListItem
} from "@/lib/api/session";

export const dynamic = "force-dynamic";

type SourceState<T> =
  | { kind: "ok"; data: T }
  | { kind: "error"; message: string };

type OnboardingState = {
  currentProject: ProjectListItem;
  projectCount: number;
};

const STARTER_CHOICES = [
  {
    title: "AI に調査だけさせる",
    mode: "research_only",
    actionClass: "read_only",
    result: "証拠と論点の整理",
    gate: "実行なし"
  },
  {
    title: "計画だけ作らせる",
    mode: "plan_only",
    actionClass: "read_only",
    result: "rollback と test plan",
    gate: "実行なし"
  },
  {
    title: "Draft PR まで作るが承認必須",
    mode: "draft_pr_requires_approval",
    actionClass: "pr_open",
    result: "人間承認後の候補",
    gate: "承認必須"
  }
] as const;

const SAFE_LINKS = [
  { href: "/settings", label: "設定を確認" },
  { href: "/today", label: "Today を開く" },
  { href: "/timeline", label: "実行ログを確認" }
] as const satisfies readonly { href: Route; label: string }[];

async function readOnboardingState(): Promise<SourceState<OnboardingState>> {
  try {
    const [currentProject, projectList] = await Promise.all([
      getCurrentProject(),
      listCurrentProjects()
    ]);
    const project = projectList.projects.find(
      (item) => item.project_id === currentProject.project_id
    );

    if (!project) {
      return {
        kind: "error",
        message: "current project と project list が一致しません。"
      };
    }

    return {
      kind: "ok",
      data: {
        currentProject: project,
        projectCount: projectList.projects.length
      }
    };
  } catch (error: unknown) {
    return { kind: "error", message: formatReadError(error) };
  }
}

export default async function OnboardingPage() {
  const state = await readOnboardingState();

  return (
    <section aria-label="初回導線" className="grid gap-5">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理 / P0.1</p>
        <h1 className="text-3xl font-semibold tracking-normal">初回導線</h1>
        <p className="max-w-3xl text-sm text-muted">
          最初の実行前に project、policy、approval 境界を確認します。
        </p>
      </header>

      {state.kind === "error" ? (
        <ReadinessUnavailable message={state.message} />
      ) : (
        <ReadinessGrid state={state.data} />
      )}
      <StarterChoices />
      <SafeNextActions />
      <CliOnboardingPanel />
    </section>
  );
}

function ReadinessGrid({ state }: { state: OnboardingState }) {
  const project = state.currentProject;

  return (
    <section aria-label="初回チェック" className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <ReadinessCard
        detail={project.slug}
        label="project"
        status="setup_checked"
        value={project.name}
      />
      <ReadinessCard
        detail={`policy_profile: ${project.policy_profile}`}
        label="autonomy"
        status="server_owned"
        value={project.autonomy_level}
      />
      <ReadinessCard
        detail="secret / merge / deploy / provider_call"
        label="approval"
        status="human_required"
        value="blocked by default"
      />
      <ReadinessCard
        detail={`${state.projectCount} project context`}
        label="first_run"
        status="read_only"
        value="dry-run only"
      />
    </section>
  );
}

function ReadinessCard({
  detail,
  label,
  status,
  value
}: {
  detail: string;
  label: string;
  status: string;
  value: string;
}) {
  return (
    <article className="rounded-md border border-line bg-panel p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h2 className="font-mono text-xs text-muted">{label}</h2>
        <span className="rounded-md bg-panel-muted px-2 py-1 font-mono text-[11px] text-muted">
          {status}
        </span>
      </div>
      <p className="mt-3 text-lg font-semibold tracking-normal">{value}</p>
      <p className="mt-1 break-words text-xs text-muted">{detail}</p>
    </article>
  );
}

function ReadinessUnavailable({ message }: { message: string }) {
  return (
    <section
      aria-label="初回チェック"
      className="rounded-md border border-attention bg-amber-50 p-4"
      role="status"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-attention">
            Project context を確認できません
          </h2>
          <p className="mt-1 text-sm text-muted">{message}</p>
        </div>
        <span className="rounded-md bg-panel px-2 py-1 font-mono text-[11px] text-muted">
          read_only
        </span>
      </div>
      <Link
        className="mt-3 inline-flex rounded-md border border-attention px-3 py-2 text-sm font-semibold text-attention"
        href="/settings"
      >
        設定を確認
      </Link>
    </section>
  );
}

function StarterChoices() {
  return (
    <section aria-label="安全な最初の選択" className="grid gap-3">
      <div>
        <h2 className="text-lg font-semibold">安全な最初の選択</h2>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {STARTER_CHOICES.map((choice) => (
          <article key={choice.mode} className="rounded-md border border-line bg-panel p-4 shadow-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-panel-muted px-2 py-1 font-mono text-[11px] text-muted">
                {choice.mode}
              </span>
              <span className="rounded-md bg-teal-50 px-2 py-1 font-mono text-[11px] text-accent">
                {choice.actionClass}
              </span>
            </div>
            <h3 className="mt-3 text-base font-semibold">{choice.title}</h3>
            <dl className="mt-3 grid gap-2 text-sm">
              <div>
                <dt className="font-mono text-xs text-muted">result</dt>
                <dd>{choice.result}</dd>
              </div>
              <div>
                <dt className="font-mono text-xs text-muted">gate</dt>
                <dd>{choice.gate}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

function SafeNextActions() {
  return (
    <section aria-label="次の確認先" className="rounded-md border border-line bg-panel p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">次の確認先</h2>
          <p className="mt-1 text-sm text-muted">
            mutation なしで現状を確認できる画面だけを開きます。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {SAFE_LINKS.map((link) => (
            <Link
              key={link.href}
              className="rounded-md border border-line bg-panel-muted px-3 py-2 text-sm font-semibold hover:bg-line"
              href={link.href}
            >
              {link.label}
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

function CliOnboardingPanel() {
  return (
    <section aria-label="CLI 導線" className="rounded-md border border-line bg-panel p-4 shadow-sm">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(18rem,24rem)] md:items-center">
        <div>
          <h2 className="text-lg font-semibold">CLI 導線</h2>
          <p className="mt-1 text-sm text-muted">
            terminal では <code className="font-mono">tm</code> を canonical entry point として扱います。
          </p>
        </div>
        <div className="grid gap-1 rounded-md bg-panel-muted p-3 font-mono text-xs text-muted">
          <code>tm context show</code>
          <code>tm doctor</code>
          <code>tm run plan --dry-run</code>
        </div>
      </div>
    </section>
  );
}

function formatReadError(error: unknown): string {
  if (error instanceof BackendApiError) {
    return `バックエンドが ${error.status} を返しました。`;
  }
  return "プロジェクト情報を取得できません。";
}
