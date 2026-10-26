// Cloudflare Pages Function: same BFF as app/api/backend, for the static export.
import { proxyToBackend, type ProxyEnv } from "../../../lib/backend-proxy";

export const onRequest = async (context: { request: Request; env: ProxyEnv; params: { path?: string | string[] } }) => {
  const raw = context.params.path;
  const segments = Array.isArray(raw) ? raw : raw ? [raw] : [];
  return proxyToBackend(context.request, segments, context.env, "Backend");
};
