import { Badge } from "@/components/ui/badge";
import type { AgentRunStatus } from "@/lib/api/agent-runs";

const STATUS_VARIANT: Record<
  AgentRunStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  queued: "outline",
  gathering_context: "outline",
  running: "default",
  generated_artifact: "default",
  schema_validated: "default",
  policy_linted: "default",
  diff_ready: "default",
  waiting_approval: "secondary",
  blocked: "destructive",
  provider_refused: "destructive",
  provider_incomplete: "secondary",
  validation_failed: "destructive",
  repair_exhausted: "destructive",
  completed: "default",
  failed: "destructive",
  cancelled: "outline",
};

const STATUS_LABEL: Record<AgentRunStatus, string> = {
  queued: "待機中",
  gathering_context: "コンテキスト収集",
  running: "実行中",
  generated_artifact: "生成完了",
  schema_validated: "検証済",
  policy_linted: "ポリシー通過",
  diff_ready: "差分準備完了",
  waiting_approval: "承認待ち",
  blocked: "ブロック",
  provider_refused: "プロバイダ拒否",
  provider_incomplete: "不完全",
  validation_failed: "検証失敗",
  repair_exhausted: "修復上限",
  completed: "完了",
  failed: "失敗",
  cancelled: "キャンセル",
};

export function AgentRunStatusBadge({ status }: { status: AgentRunStatus }) {
  return (
    <Badge variant={STATUS_VARIANT[status]} data-testid="agent-run-status">
      {STATUS_LABEL[status]}
    </Badge>
  );
}
