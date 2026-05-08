"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { z } from "zod";

import { DEV_SESSION_COOKIE_NAME } from "@/lib/auth/dev-login";

const loginSchema = z.object({
  token: z.string().trim().min(1).max(4096),
  next: z.string().trim().optional()
});

type BackendDevLoginResponse = {
  status: "ok";
  actor_id: "human:default";
  principal_type: "session";
};

type ParsedBackendCookie = {
  name: string;
  value: string;
  path: string;
  expires?: Date;
  maxAge?: number;
  httpOnly: boolean;
  secure: boolean;
  sameSite: "lax" | "strict" | "none";
};

function stringFromFormData(formData: FormData, key: string): string | undefined {
  const value = formData.get(key);
  return typeof value === "string" ? value : undefined;
}

function safeRedirectPath(value: string | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return "/dashboard";
  }
  return value;
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

function isBackendDevLoginResponse(value: unknown): value is BackendDevLoginResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "status" in value &&
    "actor_id" in value &&
    "principal_type" in value &&
    value.status === "ok" &&
    value.actor_id === "human:default" &&
    value.principal_type === "session"
  );
}

function getSetCookieHeaders(headers: Headers): string[] {
  const headersWithSetCookie = headers as Headers & { getSetCookie?: () => string[] };
  if (typeof headersWithSetCookie.getSetCookie === "function") {
    return headersWithSetCookie.getSetCookie();
  }

  const setCookie = headers.get("set-cookie");
  return setCookie ? [setCookie] : [];
}

function parseSameSite(value: string): ParsedBackendCookie["sameSite"] | null {
  const normalized = value.toLowerCase();
  if (normalized === "lax" || normalized === "strict" || normalized === "none") {
    return normalized;
  }
  return null;
}

function parseBackendSetCookie(header: string): ParsedBackendCookie | null {
  const [nameValue, ...attributeParts] = header.split(";").map((part) => part.trim());
  if (!nameValue) {
    return null;
  }

  const separatorIndex = nameValue.indexOf("=");
  if (separatorIndex <= 0) {
    return null;
  }

  const name = nameValue.slice(0, separatorIndex);
  const value = nameValue.slice(separatorIndex + 1);
  const parsedCookie: ParsedBackendCookie = {
    name,
    value,
    path: "/",
    httpOnly: false,
    secure: false,
    sameSite: "lax"
  };

  for (const attribute of attributeParts) {
    const [rawAttributeName, ...rawAttributeValueParts] = attribute.split("=");
    if (!rawAttributeName) {
      continue;
    }

    const attributeName = rawAttributeName.toLowerCase();
    const attributeValue = rawAttributeValueParts.join("=");

    if (attributeName === "httponly") {
      parsedCookie.httpOnly = true;
    } else if (attributeName === "secure") {
      parsedCookie.secure = true;
    } else if (attributeName === "path" && attributeValue.length > 0) {
      parsedCookie.path = attributeValue;
    } else if (attributeName === "max-age") {
      const maxAge = Number.parseInt(attributeValue, 10);
      if (Number.isInteger(maxAge)) {
        parsedCookie.maxAge = maxAge;
      }
    } else if (attributeName === "expires") {
      const expires = new Date(attributeValue);
      if (!Number.isNaN(expires.getTime())) {
        parsedCookie.expires = expires;
      }
    } else if (attributeName === "samesite") {
      const sameSite = parseSameSite(attributeValue);
      if (sameSite) {
        parsedCookie.sameSite = sameSite;
      }
    }
  }

  return parsedCookie;
}

function readBackendSessionCookie(response: Response): ParsedBackendCookie | null {
  for (const setCookieHeader of getSetCookieHeaders(response.headers)) {
    const parsedCookie = parseBackendSetCookie(setCookieHeader);
    if (parsedCookie?.name === DEV_SESSION_COOKIE_NAME) {
      return parsedCookie;
    }
  }

  return null;
}

async function proxyDevLogin(token: string): Promise<Response> {
  return fetch(buildBackendUrl("/auth/dev-login"), {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({ token }),
    cache: "no-store"
  });
}

export async function devLoginAction(formData: FormData): Promise<void> {
  const parsed = loginSchema.safeParse({
    token: stringFromFormData(formData, "token"),
    next: stringFromFormData(formData, "next")
  });

  if (!parsed.success) {
    redirect("/login?error=invalid-request");
  }

  let backendResponse: Response;
  try {
    backendResponse = await proxyDevLogin(parsed.data.token);
  } catch {
    redirect("/login?error=invalid-request");
  }

  if (backendResponse.status === 401) {
    redirect("/login?error=invalid-token");
  }

  if (!backendResponse.ok) {
    redirect("/login?error=invalid-request");
  }

  let responsePayload: unknown;
  try {
    responsePayload = await backendResponse.json();
  } catch {
    redirect("/login?error=invalid-request");
  }

  if (!isBackendDevLoginResponse(responsePayload)) {
    redirect("/login?error=invalid-request");
  }

  const sessionCookie = readBackendSessionCookie(backendResponse);
  if (!sessionCookie) {
    redirect("/login?error=invalid-request");
  }

  const cookieStore = await cookies();
  cookieStore.set({
    name: sessionCookie.name,
    value: sessionCookie.value,
    httpOnly: sessionCookie.httpOnly,
    secure: sessionCookie.secure,
    sameSite: sessionCookie.sameSite,
    path: sessionCookie.path,
    ...(sessionCookie.expires ? { expires: sessionCookie.expires } : {}),
    ...(sessionCookie.maxAge !== undefined ? { maxAge: sessionCookie.maxAge } : {})
  });

  redirect(safeRedirectPath(parsed.data.next));
}

