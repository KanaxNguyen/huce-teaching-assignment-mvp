import type {
  AppSettings,
  ClassItem,
  Constraint,
  DashboardMetrics,
  ImportBatch,
  Lecturer,
  OptimizationRun,
  Seminar,
  ValidationIssue,
} from "@/src/types/api";

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
  settings: () => request<AppSettings>("/settings"),
  updateSettings: (payload: AppSettings) =>
    request<AppSettings>("/settings", { method: "PUT", body: JSON.stringify(payload) }),
  dashboard: () => request<DashboardMetrics>("/dashboard"),
  classes: () => request<ClassItem[]>("/classes"),
  constraints: () => request<Constraint[]>("/constraints"),
  lecturers: () => request<Lecturer[]>("/lecturers"),
  seminars: () => request<Seminar[]>("/seminars"),
  latestImport: () => request<{ batch: ImportBatch | null }>("/imports/latest"),
  optimizationRuns: () => request<OptimizationRun[]>("/optimization/runs?limit=8"),
  conflicts: () => request<ValidationIssue[]>("/conflicts"),
  importLocal: () => request<Record<string, unknown>>("/imports/local", { method: "POST" }),
  upload: (files: File[]) => {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    return request<Record<string, unknown>>("/imports/upload", { method: "POST", body });
  },
  uploadBundle: (scheduleFile: File, preferenceFile: File, templateFile?: File | null) => {
    const body = new FormData();
    body.append("schedule_file", scheduleFile);
    body.append("preference_file", preferenceFile);
    if (templateFile) body.append("template_file", templateFile);
    return request<Record<string, unknown>>("/imports/upload-bundle", { method: "POST", body });
  },
  createConstraint: (payload: Record<string, unknown>) =>
    request<{ id: number }>("/constraints", { method: "POST", body: JSON.stringify(payload) }),
  updateConstraint: (id: number, payload: Record<string, unknown>) =>
    request<{ id: number }>(`/constraints/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteConstraint: (id: number) => request<{ id: number }>(`/constraints/${id}`, { method: "DELETE" }),
  updateSeminar: (id: number, payload: Record<string, unknown>) =>
    request<{ id: number }>(`/seminars/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  optimize: (confirmMerged: boolean) =>
    request<{ run_id: number; status: string; score: number }>("/optimization/run", {
      method: "POST",
      body: JSON.stringify({ time_limit_seconds: 30, confirm_merged_suggestions: confirmMerged }),
    }),
  exportUrl: `${API_URL}/api/v1/exports/latest`,
  calendarUrl: (lecturer?: string) =>
    `${API_URL}/api/v1/exports/calendar.ics${lecturer ? `?lecturer=${encodeURIComponent(lecturer)}` : ""}`,
  csvUrl: (lecturer?: string) =>
    `${API_URL}/api/v1/exports/assignments.csv${lecturer ? `?lecturer=${encodeURIComponent(lecturer)}` : ""}`,
  jsonUrl: (lecturer?: string) =>
    `${API_URL}/api/v1/exports/schedule.json${lecturer ? `?lecturer=${encodeURIComponent(lecturer)}` : ""}`,
  googleCalendarImportUrl: "https://calendar.google.com/calendar/u/0/r/settings/export",
};
