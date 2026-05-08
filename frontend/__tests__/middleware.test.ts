import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { middleware } from "../middleware";
import { DEV_SESSION_COOKIE_NAME } from "../lib/auth/dev-login";

const COOKIE_SECRET = "test-cookie-secret";
const TEXT_ENCODER = new TextEncoder();

type CreateSessionCookieOptions = {
  secret: string;
  now?: Date;
  ttlSeconds?: number;
  actorId?: string;
  principalType?: string;
};

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }

  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

async function hmacSha256(payload: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    TEXT_ENCODER.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, TEXT_ENCODER.encode(payload));
  return base64UrlEncode(new Uint8Array(signature));
}

async function createSignedSessionCookie(options: CreateSessionCookieOptions): Promise<string> {
  const now = options.now ?? new Date();
  const ttlSeconds = options.ttlSeconds ?? 60 * 60 * 12;
  const claims = {
    actor_id: options.actorId ?? "human:default",
    exp: Math.floor(now.getTime() / 1000) + ttlSeconds,
    principal_type: options.principalType ?? "session"
  };
  const payloadSegment = base64UrlEncode(TEXT_ENCODER.encode(JSON.stringify(claims)));
  const signature = await hmacSha256(payloadSegment, options.secret);
  return `${payloadSegment}.${signature}`;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("middleware", () => {
  it("redirects unauthenticated dashboard requests to login with next path", async () => {
    const request = new NextRequest("http://127.0.0.1:3000/dashboard");

    const response = await middleware(request);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://127.0.0.1:3000/login?next=%2Fdashboard"
    );
  });

  it("does not allow unknown protected page routes by default", async () => {
    const request = new NextRequest("http://127.0.0.1:3000/settings");

    const response = await middleware(request);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://127.0.0.1:3000/login?next=%2Fsettings"
    );
  });

  it("returns 401 for unknown protected API routes by default", async () => {
    const request = new NextRequest("http://127.0.0.1:3000/api/private");

    const response = await middleware(request);

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({
      detail: {
        error_code: "unauthenticated",
        error_summary: "Authentication is required."
      }
    });
  });

  it("allows dashboard requests with a valid signed session cookie", async () => {
    vi.stubEnv("DEV_LOGIN_COOKIE_SECRET", COOKIE_SECRET);
    const sessionCookie = await createSignedSessionCookie({
      secret: COOKIE_SECRET,
      now: new Date("2026-05-08T00:00:00.000Z")
    });
    const request = new NextRequest("http://127.0.0.1:3000/dashboard", {
      headers: {
        cookie: `${DEV_SESSION_COOKIE_NAME}=${sessionCookie}`
      }
    });

    const response = await middleware(request);

    expect(response.status).toBe(200);
    expect(response.headers.get("x-taskmanagedai-actor-id")).toBeNull();
    expect(response.headers.get("x-taskmanagedai-principal-type")).toBeNull();
    expect(response.headers.get("x-middleware-request-x-taskmanagedai-actor-id")).toBe(
      "human:default"
    );
    expect(response.headers.get("x-middleware-request-x-taskmanagedai-principal-type")).toBe(
      "session"
    );
  });

  it("preserves existing request headers and cookies when adding actor context", async () => {
    vi.stubEnv("DEV_LOGIN_COOKIE_SECRET", COOKIE_SECRET);
    const sessionCookie = await createSignedSessionCookie({
      secret: COOKIE_SECRET,
      now: new Date("2026-05-08T00:00:00.000Z")
    });
    const request = new NextRequest("http://127.0.0.1:3000/dashboard", {
      headers: {
        cookie: `${DEV_SESSION_COOKIE_NAME}=${sessionCookie}; theme=dark`,
        "x-original-header": "kept"
      }
    });

    const response = await middleware(request);

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-request-x-original-header")).toBe("kept");
    expect(response.headers.get("x-middleware-request-cookie")).toContain(
      `${DEV_SESSION_COOKIE_NAME}=`
    );
    expect(response.headers.get("x-middleware-request-cookie")).toContain("theme=dark");
  });

  it("allows explicit development fallback only outside production", async () => {
    vi.stubEnv("TASKMANAGEDAI_ENVIRONMENT", "test");
    vi.stubEnv("TASKMANAGEDAI_ALLOW_DEV_ACTOR_FALLBACK", "true");
    const request = new NextRequest("http://127.0.0.1:3000/dashboard");

    const response = await middleware(request);

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-request-x-taskmanagedai-actor-id")).toBe(
      "human:default"
    );
    expect(response.headers.get("x-middleware-request-x-taskmanagedai-principal-type")).toBe(
      "session"
    );
  });

  it("denies fallback in production even when the fallback flag is true", async () => {
    vi.stubEnv("TASKMANAGEDAI_ENVIRONMENT", "production");
    vi.stubEnv("TASKMANAGEDAI_ALLOW_DEV_ACTOR_FALLBACK", "true");
    const request = new NextRequest("http://127.0.0.1:3000/dashboard");

    const response = await middleware(request);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://127.0.0.1:3000/login?next=%2Fdashboard"
    );
  });

  it("redirects and clears an invalid session cookie", async () => {
    vi.stubEnv("DEV_LOGIN_COOKIE_SECRET", COOKIE_SECRET);
    const sessionCookie = await createSignedSessionCookie({
      secret: COOKIE_SECRET,
      now: new Date("2026-05-08T00:00:00.000Z")
    });
    const request = new NextRequest("http://127.0.0.1:3000/dashboard", {
      headers: {
        cookie: `${DEV_SESSION_COOKIE_NAME}=${sessionCookie}tampered`
      }
    });

    const response = await middleware(request);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://127.0.0.1:3000/login?next=%2Fdashboard"
    );
    expect(response.cookies.get(DEV_SESSION_COOKIE_NAME)?.value).toBe("");
  });
});
