import { getFrontendHealth } from "@/lib/health";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return Response.json(getFrontendHealth(), {
    status: 200,
    headers: {
      "cache-control": "no-store"
    }
  });
}

