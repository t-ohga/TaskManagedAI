import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://backend:8000";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get("taskmanagedai_session");

  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (sessionCookie) {
      headers["Cookie"] = `taskmanagedai_session=${sessionCookie.value}`;
    }

    const res = await fetch(`${BACKEND_URL}/api/v1/agent_runs/${id}/cancel`, {
      method: "POST",
      headers,
      body: JSON.stringify({ reason: null }),
    });

    if (!res.ok) {
      const body = await res.text();
      return NextResponse.json(
        { error: "Backend error", detail: body },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(
      { error: "Failed to cancel run" },
      { status: 502 }
    );
  }
}
