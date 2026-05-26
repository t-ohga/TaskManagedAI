import { Badge } from "@/components/ui/badge";

type ApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "invalidated";

const STATUS_VARIANT: Record<
  ApprovalStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  pending: "secondary",
  approved: "default",
  rejected: "destructive",
  expired: "outline",
  invalidated: "outline",
};

const STATUS_LABEL: Record<ApprovalStatus, string> = {
  pending: "承認待ち",
  approved: "承認済み",
  rejected: "却下",
  expired: "期限切れ",
  invalidated: "無効化",
};

export function ApprovalStatusBadge({ status }: { status: ApprovalStatus }) {
  return (
    <Badge variant={STATUS_VARIANT[status]} data-testid="approval-status">
      {STATUS_LABEL[status]}
    </Badge>
  );
}
