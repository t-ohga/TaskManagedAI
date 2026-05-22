import Link from "next/link";

export default function NotFound() {
  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <section className="w-full max-w-md rounded-lg border border-line bg-panel p-6 shadow-sm">
        <p className="text-sm font-medium text-accent">404</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-normal">ページが見つかりません</h1>
        <p className="mt-3 text-sm leading-6 text-muted">
          指定されたページは存在しないか、移動された可能性があります。
        </p>
        <Link
          className="mt-5 inline-flex rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white outline-offset-2 hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          href="/dashboard"
        >
          ダッシュボードへ戻る
        </Link>
      </section>
    </main>
  );
}
