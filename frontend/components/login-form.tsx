"use client";

import { useFormStatus } from "react-dom";

type LoginFormProps = {
  action: (formData: FormData) => void | Promise<void>;
  error: string | null;
  nextPath: string;
};

function SubmitButton() {
  const { pending } = useFormStatus();

  return (
    <button
      className="mt-5 w-full rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white outline-offset-2 hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:bg-slate-400"
      disabled={pending}
      type="submit"
    >
      {pending ? "確認中..." : "ログイン"}
    </button>
  );
}

export function LoginForm({ action, error, nextPath }: LoginFormProps) {
  return (
    <form action={action} className="grid gap-4">
      {error ? (
        <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}

      <input name="next" type="hidden" value={nextPath} />

      <div className="grid gap-2">
        <label className="text-sm font-medium text-ink" htmlFor="dev-login-token">
          Dev login token
        </label>
        <input
          autoComplete="current-password"
          className="h-11 rounded-md border border-line bg-white px-3 text-base text-ink outline-offset-2 placeholder:text-slate-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          id="dev-login-token"
          maxLength={4096}
          name="token"
          required
          type="password"
        />
      </div>

      <SubmitButton />
    </form>
  );
}
