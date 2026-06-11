"use server";

import { decideApproval } from "@/lib/api/approvals";

export type DecideActionResult =
  | { ok: true; status: string }
  | { ok: false; error: string };

export async function decideApprovalAction(
  approvalId: string,
  formData: FormData
): Promise<DecideActionResult> {
  const action = formData.get("action");
  const rationale = formData.get("rationale");

  if (action !== "approve" && action !== "reject") {
    return { ok: false, error: "不正な action です" };
  }

  try {
    const result = await decideApproval(approvalId, {
      action,
      rationale: typeof rationale === "string" && rationale.trim() !== "" ? rationale : null
    });
    // C-5 系統適用: Server Action 内 revalidatePath() は client transition の isPending を解除せず
    // 確率的に未 commit になる Next.js 16 (16.2.6) + React 19 regression。撤去し、表示更新は
    // 呼び出し側の full reload (useDeferredRouterRefresh) に委譲する
    // (撤去前: revalidatePath("/approvals") + revalidatePath(`/approvals/${approvalId}`))。
    // 参照: vercel/next.js discussions #82289 / #88767。
    return { ok: true, status: result.status };
  } catch (error: unknown) {
    return { ok: false, error: error instanceof Error ? error.message : "判定に失敗しました" };
  }
}
