"use client";

export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="max-w-md rounded-lg border border-line bg-panel p-6 text-center shadow-sm">
        <h2 className="text-lg font-semibold text-danger">エラーが発生しました</h2>
        <p className="mt-2 text-sm text-muted-foreground">{error.message}</p>
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
