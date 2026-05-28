"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";

const PAGES = [
  { label: "ダッシュボード", href: "/dashboard" },
  { label: "Today", href: "/today" },
  { label: "チケット", href: "/tickets" },
  { label: "AI 実行", href: "/runs" },
  { label: "承認待ち", href: "/approvals" },
  { label: "監査ログ", href: "/audit" },
  { label: "評価ダッシュボード", href: "/eval-dashboard" },
  { label: "AI 組織", href: "/orchestrator/board" },
  { label: "設定", href: "/settings" },
  { label: "通知", href: "/notifications" },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      inputRef.current?.focus();
    }
  }, [open]);

  const filtered = PAGES.filter((p) =>
    p.label.toLowerCase().includes(query.toLowerCase())
  );

  const navigate = useCallback(
    (href: string) => {
      setOpen(false);
      router.push(href as Route);
    },
    [router]
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]">
      <div className="fixed inset-0 bg-black/40" onClick={() => setOpen(false)} />
      <div className="relative z-10 w-full max-w-md rounded-lg border border-line bg-panel shadow-2xl">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="ページを検索... (Esc で閉じる)"
          className="w-full rounded-t-lg border-b border-line bg-transparent px-4 py-3 text-sm outline-none"
          aria-label="コマンドパレット検索"
        />
        <ul className="max-h-64 overflow-y-auto py-2">
          {filtered.map((p) => (
            <li key={p.href}>
              <button
                type="button"
                onClick={() => navigate(p.href)}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-slate-50"
              >
                <span className="text-muted-foreground">/</span>
                <span>{p.label}</span>
              </button>
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="px-4 py-3 text-center text-xs text-muted-foreground">
              一致するページがありません
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
