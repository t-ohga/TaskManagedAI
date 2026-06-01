"use client";

import Link from "next/link";
import type { Route } from "next";
import { useEffect, useState } from "react";

type RecentTicket = { id: string; title: string; slug: string };

const STORAGE_KEY = "taskmanagedai_recent_tickets";
const MAX_ITEMS = 5;

export function useTrackRecentTicket(ticket: { id: string; title: string; slug: string } | null) {
  useEffect(() => {
    if (!ticket || typeof window === "undefined") return;
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]") as RecentTicket[];
      const filtered = stored.filter((t) => t.id !== ticket.id);
      filtered.unshift({ id: ticket.id, title: ticket.title, slug: ticket.slug });
      localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered.slice(0, MAX_ITEMS)));
    } catch { /* ignore */ }
  }, [ticket]);
}

// F-4 (UI 監査 fix): ticket 詳細で閲覧を記録する thin Client Component (render なし)。
// これが無いと useTrackRecentTicket の consumer が 0 で RecentTicketsList が常時空になる。
export function TrackRecentTicket({
  ticket,
}: {
  ticket: { id: string; title: string; slug: string };
}) {
  useTrackRecentTicket(ticket);
  return null;
}

export function RecentTicketsList() {
  const [tickets, setTickets] = useState<RecentTicket[]>([]);

  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]") as RecentTicket[];
      setTickets(stored.slice(0, MAX_ITEMS));
    } catch { /* ignore */ }
  }, []);

  if (tickets.length === 0) return null;

  return (
    <div className="grid gap-1">
      <p className="text-xs font-medium text-muted-foreground">最近のチケット</p>
      {tickets.map((t) => (
        <Link key={t.id} href={`/tickets/${t.id}` as Route} className="text-xs text-accent hover:underline truncate">
          {t.title}
        </Link>
      ))}
    </div>
  );
}
