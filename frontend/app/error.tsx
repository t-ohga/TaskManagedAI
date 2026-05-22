"use client";

type AppErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function AppError({ error, reset }: AppErrorProps) {
  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <section className="w-full max-w-md rounded-lg border border-line bg-panel p-6 shadow-sm">
        <p className="text-sm font-medium text-danger">エラー</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-normal">
          画面の表示に失敗しました
        </h1>
        <p className="mt-3 text-sm leading-6 text-muted">
          しばらくしてから再試行してください。問題が続く場合は audit log と実行ログを確認してください。
        </p>
        {error.digest ? (
          <p className="mt-3 font-mono text-xs text-muted">digest: {error.digest}</p>
        ) : null}
        <button
          className="mt-5 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white outline-offset-2 hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          onClick={reset}
          type="button"
        >
          再試行
        </button>
      </section>
    </main>
  );
}
