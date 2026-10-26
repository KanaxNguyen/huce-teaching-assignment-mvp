interface Env {
  BACKEND_API_URL: string;
  HF_TOKEN?: string;
}

async function ping(env: Env): Promise<Response> {
  const headers = new Headers();
  if (env.HF_TOKEN) headers.set("authorization", `Bearer ${env.HF_TOKEN}`);
  const base = env.BACKEND_API_URL.replace(/\/+$/, "").replace(/\/api\/v1$/, "");
  return fetch(`${base}/api/v1/health`, { headers, signal: AbortSignal.timeout(90_000) });
}

export default {
  // Scheduled run: a sleeping Space wakes on the first request, later requests keep it awake.
  async scheduled(_event: unknown, env: Env): Promise<void> {
    const response = await ping(env);
    console.log(`keepwarm ${response.status}`);
  },
  // Manual check: open the worker URL to see whether the backend answers.
  async fetch(_request: Request, env: Env): Promise<Response> {
    const response = await ping(env);
    return Response.json({ backend_status: response.status });
  },
};
