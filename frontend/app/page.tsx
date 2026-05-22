import Link from "next/link";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-5xl flex-col px-6 py-8">
      <header className="flex items-center justify-between border-b border-line pb-5">
        <p className="text-lg font-semibold tracking-normal">TaskManagedAI</p>
        <nav aria-label="主要ナビゲーション">
          <ul className="flex items-center gap-2 text-sm">
            <li>
              <Link
                className="rounded-md px-3 py-2 text-muted outline-offset-2 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                href="/login"
              >
                ログイン
              </Link>
            </li>
            <li>
              <Link
                className="rounded-md bg-accent px-3 py-2 font-medium text-white outline-offset-2 hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                href="/dashboard"
              >
                ダッシュボード
              </Link>
            </li>
          </ul>
        </nav>
      </header>

      <section className="grid flex-1 content-center gap-6 py-12">
        <div className="max-w-2xl">
          <p className="mb-3 text-sm font-medium text-accent">Sprint 1 管理 shell</p>
          <h1 className="text-4xl font-semibold tracking-normal sm:text-5xl">
            TaskManagedAI
          </h1>
          <p className="mt-4 max-w-xl text-base leading-7 text-muted">
            Deep Research から実装 PR までの証拠、判断、承認、実行ログを管理する
            AI-native な開発タスク管理基盤です。
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link
            className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white outline-offset-2 hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            href="/dashboard"
          >
            ダッシュボードを開く
          </Link>
          <Link
            className="rounded-md border border-line px-4 py-2 text-sm font-semibold text-ink outline-offset-2 hover:border-accent hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            href="/api/healthz"
          >
            ヘルスチェック
          </Link>
        </div>
      </section>
    </main>
  );
}
