import type { Actor, DevSession, Principal, SessionClaims } from "./types";

export const DEV_SESSION_COOKIE_NAME = "taskmanagedai_session";

const TEXT_ENCODER = new TextEncoder();
const TEXT_DECODER = new TextDecoder();

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }

  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

function base64UrlDecode(value: string): Uint8Array | null {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");

  try {
    const binary = atob(padded);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
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

function constantTimeEqual(left: string, right: string): boolean {
  const maxLength = Math.max(left.length, right.length);
  let diff = left.length ^ right.length;

  for (let index = 0; index < maxLength; index += 1) {
    const leftCode = index < left.length ? left.charCodeAt(index) : 0;
    const rightCode = index < right.length ? right.charCodeAt(index) : 0;
    diff |= leftCode ^ rightCode;
  }

  return diff === 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseClaims(payload: unknown): SessionClaims | null {
  if (!isRecord(payload)) {
    return null;
  }

  if (
    payload.actor_id !== "human:default" ||
    payload.principal_type !== "session" ||
    typeof payload.exp !== "number" ||
    !Number.isInteger(payload.exp)
  ) {
    return null;
  }

  // ADR-00043 (R-2): iat は optional。present かつ整数のときだけ採用、無効/欠如は undefined。
  // iat 欠如/不正で session を invalid にしない (表示専用、有効性は exp のみ)。
  const iat =
    typeof payload.iat === "number" && Number.isInteger(payload.iat)
      ? payload.iat
      : undefined;

  return {
    actor_id: payload.actor_id,
    principal_type: payload.principal_type,
    exp: payload.exp,
    ...(iat !== undefined ? { iat } : {})
  };
}

function sessionFromClaims(claims: SessionClaims): DevSession {
  const actor: Actor = {
    actorId: claims.actor_id,
    actorType: "human",
    displayName: "Default human actor"
  };
  const principal: Principal = {
    principalType: claims.principal_type,
    principalId: "session"
  };

  return {
    actor,
    principal,
    expiresAt: new Date(claims.exp * 1000),
    // ADR-00043 (R-2): iat (login 時刻)。iat 無 cookie は null。
    issuedAt: claims.iat !== undefined ? new Date(claims.iat * 1000) : null,
    claims
  };
}

function readRequiredEnv(names: readonly string[]): string {
  for (const name of names) {
    const value = process.env[name];
    if (value && value.trim().length > 0 && !value.includes("REPLACE_ME")) {
      return value;
    }
  }

  throw new Error(`${names.join(" or ")} must be configured.`);
}

function isDevelopmentOrTestEnvironment(value: string | undefined): boolean {
  return value === "development" || value === "test";
}

export function readDevLoginCookieSecret(): string {
  return readRequiredEnv(["DEV_LOGIN_COOKIE_SECRET", "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET"]);
}

export function isFallbackAllowed(): boolean {
  const environment = process.env.TASKMANAGEDAI_ENVIRONMENT ?? process.env.NODE_ENV;
  return (
    isDevelopmentOrTestEnvironment(environment) &&
    process.env.TASKMANAGEDAI_ALLOW_DEV_ACTOR_FALLBACK === "true"
  );
}

export function isDevActorFallbackEnabled(): boolean {
  return isFallbackAllowed();
}

export async function verifyDevSessionCookie(
  value: string,
  secret: string,
  now: Date = new Date()
): Promise<DevSession | null> {
  const [payloadSegment, signatureSegment, extraSegment] = value.split(".");
  if (!payloadSegment || !signatureSegment || extraSegment !== undefined) {
    return null;
  }

  const expectedSignature = await hmacSha256(payloadSegment, secret);
  if (!constantTimeEqual(signatureSegment, expectedSignature)) {
    return null;
  }

  const payloadBytes = base64UrlDecode(payloadSegment);
  if (!payloadBytes) {
    return null;
  }

  let parsedPayload: unknown;
  try {
    parsedPayload = JSON.parse(TEXT_DECODER.decode(payloadBytes));
  } catch {
    return null;
  }

  const claims = parseClaims(parsedPayload);
  if (!claims || claims.exp <= Math.floor(now.getTime() / 1000)) {
    return null;
  }

  return sessionFromClaims(claims);
}
