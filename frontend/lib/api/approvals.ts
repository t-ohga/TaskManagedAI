import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";

export const ActionClassEnum = z.enum([
  "task_write",
  "repo_write",
  "pr_open",
  "secret_access",
  "merge",
  "deploy",
  "provider_call"
]);

export const ApprovalStatusEnum = z.enum([
  "pending",
  "approved",
  "rejected",
  "expired",
  "invalidated"
]);

export const RiskLevelEnum = z.enum(["low", "medium", "high", "critical"]);

export const ApprovalListItemSchema = z.object({
  id: z.string().uuid(),
  action_class: ActionClassEnum,
  resource_ref: z.string(),
  risk_level: RiskLevelEnum,
  status: ApprovalStatusEnum,
  requested_by_actor_id: z.string().uuid(),
  requested_at: z.string()
});

export type ApprovalListItem = z.infer<typeof ApprovalListItemSchema>;

export const ApprovalDetailSchema = ApprovalListItemSchema.extend({
  decided_by_actor_id: z.string().uuid().nullable(),
  decided_at: z.string().nullable(),
  rationale: z.string().nullable(),
  artifact_hash: z.string().nullable(),
  diff_hash: z.string().nullable(),
  policy_version: z.string(),
  policy_pack_lock: z.string().nullable(),
  provider_request_fingerprint: z.string().nullable()
});

export type ApprovalDetail = z.infer<typeof ApprovalDetailSchema>;

export const DecideRequestSchema = z.object({
  action: z.enum(["approve", "reject"]),
  rationale: z.string().nullable()
});

export type DecideRequest = z.infer<typeof DecideRequestSchema>;

export type ApprovalStatus = z.infer<typeof ApprovalStatusEnum>;

export async function listApprovals(
  options: { status?: ApprovalStatus } = {}
): Promise<ApprovalListItem[]> {
  const params = new URLSearchParams();
  if (options.status) {
    params.set("status", options.status);
  }
  const query = params.toString();
  const path = query ? `/api/v1/approvals?${query}` : "/api/v1/approvals";
  return fetchBackendJson(path as `/${string}`, z.array(ApprovalListItemSchema), {
    headers: { accept: "application/json" }
  });
}

export async function listPendingApprovals(): Promise<ApprovalListItem[]> {
  return listApprovals({ status: "pending" });
}

export async function getApprovalDetail(approvalId: string): Promise<ApprovalDetail> {
  return fetchBackendJson(`/api/v1/approvals/${approvalId}`, ApprovalDetailSchema, {
    headers: { accept: "application/json" }
  });
}

export async function decideApproval(
  approvalId: string,
  body: DecideRequest
): Promise<ApprovalDetail> {
  return fetchBackendJson(`/api/v1/approvals/${approvalId}/decide`, ApprovalDetailSchema, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json"
    },
    body: JSON.stringify(DecideRequestSchema.parse(body))
  });
}
