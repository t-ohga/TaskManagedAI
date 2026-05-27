type AgentRunStatus =
  | "queued" | "gathering_context" | "running"
  | "generated_artifact" | "schema_validated" | "policy_linted"
  | "diff_ready" | "waiting_approval" | "blocked"
  | "provider_refused" | "provider_incomplete" | "validation_failed"
  | "repair_exhausted" | "completed" | "failed" | "cancelled";

type BlockedReason = "policy_blocked" | "budget_blocked" | "runtime_blocked";

const STATUS_CONFIG: Record<AgentRunStatus, { color: string; label: string }> = {
  queued: { color: "bg-purple-500", label: "待機中" },
  gathering_context: { color: "bg-amber-400", label: "情報収集中" },
  running: { color: "bg-amber-500", label: "進行中" },
  generated_artifact: { color: "bg-teal-500", label: "成果物生成" },
  schema_validated: { color: "bg-teal-500", label: "検証済み" },
  policy_linted: { color: "bg-teal-500", label: "ポリシー通過" },
  diff_ready: { color: "bg-teal-500", label: "差分準備完了" },
  waiting_approval: { color: "bg-purple-500", label: "承認待ち" },
  blocked: { color: "bg-orange-500", label: "ブロック" },
  provider_refused: { color: "bg-red-600", label: "拒否" },
  provider_incomplete: { color: "bg-amber-600", label: "未完了" },
  validation_failed: { color: "bg-red-400", label: "検証失敗" },
  repair_exhausted: { color: "bg-red-700", label: "修復不能" },
  completed: { color: "bg-emerald-500", label: "完了" },
  failed: { color: "bg-red-500", label: "失敗" },
  cancelled: { color: "bg-gray-400", label: "中止" },
};

const BLOCKED_REASON_CONFIG: Record<BlockedReason, { color: string; label: string }> = {
  policy_blocked: { color: "bg-red-500", label: "ポリシー拒否" },
  budget_blocked: { color: "bg-yellow-500", label: "予算超過" },
  runtime_blocked: { color: "bg-orange-500", label: "ランタイム拒否" },
};

type Props = {
  status: string;
  blockedReason?: string | null;
};

export function AgentRunStatusIndicator({ status, blockedReason }: Props) {
  const config = STATUS_CONFIG[status as AgentRunStatus] ?? {
    color: "bg-gray-300",
    label: status,
  };

  if (status === "blocked" && blockedReason) {
    const reasonConfig = BLOCKED_REASON_CONFIG[blockedReason as BlockedReason];
    if (reasonConfig) {
      return (
        <span className="inline-flex items-center gap-1.5">
          <span className={`inline-block h-2 w-2 rounded-full ${reasonConfig.color}`} aria-hidden="true" />
          <span className="text-xs font-medium">{reasonConfig.label}</span>
        </span>
      );
    }
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block h-2 w-2 rounded-full ${config.color}`} aria-hidden="true" />
      <span className="text-xs font-medium">{config.label}</span>
    </span>
  );
}

export const AGENT_RUN_STATUSES = Object.keys(STATUS_CONFIG) as AgentRunStatus[];
export const BLOCKED_REASONS = Object.keys(BLOCKED_REASON_CONFIG) as BlockedReason[];
