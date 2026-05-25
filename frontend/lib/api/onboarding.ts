import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";

export const OnboardingStarterModeSchema = z.enum([
  "research_only",
  "plan_only",
  "draft_pr_requires_approval"
]);

export const OnboardingActionClassSchema = z.enum([
  "read_only",
  "task_write",
  "repo_write",
  "pr_open"
]);

export const OnboardingPolicyEffectSchema = z.enum([
  "allow",
  "deny",
  "require_approval"
]);

export const OnboardingRiskLevelSchema = z.enum(["low", "medium", "high"]);

export const OnboardingSafeRouteSchema = z.enum([
  "/settings",
  "/today",
  "/timeline",
  "/approvals",
  "/runs"
]);

const optionalTrimmedString = (maxLength: number) =>
  z.preprocess(
    (value) =>
      value == null || (typeof value === "string" && value.trim() === "")
        ? undefined
        : value,
    z.string().trim().max(maxLength).optional()
  );

export const OnboardingDryRunPlanRequestSchema = z
  .object({
    purpose: z.string().trim().min(1).max(4000),
    target_repo_ref: optionalTrimmedString(500),
    expected_artifact: z.string().trim().min(1).max(1000),
    allowed_action_class: OnboardingActionClassSchema,
    budget_cap: optionalTrimmedString(100),
    starter_mode: OnboardingStarterModeSchema
  })
  .strict();

export const OnboardingDryRunWouldCreateSchema = z
  .object({
    ticket: z.literal(false),
    agent_run: z.literal(false),
    approval: z.literal(false),
    notification: z.literal(false),
    audit_event: z.literal(false),
    repository_operation: z.literal(false),
    provider_call: z.literal(false)
  })
  .strict();

export const OnboardingDryRunPlanSchema = z
  .object({
    starter_mode: OnboardingStarterModeSchema,
    requested_action_class: OnboardingActionClassSchema,
    effective_action_class: OnboardingActionClassSchema,
    policy_effect: OnboardingPolicyEffectSchema,
    approval_required: z.boolean(),
    risk_level: OnboardingRiskLevelSchema,
    estimated_cost: z.string(),
    rollback_plan: z.string(),
    test_plan: z.array(z.string()),
    blocked_reasons: z.array(z.string()),
    next_safe_routes: z.array(OnboardingSafeRouteSchema),
    would_create: OnboardingDryRunWouldCreateSchema
  })
  .strict();

export const OnboardingDryRunPlanResponseSchema = z
  .object({
    dry_run_plan: OnboardingDryRunPlanSchema
  })
  .strict();

export type OnboardingDryRunPlanRequest = z.infer<
  typeof OnboardingDryRunPlanRequestSchema
>;
export type OnboardingDryRunPlan = z.infer<typeof OnboardingDryRunPlanSchema>;
export type OnboardingSafeRoute = z.infer<typeof OnboardingSafeRouteSchema>;

export async function createOnboardingDryRunPlan(
  request: OnboardingDryRunPlanRequest
): Promise<OnboardingDryRunPlan> {
  const payload = OnboardingDryRunPlanRequestSchema.parse(request);
  const response = await fetchBackendJson(
    "/api/v1/onboarding/dry_run_plan",
    OnboardingDryRunPlanResponseSchema,
    {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json"
      },
      body: JSON.stringify(payload)
    }
  );
  return response.dry_run_plan;
}
