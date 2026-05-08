import { NextResponse, type NextRequest } from "next/server";

import {
  DEV_SESSION_COOKIE_NAME,
  isFallbackAllowed,
  readDevLoginCookieSecret,
  verifyDevSessionCookie
} from "@/lib/auth/dev-login";
import type { DevSession } from "@/lib/auth/types";

const ACTOR_HEADER = "x-taskmanagedai-actor-id";
const PRINCIPAL_HEADER = "x-taskmanagedai-principal-type";
const PUBLIC_PATHS = new Set(["/login", "/api/healthz"]);

type SessionLookup = {
  session: DevSession | null;
  hadSessionCookie: boolean;
};

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.has(pathname);
}

function isApiPath(pathname: string): boolean {
  return pathname === "/api" || pathname.startsWith("/api/");
}

function redirectToLogin(request: NextRequest): NextResponse {
  const loginUrl = new URL("/login", request.url);
  const nextPath = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  loginUrl.searchParams.set("next", nextPath);
  return NextResponse.redirect(loginUrl);
}

function clearSessionCookie(response: NextResponse): NextResponse {
  response.cookies.delete(DEV_SESSION_COOKIE_NAME);
  return response;
}

function unauthenticatedResponse(request: NextRequest, clearCookie: boolean): NextResponse {
  const response = isApiPath(request.nextUrl.pathname)
    ? NextResponse.json(
        {
          detail: {
            error_code: "unauthenticated",
            error_summary: "Authentication is required."
          }
        },
        { status: 401 }
      )
    : redirectToLogin(request);

  return clearCookie ? clearSessionCookie(response) : response;
}

async function sessionFromRequest(request: NextRequest): Promise<SessionLookup> {
  const cookie = request.cookies.get(DEV_SESSION_COOKIE_NAME);

  if (!cookie) {
    return { session: null, hadSessionCookie: false };
  }

  try {
    return {
      session: await verifyDevSessionCookie(cookie.value, readDevLoginCookieSecret()),
      hadSessionCookie: true
    };
  } catch {
    return { session: null, hadSessionCookie: true };
  }
}

function responseWithActor(
  request: NextRequest,
  actorId: string,
  principalType: string
): NextResponse {
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(ACTOR_HEADER, actorId);
  requestHeaders.set(PRINCIPAL_HEADER, principalType);

  return NextResponse.next({
    request: {
      headers: requestHeaders
    }
  });
}

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const pathname = request.nextUrl.pathname;
  const { session, hadSessionCookie } = await sessionFromRequest(request);

  if (pathname === "/login") {
    if (session) {
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }

    const response = NextResponse.next();
    return hadSessionCookie ? clearSessionCookie(response) : response;
  }

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  if (session) {
    return responseWithActor(request, session.actor.actorId, session.principal.principalType);
  }

  if (hadSessionCookie) {
    return unauthenticatedResponse(request, true);
  }

  if (isFallbackAllowed()) {
    return responseWithActor(request, "human:default", "session");
  }

  return unauthenticatedResponse(request, false);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|robots.txt).*)"]
};
