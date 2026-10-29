import { createNeonAuth } from "@neondatabase/auth/next/server";

async function handle(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const baseUrl = process.env.NEON_AUTH_BASE_URL;
  const secret = process.env.NEON_AUTH_COOKIE_SECRET;
  if (new URL(request.url).pathname === "/api/auth/config") {
    return Response.json({ configured: !!baseUrl && !!secret });
  }
  if (!baseUrl || !secret) {
    return Response.json(
      { message: "Account sign-in is not configured yet." },
      { status: 503 },
    );
  }
  const handlers = createNeonAuth({ baseUrl, cookies: { secret } }).handler();
  return request.method === "GET"
    ? handlers.GET(request, context)
    : handlers.POST(request, context);
}

export const GET = handle;
export const POST = handle;
