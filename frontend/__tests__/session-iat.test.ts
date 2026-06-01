import { describe, expect, it } from "vitest";

import { verifyDevSessionCookie } from "../lib/auth/dev-login";

// ADR-00043 (R-2): dev session cookie の iat (最終ログイン日時) frontend round-trip。
// iat present → session.issuedAt が set。iat 無/不正 → issuedAt=null かつ session 有効 (後方互換)。

const COOKIE_SECRET = "test-session-secret-for-iat-frontend";
const TEXT_ENCODER = new TextEncoder();

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

async function hmac(payload: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    TEXT_ENCODER.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, TEXT_ENCODER.encode(payload));
  return base64UrlEncode(new Uint8Array(sig));
}

async function signCookie(claims: Record<string, unknown>): Promise<string> {
  const segment = base64UrlEncode(TEXT_ENCODER.encode(JSON.stringify(claims)));
  return `${segment}.${await hmac(segment, COOKIE_SECRET)}`;
}

function futureExp(): number {
  // wall-clock now を基準に十分未来の exp。
  return Math.floor(Date.now() / 1000) + 60 * 60;
}

describe("verifyDevSessionCookie iat (ADR-00043 R-2)", () => {
  it("exposes issuedAt when the cookie has a valid iat", async () => {
    const iat = Math.floor(Date.now() / 1000) - 120;
    const cookie = await signCookie({
      actor_id: "human:default",
      principal_type: "session",
      exp: futureExp(),
      iat,
    });
    const session = await verifyDevSessionCookie(cookie, COOKIE_SECRET);
    expect(session).not.toBeNull();
    expect(session?.issuedAt).toBeInstanceOf(Date);
    expect(session?.issuedAt?.getTime()).toBe(iat * 1000);
    expect(session?.claims.iat).toBe(iat);
  });

  it("is backward compatible: legacy cookie without iat is valid with issuedAt=null", async () => {
    const cookie = await signCookie({
      actor_id: "human:default",
      principal_type: "session",
      exp: futureExp(),
    });
    const session = await verifyDevSessionCookie(cookie, COOKIE_SECRET);
    expect(session).not.toBeNull();
    expect(session?.issuedAt).toBeNull();
    expect(session?.claims.iat).toBeUndefined();
  });

  it("ignores a non-integer iat (issuedAt=null) without invalidating the session", async () => {
    const cookie = await signCookie({
      actor_id: "human:default",
      principal_type: "session",
      exp: futureExp(),
      iat: "not-a-number",
    });
    const session = await verifyDevSessionCookie(cookie, COOKIE_SECRET);
    // iat 不正でも session は有効 (exp のみで判定)、issuedAt は null。
    expect(session).not.toBeNull();
    expect(session?.issuedAt).toBeNull();
  });
});
