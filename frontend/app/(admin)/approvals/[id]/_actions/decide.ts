"use server";

import { revalidatePath } from "next/cache";

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
    return { ok: false, error: "invalid action" };
  }

  try {
    const result = await decideApproval(approvalId, {
      action,
      rationale: typeof rationale === "string" && rationale.trim() !== "" ? rationale : null
    });
    revalidatePath("/approvals");
    revalidatePath(`/approvals/${approvalId}`);
    return { ok: true, status: result.status };
  } catch (error: unknown) {
    return { ok: false, error: error instanceof Error ? error.message : "decision failed" };
  }
}

