import type { ApprovalDetail } from "@/lib/api/approvals";

type ActionClass = ApprovalDetail["action_class"];
type ApprovalStatus = ApprovalDetail["status"];
type RiskLevel = ApprovalDetail["risk_level"];

export const APPROVAL_ACTION_CLASS_LABELS: Record<ActionClass, string> = {
  task_write: "タスク更新",
  repo_write: "リポジトリ書込",
  pr_open: "PR 作成",
  secret_access: "Secret 参照",
  merge: "マージ",
  deploy: "デプロイ",
  provider_call: "Provider 呼び出し"
};

export const APPROVAL_STATUS_LABELS: Record<ApprovalStatus, string> = {
  pending: "承認待ち",
  approved: "承認済み",
  rejected: "却下済み",
  expired: "期限切れ",
  invalidated: "無効化済み"
};

export const RISK_LEVEL_LABELS: Record<RiskLevel, string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "緊急"
};

export function formatApprovalActionClass(actionClass: ActionClass): string {
  return `${APPROVAL_ACTION_CLASS_LABELS[actionClass]} (${actionClass})`;
}

export function formatApprovalStatus(status: ApprovalStatus | string): string {
  return status in APPROVAL_STATUS_LABELS
    ? `${APPROVAL_STATUS_LABELS[status as ApprovalStatus]} (${status})`
    : status;
}

export function formatRiskLevel(riskLevel: RiskLevel): string {
  return `${RISK_LEVEL_LABELS[riskLevel]} (${riskLevel})`;
}
