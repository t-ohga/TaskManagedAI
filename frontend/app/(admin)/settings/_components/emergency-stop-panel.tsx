"use client";

import { useActionState, useState } from "react";

import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";

import {
  clearEmergencyStopAction,
  clearGlobalKillSwitchAction,
  engageEmergencyStopAction,
  engageGlobalKillSwitchAction,
  type EmergencyStopActionState
} from "../emergency-stop-actions";

/**
 * 緊急停止 (kill switch) operator パネル (SP-PHASE1 B6、ADR-00048 §D)。
 *
 * - emergency-stop latch (human 即時全停止): 状態表示 + 有効化 (理由任意) + 解除 (世代 CAS)。
 * - budget global kill switch (コスト緊急停止、A-8): 状態表示 + 有効化 / 解除。
 *
 * 確認は二段階 (確認ステップ → 確定)。alert/confirm の JS dialog は使わない (data-management-panel 踏襲)。
 * owner gate は backend で enforce。本 component は status 値の表示と action 呼び出しのみ (pure client)。
 */

type EmergencyStopLatchStatus = {
  engaged: boolean;
  generation: number | null;
  engagedAt: string | null;
};

type BudgetKillSwitchStatus = {
  engaged: boolean;
};

type EmergencyStopPanelProps = {
  latch: EmergencyStopLatchStatus | null;
  budgetKillSwitch: BudgetKillSwitchStatus | null;
};

const INITIAL_STATE: EmergencyStopActionState = { kind: "idle" };

function StatusMessage({ state }: { state: EmergencyStopActionState }) {
  if (state.kind === "error") {
    return (
      <p
        role="status"
        className="rounded-md bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-sm text-rose-700 dark:text-rose-300"
      >
        {state.message}
      </p>
    );
  }
  if (state.kind === "ok") {
    return (
      <p
        role="status"
        className="rounded-md bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300"
      >
        {state.message}
      </p>
    );
  }
  return null;
}

function EngagedBadge({ engaged }: { engaged: boolean }) {
  return (
    <span
      className={
        engaged
          ? "inline-flex items-center rounded-full bg-rose-100 dark:bg-rose-900/40 px-2.5 py-0.5 text-xs font-semibold text-rose-800 dark:text-rose-300"
          : "inline-flex items-center rounded-full bg-emerald-100 dark:bg-emerald-900/40 px-2.5 py-0.5 text-xs font-semibold text-emerald-800 dark:text-emerald-300"
      }
    >
      {engaged ? "停止中" : "稼働中"}
    </span>
  );
}

export function EmergencyStopPanel({ latch, budgetKillSwitch }: EmergencyStopPanelProps) {
  const requestRefresh = useDeferredRouterRefresh();

  const [engageConfirming, setEngageConfirming] = useState(false);
  const [clearConfirming, setClearConfirming] = useState(false);
  const [budgetEngageConfirming, setBudgetEngageConfirming] = useState(false);
  const [budgetClearConfirming, setBudgetClearConfirming] = useState(false);
  const [reason, setReason] = useState("");

  const [engageState, engageAction, engagePending] = useActionState(
    async (prev: EmergencyStopActionState, formData: FormData) => {
      const result = await engageEmergencyStopAction(prev, formData);
      if (result.kind === "ok") {
        setEngageConfirming(false);
        setReason("");
        requestRefresh();
      }
      return result;
    },
    INITIAL_STATE
  );
  const [clearState, clearAction, clearPending] = useActionState(
    async (prev: EmergencyStopActionState, formData: FormData) => {
      const result = await clearEmergencyStopAction(prev, formData);
      if (result.kind === "ok") {
        setClearConfirming(false);
        requestRefresh();
      }
      return result;
    },
    INITIAL_STATE
  );
  const [budgetEngageState, budgetEngageAction, budgetEngagePending] = useActionState(
    async (prev: EmergencyStopActionState, formData: FormData) => {
      const result = await engageGlobalKillSwitchAction(prev, formData);
      if (result.kind === "ok") {
        setBudgetEngageConfirming(false);
        requestRefresh();
      }
      return result;
    },
    INITIAL_STATE
  );
  const [budgetClearState, budgetClearAction, budgetClearPending] = useActionState(
    async (prev: EmergencyStopActionState, formData: FormData) => {
      const result = await clearGlobalKillSwitchAction(prev, formData);
      if (result.kind === "ok") {
        setBudgetClearConfirming(false);
        requestRefresh();
      }
      return result;
    },
    INITIAL_STATE
  );

  const anyPending =
    engagePending || clearPending || budgetEngagePending || budgetClearPending;

  const latchEngaged = latch?.engaged ?? false;
  const latchUnavailable = latch === null;
  const generation = latch?.generation ?? null;
  const budgetEngaged = budgetKillSwitch?.engaged ?? false;
  const budgetUnavailable = budgetKillSwitch === null;

  return (
    <div className="grid gap-8">
      {/* emergency-stop latch (human 即時全停止) */}
      <section className="grid gap-3" aria-labelledby="emergency-stop-latch">
        <div className="flex items-center gap-3">
          <h3 id="emergency-stop-latch" className="text-sm font-semibold text-ink">
            全 AI の即時停止 (緊急停止)
          </h3>
          {!latchUnavailable ? <EngagedBadge engaged={latchEngaged} /> : null}
        </div>
        <p className="text-sm text-muted-foreground">
          有効にすると、このテナントの新規 AI 活動 (実行作成・エージェント起動・プロバイダー呼び出しなど) が
          すべて拒否され、実行中のエージェントは停止されます。解除するまで持続します。
        </p>

        {latchUnavailable ? (
          <p className="rounded-md bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            緊急停止の状態を読み込めませんでした。再読み込みしてください。
          </p>
        ) : latchEngaged ? (
          <div className="grid gap-3 rounded-md border border-rose-300 dark:border-rose-700 bg-rose-50 dark:bg-rose-950/40 p-3">
            <p className="text-sm text-rose-900 dark:text-rose-200">
              現在 <span className="font-semibold">緊急停止中</span> です
              {generation !== null ? (
                <>
                  {" "}
                  (世代 <span className="font-mono">{generation}</span>
                  {latch?.engagedAt ? (
                    <>
                      、開始 <span className="font-mono">{latch.engagedAt}</span>
                    </>
                  ) : null}
                  )
                </>
              ) : null}
              。
            </p>
            <form action={clearAction} className="grid gap-3" data-testid="emergency-stop-clear-form">
              {/* 世代 CAS: 表示した active latch generation を宣言。別操作で変われば 409。 */}
              <input
                type="hidden"
                name="expected_generation"
                value={generation ?? ""}
              />
              {!clearConfirming ? (
                <div>
                  <button
                    type="button"
                    onClick={() => setClearConfirming(true)}
                    className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink shadow-sm hover:bg-canvas disabled:opacity-60"
                    disabled={anyPending || generation === null}
                  >
                    緊急停止を解除する
                  </button>
                </div>
              ) : (
                <div className="grid gap-3">
                  <p className="text-sm text-rose-900 dark:text-rose-200">
                    緊急停止を解除して AI 活動を再開しますか？停止していた実行は停止前の状態に復元されます。
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="submit"
                      className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent/90 disabled:opacity-60"
                      disabled={anyPending}
                    >
                      {clearPending ? "解除中..." : "解除を確定"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setClearConfirming(false)}
                      className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink hover:bg-canvas"
                      disabled={clearPending}
                    >
                      キャンセル
                    </button>
                  </div>
                </div>
              )}
              <StatusMessage state={clearState} />
            </form>
          </div>
        ) : (
          <form action={engageAction} className="grid gap-3" data-testid="emergency-stop-engage-form">
            <label className="grid gap-2 text-sm">
              <span className="font-medium">停止理由 (任意)</span>
              <input
                name="reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="例: エージェントの暴走を検知"
                maxLength={1000}
                className="rounded-md border border-line bg-panel px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              />
              <span className="text-xs text-muted-foreground">
                理由にシークレット (API キー・トークン等) を含めないでください。検出された場合は拒否されます。
              </span>
            </label>
            {!engageConfirming ? (
              <div>
                <button
                  type="button"
                  onClick={() => setEngageConfirming(true)}
                  className="rounded-md border border-rose-300 dark:border-rose-700 bg-panel px-4 py-2 text-sm font-medium text-rose-700 dark:text-rose-300 shadow-sm hover:bg-rose-50 dark:hover:bg-rose-950/40 disabled:opacity-60"
                  disabled={anyPending}
                >
                  全 AI を緊急停止する
                </button>
              </div>
            ) : (
              <div className="grid gap-3 rounded-md border border-rose-300 dark:border-rose-700 bg-rose-50 dark:bg-rose-950/40 p-3">
                <p className="text-sm text-rose-900 dark:text-rose-200">
                  本当に <span className="font-semibold">全 AI を緊急停止</span> しますか？
                  新規 AI 活動が全面的に拒否され、実行中のエージェントは停止されます。解除するまで持続します。
                </p>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    className="rounded-md bg-rose-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-rose-700 disabled:opacity-60"
                    disabled={anyPending}
                  >
                    {engagePending ? "停止中..." : "緊急停止を確定"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setEngageConfirming(false)}
                    className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink hover:bg-canvas"
                    disabled={engagePending}
                  >
                    キャンセル
                  </button>
                </div>
              </div>
            )}
            <StatusMessage state={engageState} />
          </form>
        )}
      </section>

      {/* budget global kill switch (コスト緊急停止) */}
      <section
        className="grid gap-3 border-t border-line pt-6"
        aria-labelledby="budget-kill-switch"
      >
        <div className="flex items-center gap-3">
          <h3 id="budget-kill-switch" className="text-sm font-semibold text-ink">
            コスト緊急停止 (グローバルキルスイッチ)
          </h3>
          {!budgetUnavailable ? <EngagedBadge engaged={budgetEngaged} /> : null}
        </div>
        <p className="text-sm text-muted-foreground">
          コスト超過時の保険として、予算経路のグローバルキルスイッチを有効化します。緊急停止 (上記) とは別の
          経路ですが、どちらか一方でも有効なら自動承認は拒否されます。
        </p>

        {budgetUnavailable ? (
          <p className="rounded-md bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            コスト緊急停止の状態を読み込めませんでした。再読み込みしてください。
          </p>
        ) : budgetEngaged ? (
          <form
            action={budgetClearAction}
            className="grid gap-3"
            data-testid="budget-kill-switch-clear-form"
          >
            {!budgetClearConfirming ? (
              <div>
                <button
                  type="button"
                  onClick={() => setBudgetClearConfirming(true)}
                  className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink shadow-sm hover:bg-canvas disabled:opacity-60"
                  disabled={anyPending}
                >
                  コスト緊急停止を解除する
                </button>
              </div>
            ) : (
              <div className="flex gap-2">
                <button
                  type="submit"
                  className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent/90 disabled:opacity-60"
                  disabled={anyPending}
                >
                  {budgetClearPending ? "解除中..." : "解除を確定"}
                </button>
                <button
                  type="button"
                  onClick={() => setBudgetClearConfirming(false)}
                  className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink hover:bg-canvas"
                  disabled={budgetClearPending}
                >
                  キャンセル
                </button>
              </div>
            )}
            <StatusMessage state={budgetClearState} />
          </form>
        ) : (
          <form
            action={budgetEngageAction}
            className="grid gap-3"
            data-testid="budget-kill-switch-engage-form"
          >
            {!budgetEngageConfirming ? (
              <div>
                <button
                  type="button"
                  onClick={() => setBudgetEngageConfirming(true)}
                  className="rounded-md border border-rose-300 dark:border-rose-700 bg-panel px-4 py-2 text-sm font-medium text-rose-700 dark:text-rose-300 shadow-sm hover:bg-rose-50 dark:hover:bg-rose-950/40 disabled:opacity-60"
                  disabled={anyPending}
                >
                  コスト緊急停止を有効にする
                </button>
              </div>
            ) : (
              <div className="grid gap-3 rounded-md border border-rose-300 dark:border-rose-700 bg-rose-50 dark:bg-rose-950/40 p-3">
                <p className="text-sm text-rose-900 dark:text-rose-200">
                  コスト緊急停止を有効にしますか？自動承認経路が拒否されます。
                </p>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    className="rounded-md bg-rose-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-rose-700 disabled:opacity-60"
                    disabled={anyPending}
                  >
                    {budgetEngagePending ? "有効化中..." : "有効化を確定"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setBudgetEngageConfirming(false)}
                    className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink hover:bg-canvas"
                    disabled={budgetEngagePending}
                  >
                    キャンセル
                  </button>
                </div>
              </div>
            )}
            <StatusMessage state={budgetEngageState} />
          </form>
        )}
      </section>
    </div>
  );
}
