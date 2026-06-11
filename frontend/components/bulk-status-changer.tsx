"use client";

import { useRef, useState, useTransition } from "react";
import { prepareDiscardOnCommit } from "@/lib/full-reload";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";

import { useToast } from "@/components/toast";

type BulkStatusChangerProps = {
  selectedIds: string[];
  onClear: () => void;
  onSelectionChange?: (ids: string[]) => void;
};

const STATUSES = [
  { value: "open", label: "未着手" },
  { value: "in_progress", label: "進行中" },
  { value: "closed", label: "完了" },
  { value: "cancelled", label: "中止" },
];

export function BulkStatusChanger({ selectedIds, onClear, onSelectionChange }: BulkStatusChangerProps) {
  const requestRefresh = useDeferredRouterRefresh();
  const { toast } = useToast();
  const [isPending, startTransition] = useTransition();
  const [targetStatus, setTargetStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  // adversarial R6: 同期 in-flight lock。isPending は次 render まで false で同 tick の二重 click を
  // 許すため、startTransition の二重起動 (二重 mutation バッチ) を ref で防ぐ。
  const inFlightRef = useRef(false);

  if (selectedIds.length === 0) return null;

  function handleApply() {
    // adversarial R6: 同期 in-flight lock で同 tick の二重 click を弾く (isPending は次 render まで
    // false で startTransition を二重起動でき、二重 mutation バッチ + 二重 reload race になる)。
    if (!targetStatus || inFlightRef.current) return;
    // R2 (Codex adversarial HIGH): 未保存編集の破棄確認は mutation **前**。キャンセルなら
    // server action を実行しない (post-commit 確認だと stale form 保存で commit を巻き戻せる)。
    // R11: 確認のみ pre-commit、破棄は **全件成功時にのみ** commit (部分失敗時は draft 無傷)。
    const { approved, commit } = prepareDiscardOnCommit();
    if (!approved) return;
    setError(null);
    inFlightRef.current = true;
    startTransition(async () => {
      try {
        const { updateTicketAction } = await import("@/app/(admin)/tickets/[id]/actions");
        const failedIds: string[] = [];
        for (const id of selectedIds) {
          try {
            const fd = new FormData();
            fd.set("ticket_id", id);
            fd.set("status", targetStatus);
            const result = await updateTicketAction({ kind: "idle" }, fd);
            if (result.kind === "error") failedIds.push(id);
          } catch {
            failedIds.push(id);
          }
        }
        if (failedIds.length > 0) {
          const succeeded = selectedIds.length - failedIds.length;
          setError(`${failedIds.length} 件の更新に失敗しました (権限またはプロジェクト境界を確認してください)`);
          toast(
            `${failedIds.length} 件の更新に失敗${succeeded > 0 ? ` (${succeeded} 件成功)` : ""}`,
            "error"
          );
          setSelectedIdsFromParent(failedIds);
          // 部分失敗時は再試行を許すため lock を解放 (draft も commit せず無傷)。
          inFlightRef.current = false;
        } else {
          toast(`${selectedIds.length} 件のステータスを更新しました`, "success");
          onClear();
          commit();
          // C-5 / F-2 (Codex adversarial): reload は**全件成功時のみ**。部分失敗時に reload すると
          // エラー表示と failedIds の再選択 (復旧導線) が消えるため、失敗時は現状表示を維持する。
          requestRefresh();
          // R7 (Codex adversarial HIGH): 成功時も lock を解放する。bulk bar は onClear で
          // selectedIds 空 → return null となり submit 経路が消えるため、in-flight 窓は既に終了。
          // reload が別 draft の破棄確認でキャンセルされても、その後の**再選択は新しい操作**であり
          // lock が居残ると操作不能 (dead button) になる。次の選択で正しく実行できるよう reset する。
          inFlightRef.current = false;
        }
      } catch (error) {
        // 動的 import 失敗等の例外時は lock を解放して再試行を許す (draft は commit 未実行で無傷)。
        setError(error instanceof Error ? error.message : "一括更新に失敗しました");
        inFlightRef.current = false;
      }
    });
  }

  function setSelectedIdsFromParent(ids: string[]) {
    onSelectionChange?.(ids);
  }

  return (
    <div className="grid gap-2 rounded-md border border-accent/30 bg-accent/5 px-4 py-2">
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium">{selectedIds.length} 件選択中</span>
        <select
          value={targetStatus}
          onChange={(e) => setTargetStatus(e.target.value)}
          className="rounded-md border border-line px-2 py-1 text-sm"
          aria-label="一括変更先ステータス"
        >
          <option value="">ステータスを選択</option>
          {STATUSES.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={handleApply}
          disabled={!targetStatus || isPending}
          className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
        >
          {isPending ? "処理中..." : "一括変更"}
        </button>
        <button
          type="button"
          onClick={onClear}
          className="text-sm text-muted-foreground hover:text-ink"
        >
          選択解除
        </button>
      </div>
      {error ? <p className="text-xs text-danger" role="alert">{error}</p> : null}
    </div>
  );
}
