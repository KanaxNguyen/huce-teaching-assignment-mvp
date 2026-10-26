// Framework-neutral BFF proxy shared by the Next.js route handler (local, Vercel)
// and the Cloudflare Pages Function. It only uses the standard Request/Response API.

export type ProxyEnv = {
  BACKEND_API_URL?: string;
  INTERNAL_API_TOKEN?: string;
  /** Hugging Face access token; only needed when the Space is private. */
  HF_TOKEN?: string;
  /** Milliseconds to keep retrying while a sleeping backend wakes up. Default 20000. */
  BACKEND_WAKE_BUDGET_MS?: string;
};

const FORWARDED_REQUEST_HEADERS = ["content-type", "accept"];
const FORWARDED_RESPONSE_HEADERS = ["content-type", "content-disposition", "content-length"];

function json(detail: string, status: number): Response {
  return Response.json({ detail }, { status });
}

/** The API answers JSON or xlsx. An HTML page, or a gateway error, means the container is not serving yet. */
export function backendNotReady(response: Response): boolean {
  if ([502, 503, 504].includes(response.status)) return true;
  return (response.headers.get("content-type") ?? "").toLowerCase().startsWith("text/html");
}

export function backendUrl(base: string, segments: string[], search: string): URL {
  const cleanBase = base.replace(/\/+$/, "").replace(/\/api\/v1$/, "");
  const subPath = segments.join("/").replace(/^api\/v1(?:\/|$)/, "");
  const target = new URL(subPath ? `/api/v1/${subPath}` : "/api/v1", cleanBase);
  target.search = search;
  return target;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function proxyToBackend(request: Request, segments: string[], env: ProxyEnv | Record<string, string | undefined>, label = "Backend"): Promise<Response> {
  const config = env as ProxyEnv;
  if (!config.BACKEND_API_URL || !config.INTERNAL_API_TOKEN) return json(`${label} chưa được cấu hình.`, 503);

  const target = backendUrl(config.BACKEND_API_URL, segments, new URL(request.url).search);
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("x-internal-api-key", config.INTERNAL_API_TOKEN);
  if (config.HF_TOKEN) headers.set("authorization", `Bearer ${config.HF_TOKEN}`);

  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer();
  const budget = Number(config.BACKEND_WAKE_BUDGET_MS ?? 20000);
  const started = Date.now();
  let delay = 1500;
  let upstream: Response | null = null;

  for (;;) {
    try {
      upstream = await fetch(target, { method: request.method, headers, body, cache: "no-store", redirect: "follow" });
      if (!backendNotReady(upstream)) break;
      await upstream.body?.cancel();
    } catch {
      upstream = null;
    }
    if (Date.now() - started + delay > budget) {
      return json("Máy chủ HUCE đang khởi động hoặc tạm thời không phản hồi. Hãy đợi khoảng một phút rồi tải lại.", 503);
    }
    await sleep(delay);
    delay = Math.min(delay * 1.5, 5000);
  }

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}
