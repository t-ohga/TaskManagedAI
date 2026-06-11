"use client";

import { useActionState, useEffect, useRef, useState, type RefObject } from "react";

import {
  conflictStatusLabel,
  conflictStatusTone,
  formatFreshness,
  matchTypeLabel,
  trustTierLabel,
  trustTierTone,
  type ConflictCandidate,
  type ConflictGroup,
  type EvidenceDomainTrust,
  type ResearchAdvancedSummary
} from "@/lib/domain/research-advanced";
import { noop, prepareDiscardOnCommit } from "@/lib/full-reload";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";
import { useDraftDiscardRef } from "@/lib/use-draft-discard";

import {
  assignClaimAction,
  createConflictGroupAction,
  setConflictGroupStatusAction,
  unassignClaimAction,
  type ConflictActionState
} from "./conflict-actions";

const INITIAL: ConflictActionState = { kind: "idle" };

const STATUS_TONE: Record<"warning" | "success" | "muted", string> = {
  warning: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  success:
    "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
  muted: "border-line bg-canvas text-muted-foreground"
};

const TRUST_TONE: Record<"danger" | "warning" | "success", string> = {
  danger: "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300",
  warning: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  success: "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
};

function shortId(value: string): string {
  return value.slice(0, 8);
}

function StatusMessage({ state }: { readonly state: ConflictActionState }) {
  if (state.kind === "error") {
    return (
      <p role="status" className="rounded-md bg-rose-50 dark:bg-rose-950/40 px-3 py-1.5 text-xs text-rose-700 dark:text-rose-300">
        {state.message}
      </p>
    );
  }
  if (state.kind === "ok") {
    return (
      <p role="status" className="rounded-md bg-emerald-50 dark:bg-emerald-950/40 px-3 py-1.5 text-xs text-emerald-700 dark:text-emerald-300">
        {state.message}
      </p>
    );
  }
  return null;
}

function StatusBadge({ status }: { readonly status: ConflictGroup["status"] }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_TONE[conflictStatusTone(status)]}`}>
      {conflictStatusLabel(status)}
    </span>
  );
}

function CreateGroupForm({ researchTaskId, onSuccess }: { readonly researchTaskId: string; readonly onSuccess: () => void }) {
  const formRef = useRef<HTMLFormElement>(null);
  // C-5: full reload で失われ得る入力 (グループ名) を draft guard に登録。
  const [dirty, setDirty] = useState(false);
  const discardGuardRef = useDraftDiscardRef<HTMLFormElement>(() => setDirty(false), formRef);
  const commitDiscardRef = useRef<() => void>(noop);
  // 成功時の入力クリアは action wrapper 内で行う (effect 内 setState を避ける、comment-form と同 pattern)。
  const [state, action, pending] = useActionState(
    async (prev: ConflictActionState, formData: FormData): Promise<ConflictActionState> => {
      const result = await createConflictGroupAction(prev, formData);
      if (result.kind === "ok") {
        formRef.current?.reset();
        setDirty(false);
      }
      return result;
    },
    INITIAL
  );
  useEffect(() => {
    if (state.kind === "ok") {
      commitDiscardRef.current();
      commitDiscardRef.current = noop;
      onSuccess();
    }
  }, [state, onSuccess]);
  return (
    <form
      ref={discardGuardRef}
      action={action}
      onChange={() => setDirty(true)}
      onSubmit={(event) => {
        const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
        if (!approved) {
          event.preventDefault();
          return;
        }
        commitDiscardRef.current = commit;
      }}
      className="flex flex-wrap items-end gap-2 rounded-md border border-line bg-canvas p-3"
      data-testid="conflict-group-create-form"
      data-unsaved-guard=""
      data-dirty={dirty ? "true" : undefined}
    >
      <input type="hidden" name="research_task_id" value={researchTaskId} />
      <label className="grid gap-1 text-xs flex-1 min-w-48">
        <span className="font-medium">新しい矛盾グループ</span>
        <input
          name="title"
          required
          maxLength={200}
          placeholder="例: 公開時期に関する矛盾"
          disabled={pending}
          className="rounded-md border border-line bg-panel px-2 py-1 text-sm"
        />
      </label>
      <button
        type="submit"
        disabled={pending}
        className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-60"
      >
        {pending ? "作成中..." : "グループ作成"}
      </button>
      <StatusMessage state={state} />
    </form>
  );
}

function GroupStatusForm({ researchTaskId, group, onSuccess }: { readonly researchTaskId: string; readonly group: ConflictGroup; readonly onSuccess: () => void }) {
  const formRef = useRef<HTMLFormElement>(null);
  // C-5: 編集中の状態 / 解決メモは full reload で失われ得る draft。group は独立のため巻き戻しは group 単位で閉じる。
  const [dirty, setDirty] = useState(false);
  const discardGuardRef = useDraftDiscardRef<HTMLFormElement>(() => setDirty(false), formRef);
  const commitDiscardRef = useRef<() => void>(noop);
  // 編集 form は成功時 reset しない (defaultValue=group prop で巻き戻る、F-001)。自分の dirty だけ wrapper で
  // クリアし保存成功後の reload を自分自身が阻害しないようにする (adversarial finding)。
  const [state, action, pending] = useActionState(
    async (prev: ConflictActionState, formData: FormData): Promise<ConflictActionState> => {
      const result = await setConflictGroupStatusAction(prev, formData);
      if (result.kind === "ok") setDirty(false);
      return result;
    },
    INITIAL
  );
  useEffect(() => {
    if (state.kind === "ok") {
      commitDiscardRef.current();
      commitDiscardRef.current = noop;
      onSuccess();
    }
  }, [state, onSuccess]);
  return (
    <form
      ref={discardGuardRef}
      action={action}
      onChange={() => setDirty(true)}
      onSubmit={(event) => {
        const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
        if (!approved) {
          event.preventDefault();
          return;
        }
        commitDiscardRef.current = commit;
      }}
      className="flex flex-wrap items-end gap-2"
      data-testid="conflict-group-status-form"
      data-unsaved-guard=""
      data-dirty={dirty ? "true" : undefined}
    >
      <input type="hidden" name="research_task_id" value={researchTaskId} />
      <input type="hidden" name="group_id" value={group.id} />
      <label className="grid gap-1 text-xs">
        <span className="font-medium">状態</span>
        <select name="status" defaultValue={group.status} disabled={pending} className="rounded-md border border-line bg-panel px-2 py-1 text-sm">
          <option value="open">未解決</option>
          <option value="resolved">解決済み</option>
          <option value="dismissed">却下</option>
        </select>
      </label>
      <label className="grid gap-1 text-xs flex-1 min-w-40">
        <span className="font-medium">解決メモ (解決済みは必須)</span>
        <input name="resolution_note" defaultValue={group.resolution_note ?? ""} maxLength={2000} disabled={pending} className="rounded-md border border-line bg-panel px-2 py-1 text-sm" />
      </label>
      <button type="submit" disabled={pending} className="rounded-md border border-line px-3 py-1.5 text-sm font-medium hover:bg-canvas disabled:opacity-60">
        {pending ? "更新中..." : "更新"}
      </button>
      <StatusMessage state={state} />
    </form>
  );
}

function CandidateRow({
  researchTaskId,
  candidate,
  groups,
  onSuccess
}: {
  readonly researchTaskId: string;
  readonly candidate: ConflictCandidate;
  readonly groups: readonly ConflictGroup[];
  readonly onSuccess: () => void;
}) {
  const assignFormRef = useRef<HTMLFormElement>(null);
  // C-5: 割当先選択は full reload で失われ得る draft (assign form のみ、unassign は hidden)。
  const [assignDirty, setAssignDirty] = useState(false);
  const assignDiscardRef = useDraftDiscardRef<HTMLFormElement>(() => setAssignDirty(false), assignFormRef);
  const assignCommitRef = useRef<() => void>(noop);
  const unassignCommitRef = useRef<() => void>(noop);
  // adversarial R3: 副作用は any-ok effect ではなく各 action wrapper で action-scoped に実行する。
  const finish = (ref: RefObject<() => void>) => {
    ref.current();
    ref.current = noop;
    onSuccess();
  };
  // assign form は成功時 reset しない (defaultValue=firstAssignable で巻き戻る、F-001)。自分の dirty だけ
  // wrapper でクリアし保存成功後の reload を自分自身が阻害しないようにする (adversarial finding)。
  const [assignState, assignAction, assignPending] = useActionState(
    async (prev: ConflictActionState, formData: FormData): Promise<ConflictActionState> => {
      const result = await assignClaimAction(prev, formData);
      if (result.kind === "ok") {
        setAssignDirty(false);
        finish(assignCommitRef);
      }
      return result;
    },
    INITIAL
  );
  const [unassignState, unassignAction, unassignPending] = useActionState(
    async (prev: ConflictActionState, formData: FormData): Promise<ConflictActionState> => {
      const result = await unassignClaimAction(prev, formData);
      if (result.kind === "ok") finish(unassignCommitRef);
      return result;
    },
    INITIAL
  );

  // adversarial R4: 並行 submit を防ぐため、いずれかの mutation が pending 中は両 form を block。
  const anyPending = assignPending || unassignPending;
  const assignableGroups = groups.filter((g) => g.status !== "dismissed");
  const firstAssignable = assignableGroups[0];

  return (
    <li className="grid gap-2 rounded-md border border-line bg-panel p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="font-mono">主張 {shortId(candidate.claim_id)}</span>
        <span className="text-xs text-muted-foreground">
          反証 {candidate.contradicting_count} / 支持 {candidate.supporting_count} / 文脈 {candidate.context_count}
        </span>
      </div>
      {candidate.conflict_group_id ? (
        <form
          action={unassignAction}
          onSubmit={(event) => {
            const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
            if (!approved) {
              event.preventDefault();
              return;
            }
            unassignCommitRef.current = commit;
          }}
          className="flex items-center gap-2"
          data-testid="conflict-candidate-unassign-form"
        >
          <input type="hidden" name="research_task_id" value={researchTaskId} />
          <input type="hidden" name="group_id" value={candidate.conflict_group_id} />
          <input type="hidden" name="claim_id" value={candidate.claim_id} />
          <span className="text-xs text-muted-foreground">
            グループ {shortId(candidate.conflict_group_id)} に割当済み
          </span>
          <button type="submit" disabled={anyPending} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-canvas disabled:opacity-60">
            {unassignPending ? "解除中..." : "解除"}
          </button>
          <StatusMessage state={unassignState} />
        </form>
      ) : firstAssignable ? (
        <form
          ref={assignDiscardRef}
          action={assignAction}
          onChange={() => setAssignDirty(true)}
          onSubmit={(event) => {
            const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
            if (!approved) {
              event.preventDefault();
              return;
            }
            assignCommitRef.current = commit;
          }}
          className="flex flex-wrap items-center gap-2"
          data-testid="conflict-candidate-assign-form"
          data-unsaved-guard=""
          data-dirty={assignDirty ? "true" : undefined}
        >
          <input type="hidden" name="research_task_id" value={researchTaskId} />
          <input type="hidden" name="claim_id" value={candidate.claim_id} />
          <select name="group_id" defaultValue={firstAssignable.id} disabled={anyPending} className="rounded-md border border-line bg-canvas px-2 py-1 text-xs">
            {assignableGroups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.title}
              </option>
            ))}
          </select>
          <button type="submit" disabled={anyPending} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-canvas disabled:opacity-60">
            {assignPending ? "割当中..." : "グループに割当"}
          </button>
          <StatusMessage state={assignState} />
        </form>
      ) : (
        <span className="text-xs text-muted-foreground">割当先グループがありません (先にグループを作成してください)。</span>
      )}
    </li>
  );
}

function DomainTrustBadge({ trust }: { readonly trust: EvidenceDomainTrust }) {
  if (trust.match_type === "exact" && trust.trust_tier) {
    return (
      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${TRUST_TONE[trustTierTone(trust.trust_tier)]}`}>
        {trust.domain} — 信頼度 {trustTierLabel(trust.trust_tier)}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full border border-line bg-canvas px-2 py-0.5 text-xs font-medium text-muted-foreground">
      {trust.domain ?? "ドメイン不明"} — {matchTypeLabel(trust.match_type)}
    </span>
  );
}

export function ResearchAdvancedSection({
  researchTaskId,
  summary
}: {
  readonly researchTaskId: string;
  readonly summary: ResearchAdvancedSummary;
}) {
  // C-5: action 側 revalidatePath 撤去のため、表示更新は client full reload。
  // requestRefresh は安定参照のため onSuccess に直接渡せる (effect 再発火による reload ループを防ぐ、F-005)。
  const requestRefresh = useDeferredRouterRefresh();

  const coveragePct = Math.round(Math.max(0, Math.min(1, summary.relation_coverage)) * 100);
  const freshnessByClaim = new Map(summary.claim_freshness.map((f) => [f.claim_id, f]));

  return (
    <div className="grid gap-5">
      <p className="text-sm text-muted-foreground">
        矛盾候補 {summary.conflict_candidates.length} 件 / 証拠付与率 {coveragePct}%。
        {summary.relation_coverage === 0
          ? " 証拠の関連付け (relation) が未整備のため、争点を検出できません。"
          : ""}
      </p>

      <section className="grid gap-3" aria-labelledby="conflict-groups-heading">
        <h3 id="conflict-groups-heading" className="text-sm font-semibold">
          矛盾グループ
        </h3>
        <CreateGroupForm researchTaskId={researchTaskId} onSuccess={requestRefresh} />
        {summary.conflict_groups.length === 0 ? (
          <p className="text-sm text-muted-foreground">矛盾グループはまだありません。</p>
        ) : (
          <ul className="grid gap-3">
            {summary.conflict_groups.map((group) => (
              <li key={group.id} className="grid gap-2 rounded-md border border-line bg-panel p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium">{group.title}</span>
                  <StatusBadge status={group.status} />
                </div>
                {group.resolution_note ? (
                  <p className="text-xs text-muted-foreground">解決メモ: {group.resolution_note}</p>
                ) : null}
                <GroupStatusForm researchTaskId={researchTaskId} group={group} onSuccess={requestRefresh} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="grid gap-3" aria-labelledby="conflict-candidates-heading">
        <h3 id="conflict-candidates-heading" className="text-sm font-semibold">
          矛盾候補 (反証を持つ主張)
        </h3>
        {summary.conflict_candidates.length === 0 ? (
          <p className="text-sm text-muted-foreground">反証を持つ主張はありません。</p>
        ) : (
          <ul className="grid gap-2">
            {summary.conflict_candidates.map((candidate) => (
              <CandidateRow
                key={candidate.claim_id}
                researchTaskId={researchTaskId}
                candidate={candidate}
                groups={summary.conflict_groups}
                onSuccess={requestRefresh}
              />
            ))}
          </ul>
        )}
      </section>

      <section className="grid gap-3" aria-labelledby="claim-freshness-heading">
        <h3 id="claim-freshness-heading" className="text-sm font-semibold">
          主張の鮮度 (証拠の公開日からの推定)
        </h3>
        {summary.claim_freshness.length === 0 ? (
          <p className="text-sm text-muted-foreground">主張がありません。</p>
        ) : (
          <ul className="grid gap-1 text-sm">
            {summary.claim_freshness.map((fresh) => (
              <li key={fresh.claim_id} className="flex items-center justify-between gap-2 rounded-md border border-line bg-panel px-3 py-1.5">
                <span className="font-mono text-xs">主張 {shortId(fresh.claim_id)}</span>
                <span className="text-xs text-muted-foreground">
                  鮮度 {formatFreshness(freshnessByClaim.get(fresh.claim_id)?.computed_freshness ?? null)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="grid gap-3" aria-labelledby="evidence-domain-trust-heading">
        <h3 id="evidence-domain-trust-heading" className="text-sm font-semibold">
          証拠ドメインの信頼度
        </h3>
        {summary.evidence_domain_trust.length === 0 ? (
          <p className="text-sm text-muted-foreground">証拠ソースがありません。</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {summary.evidence_domain_trust.map((trust) => (
              <li key={trust.evidence_source_id}>
                <DomainTrustBadge trust={trust} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
