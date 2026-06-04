"use client";

import Link from "next/link";
import type { Route } from "next";
import { useCallback, useEffect, useState } from "react";

import { TicketStatusIndicator } from "@/components/ticket-status-indicator";
import { BulkStatusChanger } from "@/components/bulk-status-changer";
import { TagChip } from "@/components/tag-chip";
import { assigneeLabel } from "@/lib/api/actors";
import type { TagRead } from "@/lib/domain/tag";
import { isValidYmd, ticketDueBucket, type DueDateBucket } from "@/lib/domain/due-date";

type TicketRow = {
  id: string;
  title: string;
  status: string;
  priority: string | null;
  projectSlug: string;
  // A-7 (ADR-00045 R4 F-001): 期限強調を active project のみに限定するための project 状態。
  projectActive: boolean;
  due_date: string | null;
  created_at: string | null;
  // A-6 (ADR-00046): 担当者 actor id (UUID or null)。display_name は assigneeNameById で解決。
  assignee_actor_id: string | null;
  tags: TagRead[];
};

type SelectableTicketListProps = {
  tickets: TicketRow[];
  showProjectBadge: boolean;
  // A-7 (ADR-00045): backend authority な基準日 + reminder window (date_context 由来)。
  // 取得失敗時は undefined → 期限強調なし (neutral) に倒す (fail-closed、誤分類しない)。
  referenceDate?: string | undefined;
  thresholdDays?: number | undefined;
  // A-6 (ADR-00046): assignee UUID -> display_name 解決 map (取得失敗時は空 map → 中立 fallback)。
  assigneeNameById?: Map<string, string | null> | undefined;
};

// due_date は SQL date (YYYY-MM-DD) のプレーンな暦日。timezone を持たないため
// new Date(...) を介さず文字列から直接整形し、JST 変換による日付ずれを防ぐ。
// 非実在日 / 不正形式は raw を echo せず null (R7 F-001: schema が strict だが defense-in-depth、
// bogus deadline を表示しない)。
function formatDueDate(value: string | null): string | null {
  if (!value || !isValidYmd(value)) return null;
  const [year, month, day] = value.split("-");
  return `${year}/${Number(month)}/${Number(day)}`;
}

// A-7: 期限 chip の色 (overdue=赤 / due_today・upcoming=橙 / future・基準日なし=neutral)。
function dueChipClass(bucket: DueDateBucket | null): string {
  switch (bucket) {
    case "overdue":
      return "bg-red-50 font-medium text-red-700";
    case "due_today":
    case "upcoming":
      return "bg-amber-50 font-medium text-amber-700";
    default:
      return "bg-slate-50 text-muted-foreground";
  }
}

// 色だけに依存しない (a11y): overdue / due_today は接頭ラベルでも区別する。
function dueChipLabel(bucket: DueDateBucket | null, formatted: string): string {
  if (bucket === "overdue") return `超過 ${formatted}`;
  if (bucket === "due_today") return `本日 ${formatted}`;
  return formatted;
}

const PRIORITY_LABELS: Record<string, { label: string; color: string }> = {
  critical: { label: "最優先", color: "bg-red-100 text-red-700" },
  high: { label: "高", color: "bg-orange-100 text-orange-700" },
  medium: { label: "中", color: "bg-yellow-100 text-yellow-700" },
  low: { label: "低", color: "bg-blue-100 text-blue-700" },
};

export function SelectableTicketList({
  tickets,
  showProjectBadge,
  referenceDate,
  thresholdDays,
  assigneeNameById,
}: SelectableTicketListProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  // 横断表示 (project=all) では updateTicketAction が単一プロジェクトしか
  // 解決できないため一括操作を無効化 (Codex R1 P2)
  const bulkEnabled = !showProjectBadge;

  const toggle = useCallback((id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }, []);

  const toggleAll = useCallback(() => {
    // 全 visible チケットが選択済なら解除、そうでなければ全 visible を選択 (stale ID 非依存)。
    setSelectedIds((prev) =>
      tickets.length > 0 && tickets.every((t) => prev.includes(t.id)) ? [] : tickets.map((t) => t.id)
    );
  }, [tickets]);

  const clear = useCallback(() => setSelectedIds([]), []);

  // tickets が変わったら canonical な selectedIds から隠れた ID を prune する。これは
  // cleanup であり、「隠れ選択が state に残り、後で再表示されたとき自動的に再選択されて
  // mutation 境界に再侵入する」ことを防ぐ (Codex adversarial review)。mutation 境界の
  // 即時 race (effect 実行前の最初の render) は下の visibleSelectedIds (derive-during-render)
  // が担い、本 effect と併用して first-render race と re-entry の両方を閉じる。
  useEffect(() => {
    const visible = new Set(tickets.map((t) => t.id));
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelectedIds((prev) => {
      const pruned = prev.filter((id) => visible.has(id));
      return pruned.length === prev.length ? prev : pruned;
    });
  }, [tickets]);

  // 列: title / status / priority / [project] / 期限 / 担当者 / 作成日 (+ checkbox)。
  const colSpan = (showProjectBadge ? 7 : 6) + (bulkEnabled ? 1 : 0);

  // フィルタ / プロジェクト切替で tickets が変わったとき、隠れたチケット ID が mutation 境界
  // (BulkStatusChanger → updateTicketAction) へ渡らないよう、表示中チケットに含まれる選択 ID
  // だけを render 時に純粋導出する。effect での後追い prune だと、prune 前の最初の render で
  // stale ID が BulkStatusChanger へ渡り、隠れたチケットを一括更新できる race が起きるため
  // (Codex adversarial review HIGH / 元 Codex R1 P2)、derive-during-render で境界を閉じる。
  const visibleIdSet = new Set(tickets.map((t) => t.id));
  const visibleSelectedIds = selectedIds.filter((id) => visibleIdSet.has(id));
  // checked は boolean prop なので JSX 内の && を避け、ここで boolean を確定する。
  const allSelected = tickets.length > 0 && visibleSelectedIds.length === tickets.length;

  return (
    <div className="grid gap-3">
      {bulkEnabled ? <BulkStatusChanger
          selectedIds={visibleSelectedIds}
          onClear={clear}
          onSelectionChange={setSelectedIds}
        /> : null}
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-sm">
          <thead className="bg-canvas text-left text-xs font-medium text-muted-foreground">
            <tr>
              {bulkEnabled ? <th className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    aria-label="すべて選択"
                  />
                </th> : null}
              <th className="px-4 py-3">タイトル</th>
              <th className="px-4 py-3">ステータス</th>
              <th className="px-4 py-3">優先度</th>
              {showProjectBadge ? <th className="px-4 py-3">プロジェクト</th> : null}
              <th className="px-4 py-3">期限</th>
              <th className="px-4 py-3">担当者</th>
              <th className="px-4 py-3">作成日</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {tickets.map((ticket) => {
              const pri = ticket.priority ? PRIORITY_LABELS[ticket.priority] : null;
              return (
                <tr key={ticket.id} className={selectedIds.includes(ticket.id) ? "bg-accent/5" : "hover:bg-slate-50"}>
                  {bulkEnabled ? <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(ticket.id)}
                        onChange={() => toggle(ticket.id)}
                        aria-label={`${ticket.title} を選択`}
                      />
                    </td> : null}
                  <td className="px-4 py-3">
                    <Link href={`/tickets/${ticket.id}` as Route} className="font-medium text-accent hover:underline">
                      {ticket.title}
                    </Link>
                    {ticket.tags.length > 0 ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {ticket.tags.map((tag) => (
                          <TagChip key={tag.id} name={tag.name} color={tag.color} />
                        ))}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-4 py-3"><TicketStatusIndicator status={ticket.status} /></td>
                  <td className="px-4 py-3">
                    {pri ? <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${pri.color}`}>{pri.label}</span> : null}
                  </td>
                  {showProjectBadge ? <td className="px-4 py-3 text-xs text-muted-foreground">{ticket.projectSlug}</td> : null}
                  <td className="px-4 py-3 text-xs">
                    {(() => {
                      const formatted = formatDueDate(ticket.due_date);
                      if (!formatted || !ticket.due_date) {
                        return <span className="text-muted-foreground">—</span>;
                      }
                      // status + 期限から強調 bucket を導出。非 actionable (closed/cancelled) /
                      // 基準日不明 (date_context 失敗) は bucket=null → neutral (R2 F-002 / R3 F-001、
                      // backend reminders の actionable 集合と揃え画面間不整合・誤分類を防ぐ)。
                      const bucket = ticketDueBucket(
                        ticket.due_date,
                        ticket.status,
                        ticket.projectActive,
                        referenceDate,
                        thresholdDays
                      );
                      return (
                        <span className={`rounded px-1.5 py-0.5 ${dueChipClass(bucket)}`}>
                          {dueChipLabel(bucket, formatted)}
                        </span>
                      );
                    })()}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {/* A-6: assignee は display_name で表示 (UUID 生表示はしない)。未割当は淡色。 */}
                    {ticket.assignee_actor_id ? (
                      <span className="text-foreground">
                        {assigneeLabel(assigneeNameById ?? new Map(), ticket.assignee_actor_id)}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">未割当</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    {ticket.created_at ? new Date(ticket.created_at).toLocaleDateString("ja-JP", { timeZone: "Asia/Tokyo" }) : ""}
                  </td>
                </tr>
              );
            })}
            {tickets.length === 0 ? <tr>
                <td colSpan={colSpan} className="px-4 py-8 text-center text-muted-foreground">
                  チケットがありません
                </td>
              </tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
