"use client";

import Link from "next/link";
import type { Route } from "next";
import { useActionState } from "react";

import type { OnboardingDryRunPlan, OnboardingSafeRoute } from "@/lib/api/onboarding";

import {
  createOnboardingDryRunPlanAction,
  type OnboardingDryRunPlanActionState
} from "../actions";

const INITIAL_STATE: OnboardingDryRunPlanActionState = { kind: "idle" };

const SAFE_ROUTE_LABELS: Record<OnboardingSafeRoute, string> = {
  "/settings": "設定",
  "/today": "Today",
  "/timeline": "実行ログ",
  "/approvals": "承認",
  "/runs": "Runs"
};

export function DryRunPlanForm() {
  const [state, formAction, isPending] = useActionState(
    createOnboardingDryRunPlanAction,
    INITIAL_STATE
  );

  return (
    <section aria-label="dry-run 計画レビュー" className="grid gap-3">
      <div>
        <h2 className="text-lg font-semibold">dry-run 計画レビュー</h2>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <form action={formAction} className="rounded-md border border-line bg-panel p-4 shadow-sm">
          <fieldset className="grid gap-4" disabled={isPending}>
            <legend className="font-semibold">guided intake</legend>

            <label className="grid gap-2 text-sm">
              <span className="font-medium">目的</span>
              <textarea
                className="min-h-28 resize-y rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                maxLength={4000}
                name="purpose"
                placeholder="調査、計画、または Draft PR 候補の目的"
                required
              />
            </label>

            <label className="grid gap-2 text-sm">
              <span className="font-medium">想定成果物</span>
              <input
                className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                maxLength={1000}
                name="expected_artifact"
                placeholder="実装計画、調査メモ、Draft PR plan"
                required
              />
            </label>

            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-2 text-sm">
                <span className="font-medium">starter mode</span>
                <select
                  className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  defaultValue="plan_only"
                  name="starter_mode"
                >
                  <option value="research_only">research_only</option>
                  <option value="plan_only">plan_only</option>
                  <option value="draft_pr_requires_approval">
                    draft_pr_requires_approval
                  </option>
                </select>
              </label>

              <label className="grid gap-2 text-sm">
                <span className="font-medium">upper action class</span>
                <select
                  className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  defaultValue="read_only"
                  name="allowed_action_class"
                >
                  <option value="read_only">read_only</option>
                  <option value="task_write">task_write</option>
                  <option value="repo_write">repo_write</option>
                  <option value="pr_open">pr_open</option>
                </select>
              </label>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-2 text-sm">
                <span className="font-medium">repo ref</span>
                <input
                  className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  maxLength={500}
                  name="target_repo_ref"
                  placeholder="owner/repo or local workspace"
                />
              </label>

              <label className="grid gap-2 text-sm">
                <span className="font-medium">budget cap</span>
                <input
                  className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  maxLength={100}
                  name="budget_cap"
                  placeholder="0 USD committed"
                />
              </label>
            </div>

            <button
              className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-accent/90 disabled:opacity-60"
              type="submit"
            >
              {isPending ? "dry-run 作成中..." : "dry-run 計画を作成"}
            </button>
          </fieldset>

          {state.kind === "error" ? (
            <p className="mt-4 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700" role="status">
              {state.message}
            </p>
          ) : null}
        </form>

        {state.kind === "ok" ? (
          <DryRunPlanReview plan={state.plan} />
        ) : (
          <DryRunEmptyState />
        )}
      </div>
    </section>
  );
}

function DryRunEmptyState() {
  return (
    <section
      aria-label="dry-run 結果"
      className="rounded-md border border-line bg-panel-muted p-4 text-sm text-muted"
    >
      <h3 className="font-semibold text-fg">dry-run 結果</h3>
      <p className="mt-2">
        ここには response-only の計画だけを表示します。承認や実行開始は作成しません。
      </p>
    </section>
  );
}

export function DryRunPlanReview({ plan }: { plan: OnboardingDryRunPlan }) {
  return (
    <section aria-label="dry-run 結果" className="grid gap-4 rounded-md border border-line bg-panel p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">dry-run 結果</h3>
          <p className="mt-1 text-sm text-muted">{plan.estimated_cost}</p>
        </div>
        <span className="rounded-md bg-panel-muted px-2 py-1 font-mono text-[11px] text-muted">
          {plan.risk_level}
        </span>
      </div>

      <dl className="grid gap-3 text-sm md:grid-cols-2">
        <PlanFact label="starter" value={plan.starter_mode} />
        <PlanFact label="requested" value={plan.requested_action_class} />
        <PlanFact label="effective" value={plan.effective_action_class} />
        <PlanFact label="policy" value={plan.policy_effect} />
        <PlanFact label="approval" value={plan.approval_required ? "required" : "not required"} />
        <PlanFact label="rollback" value={plan.rollback_plan} />
      </dl>

      <div className="grid gap-3 lg:grid-cols-2">
        <ListBlock label="test plan" values={plan.test_plan} />
        <ListBlock label="blocked reasons" values={plan.blocked_reasons} />
      </div>

      <section aria-label="would_create ledger" className="rounded-md bg-panel-muted p-3">
        <h4 className="font-mono text-xs text-muted">would_create</h4>
        <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
          {Object.entries(plan.would_create).map(([key, value]) => (
            <div key={key} className="flex items-center justify-between gap-3">
              <dt className="font-mono text-xs text-muted">{key}</dt>
              <dd className="font-mono text-xs">{String(value)}</dd>
            </div>
          ))}
        </dl>
      </section>

      <div className="flex flex-wrap gap-2">
        {plan.next_safe_routes.map((route) => (
          <Link
            className="rounded-md border border-line bg-panel-muted px-3 py-2 text-sm font-semibold hover:bg-line"
            href={route as Route}
            key={route}
          >
            {SAFE_ROUTE_LABELS[route]}
          </Link>
        ))}
      </div>

      <details className="rounded-md border border-line bg-panel-muted p-3 text-sm">
        <summary className="cursor-pointer font-semibold">理由を見る</summary>
        <p className="mt-2 text-muted">
          この結果は dry-run API の response-only deterministic response です。実行状態や承認レコードは作成していません。
        </p>
      </details>
    </section>
  );
}

function PlanFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-panel-muted p-3">
      <dt className="font-mono text-xs text-muted">{label}</dt>
      <dd className="mt-1 break-words font-semibold">{value}</dd>
    </div>
  );
}

function ListBlock({ label, values }: { label: string; values: string[] }) {
  return (
    <section className="rounded-md bg-panel-muted p-3">
      <h4 className="font-mono text-xs text-muted">{label}</h4>
      <ul className="mt-2 grid gap-2 text-sm">
        {values.map((value) => (
          <li className="break-words" key={value}>
            {value}
          </li>
        ))}
      </ul>
    </section>
  );
}
