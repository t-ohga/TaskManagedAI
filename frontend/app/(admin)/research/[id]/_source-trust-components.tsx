"use client";

import { useActionState, useEffect, useRef, useState } from "react";

import { trustTierLabel, trustTierTone } from "@/lib/domain/research-advanced";
import {
  provRelationLabel,
  sourceTrustOriginLabel,
  type EffectiveSourceTrust,
  type ProvenanceView
} from "@/lib/domain/source-trust";
import {
  CITATION_RENDER_MODES,
  citationRenderModeLabel,
  readCitationRenderMode,
  writeCitationRenderMode,
  type CitationRenderMode
} from "@/lib/citation-render-mode";
import { noop, prepareDiscardOnCommit } from "@/lib/full-reload";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";
import { useDraftDiscardRef } from "@/lib/use-draft-discard";

import {
  fetchClaimProvenanceAction,
  setSourceTrustAction,
  type SourceTrustActionState
} from "./source-trust-actions";

const INITIAL: SourceTrustActionState = { kind: "idle" };

const TONE_CLASS: Record<"danger" | "warning" | "success" | "muted", string> = {
  danger: "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300",
  warning: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  success: "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
  muted: "border-line bg-canvas text-muted-foreground"
};

function shortId(value: string): string {
  return value.slice(0, 8);
}

function TrustBadge({ trust }: { readonly trust: EffectiveSourceTrust }) {
  const tone = trust.trust_level ? trustTierTone(trust.trust_level) : "muted";
  const label = trust.trust_level ? `信頼度 ${trustTierLabel(trust.trust_level)}` : "信頼度 未設定";
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${TONE_CLASS[tone]}`}>
      {label} ・ {sourceTrustOriginLabel(trust.origin)}
      {trust.trust_score !== null ? ` (${Math.round(trust.trust_score * 100)}%)` : ""}
    </span>
  );
}

function ManualTrustForm({
  researchTaskId,
  trust,
  onSuccess
}: {
  readonly researchTaskId: string;
  readonly trust: EffectiveSourceTrust;
  readonly onSuccess: () => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  // C-5: 手動信頼度の編集は full reload で失われ得る draft。defaultValue=現在値のため成功時 reset せず
  // (reset すると巻き戻る、F-001)、reload で再構成。source は独立で巻き戻しは source 単位で閉じる。
  const [dirty, setDirty] = useState(false);
  const discardGuardRef = useDraftDiscardRef<HTMLFormElement>(() => setDirty(false), formRef);
  const commitDiscardRef = useRef<() => void>(noop);
  // 自分の dirty だけ wrapper でクリアし保存成功後の reload を自分自身が阻害しないようにする (adversarial finding)。
  const [state, action, pending] = useActionState(
    async (prev: SourceTrustActionState, formData: FormData): Promise<SourceTrustActionState> => {
      const result = await setSourceTrustAction(prev, formData);
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
  const currentLevel = trust.origin === "manual" ? (trust.trust_level ?? "") : "";
  // Codex adversarial R1 MEDIUM (F-003): 既存 manual score を空欄で silently null 化させない。
  // origin=manual の現在値を defaultValue に入れ、未編集なら round-trip させる。
  const currentScore =
    trust.origin === "manual" && trust.trust_score !== null ? String(trust.trust_score) : "";
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
      data-testid="source-trust-form"
      data-unsaved-guard=""
      data-dirty={dirty ? "true" : undefined}
    >
      <input type="hidden" name="research_task_id" value={researchTaskId} />
      <input type="hidden" name="evidence_source_id" value={trust.evidence_source_id} />
      <label className="grid gap-1 text-xs">
        <span className="font-medium">手動信頼度</span>
        <select name="trust_level" defaultValue={currentLevel} disabled={pending} className="rounded-md border border-line bg-panel px-2 py-1 text-sm">
          <option value="">(ドメイン由来 / クリア)</option>
          <option value="low">低</option>
          <option value="medium">中</option>
          <option value="high">高</option>
        </select>
      </label>
      <label className="grid gap-1 text-xs">
        <span className="font-medium">スコア (0-1、任意)</span>
        <input name="trust_score" type="number" min="0" max="1" step="0.01" defaultValue={currentScore} disabled={pending} className="w-24 rounded-md border border-line bg-panel px-2 py-1 text-sm" />
      </label>
      <button type="submit" disabled={pending} className="rounded-md border border-line px-3 py-1 text-sm font-medium hover:bg-canvas disabled:opacity-60">
        {pending ? "保存中..." : "設定"}
      </button>
      {state.kind === "error" ? (
        <span role="status" className="text-xs text-rose-700 dark:text-rose-300">{state.message}</span>
      ) : null}
    </form>
  );
}

function ProvenanceBlock({ view }: { readonly view: ProvenanceView }) {
  if (!view.valid) {
    return (
      <p className="text-xs text-muted-foreground">来歴情報は検証できませんでした (表示しません)。</p>
    );
  }
  return (
    <div className="grid gap-1 text-xs">
      <p className="text-muted-foreground">
        ノード: 活動 {view.activities.length} / 実体 {view.entities.length} / 主体 {view.agents.length}
        {view.truncated ? " (一部省略)" : ""}
      </p>
      <ul className="grid gap-0.5">
        {view.relations.map((rel, i) => (
          <li key={`${rel.relation}-${i}`} className="font-mono text-muted-foreground">
            {provRelationLabel(rel.relation)}: {shortId(rel.from_id)} → {shortId(rel.to_id)}
          </li>
        ))}
      </ul>
    </div>
  );
}

type ProvenanceState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; items: { claimId: string; view: ProvenanceView }[]; capped: boolean }
  | { status: "error" };

export function SourceTrustSection({
  researchTaskId,
  sourceTrust,
  claimIds
}: {
  readonly researchTaskId: string;
  readonly sourceTrust: readonly EffectiveSourceTrust[];
  readonly claimIds: readonly string[];
}) {
  // C-5: action 側 revalidatePath 撤去のため表示更新は client full reload。requestRefresh は安定参照 (F-005)。
  const requestRefresh = useDeferredRouterRefresh();
  const [mode, setMode] = useState<CitationRenderMode>("detailed");
  // adversarial R2 F-001: provenance は mode=provenance のときだけ lazy 取得 (page load 時の全 claim
  // prefetch DoS を防ぐ)。
  const [provenance, setProvenance] = useState<ProvenanceState>({ status: "idle" });
  // localStorage は SSR で読めないため hydration 後に反映 (M-2/P-2 と同型の localStorage-sync-in-effect)。
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMode(readCitationRenderMode());
  }, []);
  useEffect(() => {
    if (mode !== "provenance" || provenance.status !== "idle") return;
    let active = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProvenance({ status: "loading" });
    fetchClaimProvenanceAction(researchTaskId, claimIds)
      .then((result) => {
        if (active) setProvenance({ status: "loaded", items: result.items, capped: result.capped });
      })
      .catch(() => {
        if (active) setProvenance({ status: "error" });
      });
    return () => {
      active = false;
    };
  }, [mode, provenance.status, researchTaskId, claimIds]);
  const changeMode = (next: CitationRenderMode) => {
    writeCitationRenderMode(next);
    setMode(next);
  };

  const tierCounts = sourceTrust.reduce<Record<string, number>>((acc, t) => {
    const key = t.trust_level ?? "unset";
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="引用の表示モード">
        <span className="text-xs font-medium text-muted-foreground">表示モード:</span>
        {CITATION_RENDER_MODES.map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => changeMode(m)}
            aria-pressed={mode === m}
            className={`rounded-md border px-2.5 py-1 text-xs font-medium ${mode === m ? "border-accent bg-accent/10 text-accent" : "border-line text-muted-foreground hover:bg-canvas"}`}
          >
            {citationRenderModeLabel(m)}
          </button>
        ))}
      </div>

      {sourceTrust.length === 0 ? (
        <p className="text-sm text-muted-foreground">証拠ソースがありません。</p>
      ) : mode === "compact" ? (
        <p className="text-sm text-muted-foreground">
          証拠ソース {sourceTrust.length} 件 ・ 高 {tierCounts.high ?? 0} / 中 {tierCounts.medium ?? 0} / 低 {tierCounts.low ?? 0} / 未設定 {tierCounts.unset ?? 0}
        </p>
      ) : (
        <ul className="grid gap-3">
          {sourceTrust.map((trust) => (
            <li key={trust.evidence_source_id} className="grid gap-2 rounded-md border border-line bg-panel p-3">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="font-mono">ソース {shortId(trust.evidence_source_id)}{trust.domain ? ` ・ ${trust.domain}` : ""}</span>
                <TrustBadge trust={trust} />
              </div>
              <ManualTrustForm researchTaskId={researchTaskId} trust={trust} onSuccess={requestRefresh} />
            </li>
          ))}
        </ul>
      )}

      {mode === "provenance" ? (
        <section className="grid gap-2" aria-labelledby="claim-provenance-heading">
          <h3 id="claim-provenance-heading" className="text-sm font-semibold">主張の来歴 (PROV)</h3>
          {provenance.status === "loading" || provenance.status === "idle" ? (
            <p className="text-sm text-muted-foreground" aria-live="polite">来歴を読み込み中...</p>
          ) : provenance.status === "error" ? (
            <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">来歴の読込に失敗しました。</p>
          ) : provenance.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">表示できる来歴がありません。</p>
          ) : (
            <>
              {provenance.capped ? (
                <p className="text-xs text-muted-foreground">先頭 {provenance.items.length} 件のみ表示しています。</p>
              ) : null}
              <ul className="grid gap-2">
                {provenance.items.map(({ claimId, view }) => (
                  <li key={claimId} className="grid gap-1 rounded-md border border-line bg-panel p-3">
                    <span className="font-mono text-xs">主張 {shortId(claimId)}</span>
                    <ProvenanceBlock view={view} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      ) : null}
    </div>
  );
}
