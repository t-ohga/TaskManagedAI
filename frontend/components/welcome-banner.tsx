"use client";

import { useState } from "react";

export function WelcomeBanner() {
  const [dismissed, setDismissed] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("taskmanagedai_welcome_dismissed") === "true";
  });

  if (dismissed) return null;

  function dismiss() {
    localStorage.setItem("taskmanagedai_welcome_dismissed", "true");
    setDismissed(true);
  }

  return (
    <div className="rounded-lg border border-accent/30 bg-accent/5 p-5">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-accent">TaskManagedAI へようこそ</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            AI-native な開発タスク管理ツールです。チケットの作成、AI 実行の管理、承認ワークフローを統合的に扱えます。
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <a href="/tickets" className="rounded-md bg-accent px-3 py-1.5 font-medium text-white hover:bg-accent/90">
              チケットを見る
            </a>
            <a href="/runs" className="rounded-md border border-line px-3 py-1.5 font-medium text-muted-foreground hover:bg-slate-50">
              AI 実行を確認
            </a>
          </div>
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="text-muted-foreground hover:text-ink"
          aria-label="バナーを閉じる"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
