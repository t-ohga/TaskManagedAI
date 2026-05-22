import { LoginForm } from "@/components/login-form";

import { devLoginAction } from "./actions";

type LoginPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function errorMessage(code: string | undefined): string | null {
  if (code === "invalid-token") {
    return "Dev login token が不正です。";
  }
  if (code === "invalid-request") {
    return "ログインリクエストが不正です。";
  }
  return null;
}

function safeNextPath(value: string | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return "/dashboard";
  }
  return value;
}

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = searchParams ? await searchParams : {};
  const error = errorMessage(firstParam(params.error));
  const nextPath = safeNextPath(firstParam(params.next));

  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <section className="w-full max-w-md rounded-lg border border-line bg-panel p-6 shadow-sm">
        <div className="mb-6">
          <p className="text-sm font-medium text-accent">TaskManagedAI</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-normal">Dev ログイン</h1>
        </div>
        <LoginForm action={devLoginAction} error={error} nextPath={nextPath} />
      </section>
    </main>
  );
}
