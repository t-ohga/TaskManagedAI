"use server";

import { z } from "zod";

import { requestApprovalRevision } from "@/lib/api/approvals";

const ApprovalIdSchema = z.string().uuid();
const RevisionRationaleSchema = z.string().trim().min(1).max(2000);

export type RequestRevisionActionResult =
  | {
      ok: true;
      status: string;
      revisionRequestId: string;
    }
  | { ok: false; error: string };

export async function requestApprovalRevisionAction(
  approvalId: string,
  formData: FormData
): Promise<RequestRevisionActionResult> {
  const parsedApprovalId = ApprovalIdSchema.safeParse(approvalId);
  if (!parsedApprovalId.success) {
    return { ok: false, error: "不正な承認 ID です" };
  }

  const rationale = formData.get("rationale");
  if (typeof rationale !== "string") {
    return { ok: false, error: "修正理由を入力してください" };
  }

  const parsedRationale = RevisionRationaleSchema.safeParse(rationale);
  if (!parsedRationale.success) {
    return { ok: false, error: "修正理由は 1〜2000 文字で入力してください" };
  }

  try {
    const result = await requestApprovalRevision(parsedApprovalId.data, {
      rationale: parsedRationale.data
    });
    // C-5 系統適用: Server Action 内 revalidatePath() は client transition の isPending を解除せず
    // 確率的に未 commit になる Next.js 16 (16.2.6) + React 19 regression。撤去し、表示更新は
    // 呼び出し側の full reload (useDeferredRouterRefresh) に委譲する
    // (撤去前: revalidatePath("/approvals") + revalidatePath(`/approvals/${id}`))。
    // 参照: vercel/next.js discussions #82289 / #88767。
    return {
      ok: true,
      status: result.approval.status,
      revisionRequestId: result.revision_request_id
    };
  } catch (error: unknown) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "修正依頼に失敗しました"
    };
  }
}
