"use server";

import { BackendApiError } from "@/lib/api/client";
import {
  createOnboardingDryRunPlan,
  OnboardingDryRunPlanRequestSchema,
  type OnboardingDryRunPlan
} from "@/lib/api/onboarding";

export type OnboardingDryRunPlanActionState =
  | { kind: "idle" }
  | { kind: "ok"; plan: OnboardingDryRunPlan }
  | { kind: "error"; message: string };

export async function createOnboardingDryRunPlanAction(
  _prevState: OnboardingDryRunPlanActionState,
  formData: FormData
): Promise<OnboardingDryRunPlanActionState> {
  const parsed = OnboardingDryRunPlanRequestSchema.safeParse({
    purpose: formData.get("purpose"),
    target_repo_ref: formData.get("target_repo_ref"),
    expected_artifact: formData.get("expected_artifact"),
    allowed_action_class: formData.get("allowed_action_class"),
    budget_cap: formData.get("budget_cap"),
    starter_mode: formData.get("starter_mode")
  });

  if (!parsed.success) {
    return { kind: "error", message: "入力内容を確認してください。" };
  }

  try {
    const plan = await createOnboardingDryRunPlan(parsed.data);
    return { kind: "ok", plan };
  } catch (error: unknown) {
    if (error instanceof BackendApiError) {
      return {
        kind: "error",
        message: `dry-run API が ${error.status} を返しました。`
      };
    }
    return { kind: "error", message: "dry-run 計画を作成できませんでした。" };
  }
}
