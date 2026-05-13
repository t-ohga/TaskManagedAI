/**
 * Sprint 9 BL-0108: Project Settings (P0 UI skeleton)。
 *
 * Provider config / repo binding / policy 表示。secret_ref / installation
 * token を DOM に出さず、metadata (provider 名 / api_or_feature / version /
 * secret_ref URI) のみ表示。
 */

export const dynamic = "force-dynamic";

const PROVIDERS_WITH_MATRIX = [
  { provider: "openai", api: "responses", allowed_data_class: "internal" },
  { provider: "openai", api: "chat.completions", allowed_data_class: "internal" },
  { provider: "anthropic", api: "messages", allowed_data_class: "internal" },
  { provider: "google", api: "gemini.generate_content", allowed_data_class: "internal" }
] as const;

const POLICY_PROFILES = ["minimal_safe", "approval_required", "merge_deny"] as const;

export default function ProjectSettingsPage() {
  return (
    <section aria-label="Project Settings" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">Admin</p>
        <h1 className="text-3xl font-semibold tracking-normal">Project Settings</h1>
        <p className="mt-2 text-sm text-muted">
          Sprint 9 BL-0108 skeleton — Provider config + repo binding + policy
          profile 表示 (secret_ref 値は SecretBroker 内 resolve、DOM には出さない)。
        </p>
      </header>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">Provider Compliance Matrix (P0)</h2>
        <ul className="mt-2 grid grid-cols-1 gap-2 text-sm md:grid-cols-2">
          {PROVIDERS_WITH_MATRIX.map((entry) => (
            <li
              key={`${entry.provider}.${entry.api}`}
              className="rounded bg-muted/10 px-3 py-2"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">{entry.provider}</span>
                <span className="text-xs text-muted">
                  allowed_data_class: <code>{entry.allowed_data_class}</code>
                </span>
              </div>
              <code className="text-xs text-muted">{entry.api}</code>
            </li>
          ))}
        </ul>
      </article>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">Policy Profiles</h2>
        <ul className="mt-2 flex gap-2">
          {POLICY_PROFILES.map((profile) => (
            <li key={profile} className="rounded bg-blue-50 px-2 py-1 text-blue-700">
              <code className="text-xs">{profile}</code>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted">
          P0 default: <code>minimal_safe</code> (task_write / repo_write /
          pr_open / secret_access は approval 必須、merge / deploy は always
          deny)。
        </p>
      </article>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">GitHub App Repository Binding</h2>
        <p className="mt-2 text-sm text-muted">
          Sprint 8 で実装される RepoProxy 経由のみ branch push / Draft PR。
          installation_token は SecretBroker capability token 経由でのみ
          resolve、本 UI には出さない (ADR-00011 §採用案)。
        </p>
      </article>
    </section>
  );
}
