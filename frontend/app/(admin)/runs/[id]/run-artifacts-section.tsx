import type { RunArtifact } from "@/lib/api/agent-runs";

// ADR-00042 L-2: AgentRun が生成した artifact の metadata inventory (read-only).
// content body / hash は表示しない (backend が返さない、metadata-only)。content drill-down は P0.1。

const KIND_LABELS: Record<string, string> = {
  plan: "計画",
  patch: "パッチ",
  evidence: "証拠",
  citation: "引用",
  other: "その他",
  cli_input: "CLI 入力",
  cli_stdout: "CLI 標準出力",
  cli_stderr: "CLI 標準エラー",
  cli_exit: "CLI 終了",
  cli_result_summary: "CLI 結果要約",
};

const TRUST_LABELS: Record<string, string> = {
  untrusted_content: "未検証",
  validated_artifact: "検証済",
  trusted_instruction: "信頼済",
};

const TRUST_COLORS: Record<string, string> = {
  untrusted_content: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300",
  validated_artifact: "bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300",
  trusted_instruction: "bg-teal-50 dark:bg-teal-950/40 text-accent",
};

const DATA_CLASS_COLORS: Record<string, string> = {
  public: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300",
  internal: "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300",
  confidential: "bg-orange-50 dark:bg-orange-950/40 text-orange-700 dark:text-orange-300",
  pii: "bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400",
};

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

export function RunArtifactsSection({
  artifacts,
  degraded,
}: {
  artifacts: RunArtifact[] | null;
  degraded: boolean;
}) {
  return (
    <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
      <h2 className="text-lg font-semibold">生成物 (Artifact)</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        この実行が生成した artifact の一覧 (種別・信頼度・分類のみ。本文は表示しません)。
      </p>
      {degraded ? (
        <p className="mt-4 text-sm text-amber-700 dark:text-amber-300">
          生成物を読み込めませんでした。
        </p>
      ) : artifacts && artifacts.length > 0 ? (
        <ul className="mt-4 grid gap-2" aria-label="生成物一覧">
          {artifacts.map((artifact) => (
            <li
              key={artifact.id}
              className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-panel px-3 py-2 text-sm"
            >
              <span className="font-medium text-ink">{kindLabel(artifact.kind)}</span>
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium ${TRUST_COLORS[artifact.trust_level] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"}`}
              >
                {TRUST_LABELS[artifact.trust_level] ?? artifact.trust_level}
              </span>
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium ${DATA_CLASS_COLORS[artifact.payload_data_class] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"}`}
              >
                {artifact.payload_data_class}
              </span>
              {artifact.parent_artifact_id ? (
                <span className="text-xs text-muted-foreground">
                  派生元: {artifact.parent_artifact_id.slice(0, 8)}...
                </span>
              ) : null}
              <span className="ml-auto text-xs text-muted-foreground">
                {artifact.created_at
                  ? new Date(artifact.created_at).toLocaleString("ja-JP")
                  : "—"}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">生成物はまだありません。</p>
      )}
    </article>
  );
}
