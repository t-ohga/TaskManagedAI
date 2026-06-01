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
    // パレットを開いた瞬間に前回の検索語をクリアし入力欄へ focus する。open への遷移は
    // 複数箇所 (⌘K / 各 setOpen) から起き、query state は閉じても保持されるため、開いた
    // タイミングで集約的にリセットするこの setState-in-effect は意図的。
    if (open) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
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
      {/* a11y: 背景クリックで閉じる overlay を semantic な button にする
          (jsx-a11y/click-events-have-key-events + no-static-element-interactions)。
          keyboard では Escape でも閉じられる (上部 keydown handler)。tabIndex={-1} で tab 順序からは外す。 */}
      <button
        type="button"
        aria-label="コマンドパレットを閉じる"
        tabIndex={-1}
        className="fixed inset-0 bg-black/40"
        onClick={() => setOpen(false)}
      />
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
          {filtered.length === 0 ? <li className="px-4 py-3 text-center text-xs text-muted-foreground">
              一致するページがありません
            </li> : null}
        </ul>
      </div>
    </div>
  );
}
