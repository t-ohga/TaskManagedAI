"use client";

import { useEffect } from "react";

// O-4 (UI 監査 fix): raw な error.message (技術的文字列) をそのまま表示せず、人間可読な
// メッセージに mapping する。詳細は console に残す (デバッグ用)。
function humanizeError(error: Error): string {
  const message = error.message ?? "";
  if (/failed with 401|unauthor/i.test(message)) {
    return "認証の有効期限が切れている可能性があります。再ログインしてください。";
  }
  if (/failed with 403|forbidden|権限/i.test(message)) {
    return "この操作を行う権限がありません。";
  }
  if (/failed with 404|not found/i.test(message)) {
    return "対象のデータが見つかりませんでした。削除された可能性があります。";
  }
  if (/failed with 5\d\d|fetch failed|network|econn|timeout/i.test(message)) {
    return "サーバーに接続できませんでした。時間をおいて再試行してください。";
  }
  return "予期しないエラーが発生しました。再試行しても解決しない場合は管理者に連絡してください。";
}

export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // 技術的詳細は console に残す (画面には人間可読メッセージのみ表示)。
    console.error("AdminError:", error.message, error.digest ?? "");
  }, [error]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="max-w-md rounded-lg border border-line bg-panel p-6 text-center shadow-sm">
        <h2 className="text-lg font-semibold text-danger">エラーが発生しました</h2>
        <p className="mt-2 text-sm text-muted-foreground">{humanizeError(error)}</p>
        <button
          className="mt-4 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90"
          onClick={reset}
          type="button"
        >
          再試行
        </button>
      </div>
    </div>
  );
}
