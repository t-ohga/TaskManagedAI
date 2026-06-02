"use client";

import Link from "next/link";
import type { Route } from "next";
import { useCallback, useEffect, useState } from "react";

import { TicketStatusIndicator } from "@/components/ticket-status-indicator";
import { BulkStatusChanger } from "@/components/bulk-status-changer";
import { TagChip } from "@/components/tag-chip";
import type { TagRead } from "@/lib/api/tags";

type TicketRow = {
  id: string;
  title: string;
  status: string;
  priority: string | null;
  projectSlug: string;
  due_date: string | null;
  created_at: string | null;
  tags: TagRead[];
};

type SelectableTicketListProps = {
  tickets: TicketRow[];
  showProjectBadge: boolean;
};

// due_date は SQL date (YYYY-MM-DD) のプレーンな暦日。timezone を持たないため
// new Date(...) を介さず文字列から直接整形し、JST 変換による日付ずれを防ぐ。
function formatDueDate(value: string | null): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const [, year, month, day] = match;
  return `${year}/${Number(month)}/${Number(day)}`;
}

const PRIORITY_LABELS: Record<string, { label: string; color: string }> = {
  critical: { label: "最優先", color: "bg-red-100 text-red-700" },
  high: { label: "高", color: "bg-orange-100 text-orange-700" },
  medium: { label: "中", color: "bg-yellow-100 text-yellow-700" },
  low: { label: "低", color: "bg-blue-100 text-blue-700" },
};

export function SelectableTicketList({ tickets, showProjectBadge }: SelectableTicketListProps) {
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

  const colSpan = (showProjectBadge ? 6 : 5) + (bulkEnabled ? 1 : 0);

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
                    {formatDueDate(ticket.due_date) ? (
                      <span className="rounded bg-amber-50 px-1.5 py-0.5 font-medium text-amber-700">
                        {formatDueDate(ticket.due_date)}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
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
