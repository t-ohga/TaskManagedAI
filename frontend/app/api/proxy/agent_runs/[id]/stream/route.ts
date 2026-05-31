import { cookies } from "next/headers";

// ADR-00038 (L-3 SSE realtime): browser → Next.js → backend の SSE proxy。
// browser は backend (Docker internal) に直接到達できないため、same-origin の本 route が
// session cookie を転送しつつ backend の SSE stream を pass-through する。
// request.signal を backend fetch に渡し、client 切断を backend まで伝播 (R3 cleanup chain)。
//
// upstream は **fetchBackendRaw と同じ server-only internal API URL** (INTERNAL_API_URL) を使う
// (code-review #1: NEXT_PUBLIC_BACKEND_URL fallback だと docker-compose の api:8000 と不整合で 502)。

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function readInternalApiUrl(): string {
  const value = process.env.INTERNAL_API_URL ?? process.env.TASKMANAGEDAI_INTERNAL_API_URL;
  if (!value || value.trim().length === 0) {
    throw new Error("INTERNAL_API_URL must be configured.");
  }
  return value;
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const requestUrl = new URL(request.url);
  // resume cursor は server 側で int validation される。client が付与した値をそのまま転送。
  const lastEventId = requestUrl.searchParams.get("last_event_id") ?? "0";

  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get("taskmanagedai_session");
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (sessionCookie) {
    headers["Cookie"] = `taskmanagedai_session=${sessionCookie.value}`;
  }

  let backendUrl: string;
  try {
    backendUrl = new URL(
      `/api/v1/agent_runs/${id}/events/stream?last_event_id=${encodeURIComponent(lastEventId)}`,
      readInternalApiUrl()
    ).toString();
  } catch {
    return new Response(null, { status: 500 }); // INTERNAL_API_URL 未設定 (deploy misconfig)
  }

  let backendRes: Response;
  try {
    backendRes = await fetch(backendUrl, {
      headers,
      signal: request.signal,
      cache: "no-store",
    });
  } catch {
    return new Response(null, { status: 502 });
  }

  // 204 (flag-off) / 404 / 422 / 503 等は status のみ pass-through (client 側が分岐)。
  if (backendRes.status !== 200 || backendRes.body === null) {
    return new Response(null, { status: backendRes.status });
  }

  // 200 + body は SSE stream を buffer せず pass-through。
  return new Response(backendRes.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
      Connection: "keep-alive",
    },
  });
}
