export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return Response.json(
    {
      status: "ok",
      service: "frontend"
    },
    {
      status: 200,
      headers: {
        "cache-control": "no-store"
      }
    }
  );
}

