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

