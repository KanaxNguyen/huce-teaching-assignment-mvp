import type { ClassItem, Constraint, DashboardMetrics, ValidationIssue } from "@/src/types/api";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}/api/v1${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Không thể kết nối máy chủ." }));
    throw new Error(payload.detail ?? "Yêu cầu thất bại.");
  }
  return response.json() as Promise<T>;
}

export const api = {
  dashboard: () => request<DashboardMetrics>("/dashboard"),
  classes: () => request<ClassItem[]>("/classes"),
  constraints: () => request<Constraint[]>("/constraints"),
  conflicts: () => request<ValidationIssue[]>("/conflicts"),
  importLocal: () => request<Record<string, unknown>>("/imports/local", { method: "POST" }),
  upload: (files: File[]) => {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    return request<Record<string, unknown>>("/imports/upload", { method: "POST", body });
  },
  createConstraint: (payload: Record<string, unknown>) =>
    request<{ id: number }>("/constraints", { method: "POST", body: JSON.stringify(payload) }),
  optimize: (confirmMerged: boolean) =>
    request<{ run_id: number; status: string; score: number }>("/optimization/run", {
      method: "POST",
      body: JSON.stringify({ time_limit_seconds: 30, confirm_merged_suggestions: confirmMerged }),
    }),
  exportUrl: `${API_URL}/api/v1/exports/latest`,
};

