import { cookies } from "next/headers";

import { DEV_SESSION_COOKIE_NAME } from "@/lib/auth/dev-login";

import { healthResponseSchema, type HealthResponse } from "./types";

type Parser<T> = {
  parse(value: unknown): T;
};

export class BackendApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "BackendApiError";
    this.status = status;
  }
}

function readInternalApiUrl(): string {
  const value = process.env.INTERNAL_API_URL ?? process.env.TASKMANAGEDAI_INTERNAL_API_URL;
  if (!value || value.trim().length === 0) {
    throw new Error("INTERNAL_API_URL must be configured.");
  }
  return value;
}

function buildBackendUrl(path: `/${string}`): string {
  return new URL(path, readInternalApiUrl()).toString();
}

export async function fetchBackendJson<T>(
  path: `/${string}`,
  parser: Parser<T>,
  init: RequestInit = {}
): Promise<T> {
  const headers = new Headers(init.headers);
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get(DEV_SESSION_COOKIE_NAME);

  if (sessionCookie) {
    headers.set("cookie", `${DEV_SESSION_COOKIE_NAME}=${sessionCookie.value}`);
  }

  const response = await fetch(buildBackendUrl(path), {
    ...init,
    headers,
    cache: "no-store"
  });

  if (!response.ok) {
    throw new BackendApiError(response.status, `Backend request failed with ${response.status}.`);
  }

  const payload: unknown = await response.json();
  return parser.parse(payload);
}

export async function getBackendHealth(): Promise<HealthResponse> {
  return fetchBackendJson("/healthz", healthResponseSchema);
}


export async function fetchBackendRaw(
  path: `/${string}`,
  init: RequestInit = {}
): Promise<unknown> {
  const headers = new Headers(init.headers);
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get(DEV_SESSION_COOKIE_NAME);

  if (sessionCookie) {
    headers.set("cookie", `${DEV_SESSION_COOKIE_NAME}=${sessionCookie.value}`);
  }

  const response = await fetch(buildBackendUrl(path), {
    ...init,
    headers,
    cache: "no-store"
  });

  if (!response.ok) {
    throw new BackendApiError(response.status, `Backend request failed with ${response.status}.`);
  }

  return response.json();
}

/**
 * 204 No Content を返す mutation (ADR-00044 A-5 tag delete/attach/detach 等) 用 helper。
 * body を読まないため response.json() の "Unexpected end of JSON input" を避ける。
 * 非 2xx は BackendApiError に写像し、呼び出し側が status (404/409 等) を分岐できるようにする。
 */
export async function fetchBackendNoContent(
  path: `/${string}`,
  init: RequestInit = {}
): Promise<void> {
  const headers = new Headers(init.headers);
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get(DEV_SESSION_COOKIE_NAME);

  if (sessionCookie) {
    headers.set("cookie", `${DEV_SESSION_COOKIE_NAME}=${sessionCookie.value}`);
  }

  const response = await fetch(buildBackendUrl(path), {
    ...init,
    headers,
    cache: "no-store"
  });

  if (!response.ok) {
    throw new BackendApiError(response.status, `Backend request failed with ${response.status}.`);
  }
}
