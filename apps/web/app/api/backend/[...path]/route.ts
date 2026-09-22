import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  const backendUrl = process.env.BACKEND_API_URL;
  const token = process.env.INTERNAL_API_TOKEN;
  if (!backendUrl || !token) {
    const envLabel = process.env.NODE_ENV === "production" ? "Backend staging" : "Backend local";
    return Response.json({ detail: `${envLabel} chưa được cấu hình.` }, { status: 503 });
  }

  const { path } = await context.params;
  const cleanBase = backendUrl.replace(/\/+$/, "").replace(/\/api\/v1$/, "");
  const rawPath = path.join("/");
  const subPath = rawPath.replace(/^api\/v1(?:\/|$)/, "");
  const normalizedPath = subPath ? `/api/v1/${subPath}` : "/api/v1";
  const target = new URL(normalizedPath, cleanBase);
  target.search = request.nextUrl.search;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("content-type", contentType);
  if (accept) headers.set("accept", accept);
  headers.set("x-internal-api-key", token);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
      cache: "no-store",
      redirect: "follow",
    });
  } catch {
    return Response.json({ detail: "Không kết nối được backend HUCE. Kiểm tra dịch vụ API và thử lại." }, { status: 502 });
  }
  const responseHeaders = new Headers();
  for (const name of ["content-type", "content-disposition", "content-length"]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const PUT = proxy;
