"use client";

// S-1 チケット印刷ビュー: ブラウザの印刷ダイアログを開く。印刷 CSS (globals.css @media print)
// がナビ / 操作系を隠し内容のみを出すため、本ボタン自体も .no-print で印刷対象から除外する。
export function PrintButton({ label = "印刷" }: { label?: string }) {
  return (
    <button
      type="button"
      onClick={() => window.print()}
      className="no-print rounded-md border border-line px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-slate-50"
    >
      {label}
    </button>
  );
}
