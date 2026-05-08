import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { devLoginAction } from "../app/(auth)/login/actions";
import { LoginForm } from "../components/login-form";
import { DEV_SESSION_COOKIE_NAME } from "../lib/auth/dev-login";

const cookieMocks = vi.hoisted(() => ({
  set: vi.fn()
}));

const navigationMocks = vi.hoisted(() => ({
  redirect: vi.fn((path: string): never => {
    throw new Error(`NEXT_REDIRECT:${path}`);
  })
}));

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    set: cookieMocks.set
  }))
}));

vi.mock("next/navigation", () => ({
  redirect: navigationMocks.redirect
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  cookieMocks.set.mockReset();
  navigationMocks.redirect.mockClear();
});

describe("LoginForm", () => {
  it("submits the token through the backend dev login proxy and copies Set-Cookie", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");

    const user = userEvent.setup();
    const expires = new Date("Fri, 08 May 2026 12:00:00 GMT");
    const backendSetCookie = [
      `${DEV_SESSION_COOKIE_NAME}=backend-session-value`,
      "Path=/",
      "Max-Age=43200",
      "Expires=Fri, 08 May 2026 12:00:00 GMT",
      "HttpOnly",
      "Secure",
      "SameSite=Lax"
    ].join("; ");

    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          status: "ok",
          actor_id: "human:default",
          principal_type: "session"
        }),
        {
          status: 200,
          headers: {
            "content-type": "application/json",
            "set-cookie": backendSetCookie
          }
        }
      )
    );

    const action = vi.fn(async (formData: FormData): Promise<void> => {
      await expect(devLoginAction(formData)).rejects.toThrow("NEXT_REDIRECT:/dashboard");
    });

    render(<LoginForm action={action} error={null} nextPath="/dashboard" />);

    await user.type(screen.getByLabelText("Dev login token"), "correct-dev-login-token");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(cookieMocks.set).toHaveBeenCalledTimes(1);
    });

    expect(action).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("http://backend.test/auth/dev-login", {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({ token: "correct-dev-login-token" }),
      cache: "no-store"
    });
    expect(cookieMocks.set).toHaveBeenCalledWith({
      name: DEV_SESSION_COOKIE_NAME,
      value: "backend-session-value",
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/",
      expires,
      maxAge: 43200
    });
    expect(navigationMocks.redirect).toHaveBeenCalledWith("/dashboard");
  });

  it("renders invalid token feedback as an alert", () => {
    render(
      <LoginForm
        action={() => undefined}
        error="Dev login token is invalid."
        nextPath="/dashboard"
      />
    );

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe("Dev login token is invalid.");
    expect(screen.getByLabelText("Dev login token").getAttribute("name")).toBe("token");
  });
});

