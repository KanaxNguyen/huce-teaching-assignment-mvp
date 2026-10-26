import { afterEach, describe, expect, it, vi } from "vitest";
import { backendNotReady, backendUrl, proxyToBackend } from "@/lib/backend-proxy";

const env = { BACKEND_API_URL: "https://owner-space.hf.space/", INTERNAL_API_TOKEN: "secret", BACKEND_WAKE_BUDGET_MS: "6000" };
const ok = () => Response.json({ ok: true });
const html = () => new Response("<html>Space is starting</html>", { status: 200, headers: { "content-type": "text/html" } });

afterEach(() => vi.restoreAllMocks());

describe("backend proxy", () => {
  it("builds the backend URL without doubling /api/v1 and keeps the query string", () => {
    expect(backendUrl("https://h.example/api/v1/", ["api", "v1", "classes"], "?semester_id=1").href).toBe("https://h.example/api/v1/classes?semester_id=1");
    expect(backendUrl("https://h.example", [], "").pathname).toBe("/api/v1");
  });

  it("refuses to run without configuration", async () => {
    const response = await proxyToBackend(new Request("https://x/api/backend/api/v1/health"), ["api", "v1", "health"], {});
    expect(response.status).toBe(503);
  });

  it("adds the internal token, and the Hugging Face token only when configured", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => ok());
    await proxyToBackend(new Request("https://x/p", { headers: { cookie: "leak" } }), ["classes"], env);
    await proxyToBackend(new Request("https://x/p"), ["classes"], { ...env, HF_TOKEN: "hf_abc" });
    const first = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    const second = new Headers((fetchMock.mock.calls[1][1] as RequestInit).headers);
    expect(first.get("x-internal-api-key")).toBe("secret");
    expect(first.get("authorization")).toBeNull();
    expect(first.get("cookie")).toBeNull();
    expect(second.get("authorization")).toBe("Bearer hf_abc");
  });

  it("retries while the sleeping backend answers with an HTML page, then succeeds", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementationOnce(async () => html()).mockImplementationOnce(async () => new Response("", { status: 503 })).mockImplementation(async () => ok());
    const pending = proxyToBackend(new Request("https://x/p", { method: "POST", body: "{}" }), ["optimization", "run"], env);
    await vi.advanceTimersByTimeAsync(10000);
    const response = await pending;
    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    vi.useRealTimers();
  });

  it("gives a clear 503 when the backend never wakes within the budget", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => { throw new TypeError("network"); });
    const pending = proxyToBackend(new Request("https://x/p"), ["classes"], env);
    await vi.advanceTimersByTimeAsync(20000);
    const response = await pending;
    expect(response.status).toBe(503);
    expect((await response.json()).detail).toContain("khởi động");
    vi.useRealTimers();
  });

  it("passes real API errors (JSON 4xx) through without retrying", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json({ detail: "bad" }, { status: 422 }));
    const response = await proxyToBackend(new Request("https://x/p"), ["classes"], env);
    expect(response.status).toBe(422);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(backendNotReady(new Response("", { status: 404, headers: { "content-type": "application/json" } }))).toBe(false);
  });
});
