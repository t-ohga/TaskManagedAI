"use client";

import Link from "next/link";
import type { Route } from "next";
import { useCallback, useEffect, useState } from "react";

import { TicketStatusIndicator } from "@/components/ticket-status-indicator";
import { BulkStatusChanger } from "@/components/bulk-status-changer";

type TicketRow = {
  id: string;
  title: string;
  status: string;
  priority: string | null;
  projectSlug: string;
  created_at: string | null;
};

type SelectableTicketListProps = {
  tickets: TicketRow[];
  showProjectBadge: boolean;
};

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

  // フィルタ / プロジェクト切替で表示チケットが変わったら、現在の一覧に
  // 含まれない選択 ID を除去 (隠れたチケットの一括更新を防止、Codex R1 P2)
  useEffect(() => {
    const visibleIds = new Set(tickets.map((t) => t.id));
    setSelectedIds((prev) => prev.filter((id) => visibleIds.has(id)));
  }, [tickets]);

  const toggle = useCallback((id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }, []);

  const toggleAll = useCallback(() => {
    setSelectedIds((prev) => (prev.length === tickets.length ? [] : tickets.map((t) => t.id)));
  }, [tickets]);

  const clear = useCallback(() => setSelectedIds([]), []);

  const colSpan = (showProjectBadge ? 5 : 4) + (bulkEnabled ? 1 : 0);

  return (
    <div className="grid gap-3">
      {bulkEnabled && (
        <BulkStatusChanger
          selectedIds={selectedIds}
          onClear={clear}
          onSelectionChange={setSelectedIds}
        />
      )}
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-sm">
          <thead className="bg-canvas text-left text-xs font-medium text-muted-foreground">
            <tr>
              {bulkEnabled && (
                <th className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={tickets.length > 0 && selectedIds.length === tickets.length}
                    onChange={toggleAll}
                    aria-label="すべて選択"
                  />
                </th>
              )}
              <th className="px-4 py-3">タイトル</th>
              <th className="px-4 py-3">ステータス</th>
              <th className="px-4 py-3">優先度</th>
              {showProjectBadge && <th className="px-4 py-3">プロジェクト</th>}
              <th className="px-4 py-3">作成日</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {tickets.map((ticket) => {
              const pri = ticket.priority ? PRIORITY_LABELS[ticket.priority] : null;
              return (
                <tr key={ticket.id} className={selectedIds.includes(ticket.id) ? "bg-accent/5" : "hover:bg-slate-50"}>
                  {bulkEnabled && (
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(ticket.id)}
                        onChange={() => toggle(ticket.id)}
                        aria-label={`${ticket.title} を選択`}
                      />
                    </td>
                  )}
                  <td className="px-4 py-3">
                    <Link href={`/tickets/${ticket.id}` as Route} className="font-medium text-accent hover:underline">
                      {ticket.title}
                    </Link>
                  </td>
                  <td className="px-4 py-3"><TicketStatusIndicator status={ticket.status} /></td>
                  <td className="px-4 py-3">
                    {pri && (
                      <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${pri.color}`}>{pri.label}</span>
                    )}
                  </td>
                  {showProjectBadge && (
                    <td className="px-4 py-3 text-xs text-muted-foreground">{ticket.projectSlug}</td>
                  )}
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    {ticket.created_at ? new Date(ticket.created_at).toLocaleDateString("ja-JP", { timeZone: "Asia/Tokyo" }) : ""}
                  </td>
                </tr>
              );
            })}
            {tickets.length === 0 && (
              <tr>
                <td colSpan={colSpan} className="px-4 py-8 text-center text-muted-foreground">
                  チケットがありません
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
