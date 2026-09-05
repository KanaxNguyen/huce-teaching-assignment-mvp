import type { AssignmentCheck, AssignmentItem, Candidate, ClassItem, Constraint, DashboardMetrics, Lecturer, MergeCandidate, OptimizationResult, Problem, Readiness, RunDiff, Seminar, Semester, TemplateDetection, ValidationIssue, Workload } from "@/src/types/api";

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
  lecturers: () => request<Lecturer[]>("/lecturers"),
  conflicts: () => request<ValidationIssue[]>("/conflicts"),
  readiness: (semesterId: number) => request<Readiness>(`/readiness?semester_id=${semesterId}`),
  workload: (semesterId: number) => request<Workload[]>(`/workload?semester_id=${semesterId}`),
  mergeCandidates: (semesterId: number) => request<MergeCandidate[]>(`/merge-candidates?semester_id=${semesterId}`),
  decideMerge: (mergedGroupId: string, confirmed: boolean, semesterId: number) => request<{ merged_group_id: string; confirmed: boolean }>(`/merged-groups?semester_id=${semesterId}`, { method: "PATCH", body: JSON.stringify({ merged_group_id: mergedGroupId, confirmed }) }),
  problems: (semesterId: number) => request<Problem[]>(`/problems?semester_id=${semesterId}`),
  assignments: () => request<AssignmentItem[]>("/assignments"),
  semesters: () => request<Semester[]>("/semesters"),
  latestTemplate: () => request<TemplateDetection | null>("/templates/latest"),
  createSemester: (payload: Omit<Semester, "id" | "status" | "is_active">) =>
    request<{ id: number }>("/semesters", { method: "POST", body: JSON.stringify(payload) }),
  detectTemplate: (file: File, semesterId?: number) => {
    const body = new FormData();
    body.append("template_file", file);
    const query = semesterId ? `?semester_id=${semesterId}` : "";
    return request<TemplateDetection>(`/templates/detect${query}`, { method: "POST", body });
  },
  updateTemplate: (profileId: number, mappings: TemplateDetection["mappings"], missingFields: string[]) =>
    request<{ id: number; ready: boolean }>(`/templates/${profileId}`, {
      method: "PATCH",
      body: JSON.stringify({ mappings, missing_fields: missingFields }),
    }),
  importLocal: () => request<Record<string, unknown>>("/imports/local", { method: "POST" }),
  upload: (files: File[]) => {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    return request<Record<string, unknown>>("/imports/upload", { method: "POST", body });
  },
  uploadPair: (scheduleFile: File, preferenceFile: File) => {
    const body = new FormData();
    body.append("schedule_file", scheduleFile);
    body.append("preference_file", preferenceFile);
    return request<Record<string, unknown>>("/imports/upload-pair", { method: "POST", body });
  },
  createConstraint: (payload: Record<string, unknown>) =>
    request<{ id: number }>("/constraints", { method: "POST", body: JSON.stringify(payload) }),
  updateConstraint: (id: number, payload: Partial<Constraint>) =>
    request<{ id: number }>(`/constraints/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteConstraint: (id: number) =>
    request<{ id: number }>(`/constraints/${id}`, { method: "DELETE" }),
  optimize: (confirmMerged: boolean) =>
    request<OptimizationResult>("/optimization/run", {
      method: "POST",
      body: JSON.stringify({ time_limit_seconds: 30, confirm_merged_suggestions: confirmMerged }),
    }),
  runDiff: (runId: number, semesterId: number) => request<RunDiff>(`/optimization/runs/${runId}/diff?semester_id=${semesterId}`),
  runs: (semesterId: number) => request<Array<{ id: number; status: string; score: number | null; summary: Record<string, unknown>; created_at: string }>>(`/optimization/runs?semester_id=${semesterId}`),
  seminars: (semesterId: number) => request<Seminar[]>(`/seminars?semester_id=${semesterId}`),
  createSeminar: (payload: Record<string, unknown>, semesterId: number) => request<{ id: number }>(`/seminars?semester_id=${semesterId}`, { method: "POST", body: JSON.stringify(payload) }),
  resolveAlias: (lecturerId: number, alias: string, semesterId: number) => request<{ resolved: boolean }>(`/lecturers/${lecturerId}/aliases?semester_id=${semesterId}`, { method: "POST", body: JSON.stringify({ alias }) }),
  candidates: (classId: number, semesterId: number) => request<Candidate[]>(`/classes/${classId}/candidates?semester_id=${semesterId}`),
  checkAssignment: (classId: number, lecturerId: number, semesterId: number) => request<AssignmentCheck>(`/classes/${classId}/assignment/check?semester_id=${semesterId}`, { method: "POST", body: JSON.stringify({ lecturer_id: lecturerId }) }),
  assign: (classId: number, lecturerId: number, lock: boolean, semesterId: number) => request<AssignmentCheck>(`/classes/${classId}/assignment?semester_id=${semesterId}`, { method: "PATCH", body: JSON.stringify({ lecturer_id: lecturerId, lock }) }),
  lock: (classId: number, semesterId: number) => request<{ locked: boolean }>(`/classes/${classId}/lock?semester_id=${semesterId}`, { method: "POST" }),
  unlock: (classId: number, semesterId: number) => request<{ locked: boolean }>(`/classes/${classId}/unlock?semester_id=${semesterId}`, { method: "POST" }),
  exportUrl: (mode: "draft" | "final" = "draft", semesterId?: number) => `${API_URL}/api/v1/exports/latest?mode=${mode}${semesterId ? `&semester_id=${semesterId}` : ""}`,
};
