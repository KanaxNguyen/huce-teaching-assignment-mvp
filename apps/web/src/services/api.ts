import type { SourceState, SourcePreview, SourceRole, AssignmentCheck, AssignmentItem, Candidate, CandidateAnalysisItem, CapabilityReadiness, ClassItem, Constraint, DashboardMetrics, Lecturer, LecturerImportPreview, LecturerImportResult, LecturerReviewResponse, MergeCandidate, OptimizationResult, PreferenceDraft, Problem, Readiness, RunDiff, Seminar, Semester, TemplateDetection, UnassignedDiagnosticItem, ValidationIssue, Workload } from "@/src/types/api";

// Keep browser requests on the same origin in every environment. The BFF owns
// the backend host and credentials, including during local development.
export const API_URL = "/api/backend";

function requestError(reason: unknown): Error {
  if (reason instanceof TypeError) {
    return new Error("Không kết nối được máy chủ HUCE. Kiểm tra backend và thử tải lại dữ liệu.");
  }
  return reason instanceof Error ? reason : new Error("Không thể hoàn tất yêu cầu. Hãy thử lại.");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/v1${path}`, {
      ...init,
      headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (reason) {
    throw requestError(reason);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Máy chủ HUCE trả về lỗi. Hãy thử tải lại dữ liệu." }));
    const detail = payload.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.message ?? detail?.validation_errors?.map((e: {message: string}) => e.message).join('; ') ?? 'Yêu cầu thất bại.');
  }
  return response.json() as Promise<T>;
}

export const api = {
  uploadSource: (file: File, role: SourceRole, semesterId: number) => {
    const body = new FormData(); body.append('file', file);
    return request(`/sources/upload?semester_id=${semesterId}&source_type=${role}`, {method: 'POST', body});
  },
  sources: (semesterId: number) => request<SourceState>(`/sources?semester_id=${semesterId}`),
  previewSource: (id: number, role: SourceRole, semesterId: number) => request<SourcePreview>(`/sources/${id}/preview?semester_id=${semesterId}`, {method: 'POST', body: JSON.stringify({source_type: role})}),
  activateSource: (preview: SourcePreview, semesterId: number) => request(`/sources/${preview.source_id}/activate?semester_id=${semesterId}`, {method: 'POST', body: JSON.stringify({source_type: preview.source_type, confirmed: true, preview_token: preview.preview_token})}),
  resolveSourceIssue: (id: number, payload: Record<string, unknown>, semesterId: number) => request(`/sources/reviews/${id}/resolve?semester_id=${semesterId}`, {method: 'POST', body: JSON.stringify(payload)}),
  dashboard: () => request<DashboardMetrics>("/dashboard"),
  classes: () => request<ClassItem[]>("/classes"),
  constraints: () => request<Constraint[]>("/constraints"),
  lecturers: () => request<Lecturer[]>("/lecturers"),
  conflicts: () => request<ValidationIssue[]>("/conflicts"),
  readiness: (semesterId: number) => request<Readiness>(`/readiness?semester_id=${semesterId}`),
  workload: (semesterId: number) => request<Workload[]>(`/workload?semester_id=${semesterId}`),
  mergeCandidates: (semesterId: number) => request<MergeCandidate[]>(`/merge-candidates?semester_id=${semesterId}`),
  decideMerge: (mergedGroupId: string, confirmed: boolean, semesterId: number) => request<{ merged_group_id: string; confirmed: boolean }>(`/merged-groups?semester_id=${semesterId}`, { method: "PATCH", body: JSON.stringify({ merged_group_id: mergedGroupId, confirmed }) }),
  mergeClasses: (classIds: number[], semesterId: number, mergedGroupId?: string) =>
    request<{
      merged_group_id: string;
      confirmed: boolean;
      classes: number;
      class_ids: number[];
      class_codes: string[];
    }>(`/classes/merge?semester_id=${semesterId}`, {
      method: "POST",
      body: JSON.stringify({ class_ids: classIds, merged_group_id: mergedGroupId }),
    }),
  unmergeClasses: (classIds: number[], semesterId: number, mergedGroupId?: string) =>
    request<{
      unmerged: number;
      class_ids: number[];
    }>(`/classes/unmerge?semester_id=${semesterId}`, {
      method: "POST",
      body: JSON.stringify({ class_ids: classIds, merged_group_id: mergedGroupId }),
    }),
  problems: (semesterId: number) => request<Problem[]>(`/problems?semester_id=${semesterId}`),
  assignments: () => request<AssignmentItem[]>("/assignments"),
  semesters: () => request<Semester[]>("/semesters"),
  latestTemplate: (semesterId?: number) =>
    request<TemplateDetection | null>(`/templates/latest${semesterId ? `?semester_id=${semesterId}` : ""}`),
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
  uploadPair: (scheduleFile: File, preferenceFile: File, semesterId?: number) => {
    const body = new FormData();
    body.append("schedule_file", scheduleFile);
    body.append("preference_file", preferenceFile);
    return request<Record<string, unknown>>(`/imports/upload-pair${semesterId ? `?semester_id=${semesterId}` : ""}`, { method: "POST", body });
  },
  preferenceDrafts: (semesterId: number) => request<PreferenceDraft[]>(`/preference-drafts?semester_id=${semesterId}`),
  createPreferenceDraft: (payload: Record<string, unknown>, semesterId: number) =>
    request<{ ids: number[]; created: number; atomic_split: boolean }>(`/preference-drafts?semester_id=${semesterId}`, { method: "POST", body: JSON.stringify(payload) }),
  updatePreferenceDraft: (id: number, payload: Partial<PreferenceDraft>, semesterId: number) =>
    request<PreferenceDraft>(`/preference-drafts/${id}?semester_id=${semesterId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  validatePreferenceDraft: (id: number, payload: Partial<PreferenceDraft>, semesterId: number) =>
    request<{is_confirmable: boolean; validation_errors: Array<{code: string; field: string; message: string}>}>(`/preference-drafts/${id}/validate?semester_id=${semesterId}`, {method:'POST',body:JSON.stringify(payload)}),
  validateNewPreferenceDraft: (payload: Record<string,unknown>,semesterId:number) =>
    request<{is_confirmable:boolean;validation_errors:Array<{code:string;field:string;message:string}>}>(`/preference-drafts/validate?semester_id=${semesterId}`,{method:'POST',body:JSON.stringify(payload)}),
  confirmHighPreferenceDrafts: (semesterId: number) =>
    request<{ confirmed: number }>(`/preference-drafts/confirm-high?semester_id=${semesterId}`, { method: "POST" }),
  applyPreferenceDrafts: (ids: number[], semesterId: number) =>
    request<{ applied: number; constraints: number; seminars: number }>(`/preference-drafts/apply?semester_id=${semesterId}`, { method: "POST", body: JSON.stringify({ draft_ids: ids }) }),
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
  lecturerReview: (semesterId: number) => request<LecturerReviewResponse>(`/lecturers/review?semester_id=${semesterId}`),
  createLecturer: (payload: Record<string, unknown>, semesterId: number) =>
    request<{ id: number; message: string }>(`/lecturers?semester_id=${semesterId}`, { method: "POST", body: JSON.stringify(payload) }),
  updateLecturer: (id: number, payload: Record<string, unknown>, semesterId: number) =>
    request<{ id: number; message: string }>(`/lecturers/${id}?semester_id=${semesterId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  mergeLecturers: (sourceId: number, targetId: number, semesterId: number) =>
    request<{ success: boolean; message: string; target_id: number }>(`/lecturers/${sourceId}/merge?semester_id=${semesterId}`, { method: "POST", body: JSON.stringify({ target_id: targetId, confirmed: true }) }),
  previewLecturerImport: (file: File, semesterId: number) => {
    const body = new FormData();
    body.append("file", file);
    return request<LecturerImportPreview>(`/lecturers/import/preview?semester_id=${semesterId}`, { method: "POST", body });
  },
  commitLecturerImport: (file: File, semesterId: number) => {
    const body = new FormData();
    body.append("file", file);
    return request<LecturerImportResult>(`/lecturers/import?semester_id=${semesterId}`, { method: "POST", body });
  },
  exportLecturersUrl: (semesterId: number) => `${API_URL}/api/v1/lecturers/export?semester_id=${semesterId}`,
  rejectPreferenceDraft: (id: number, reason: string, semesterId: number) =>
    request<PreferenceDraft>(`/preference-drafts/${id}?semester_id=${semesterId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "REJECTED", rejected_reason: reason }),
    }),
  restorePreferenceDraft: (id: number, semesterId: number) =>
    request<PreferenceDraft>(`/preference-drafts/${id}?semester_id=${semesterId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "NEEDS_REVIEW" }),
    }),
  candidates: (classId: number, semesterId: number) => request<Candidate[]>(`/classes/${classId}/candidates?semester_id=${semesterId}`),
  unassignedClasses: (semesterId: number, runId?: number) =>
    request<UnassignedDiagnosticItem[]>(`/classes/unassigned?semester_id=${semesterId}${runId ? `&run_id=${runId}` : ""}`),
  candidateAnalysis: (classId: number, semesterId: number, runId?: number) =>
    request<CandidateAnalysisItem[] | { analysis_rows?: CandidateAnalysisItem[] }>(
      `/classes/${classId}/candidate-analysis?semester_id=${semesterId}${runId ? `&run_id=${runId}` : ""}`
    ).then((data) =>
      Array.isArray(data) ? data : (data?.analysis_rows || [])
    ),
  capabilityReadiness: (semesterId: number) =>
    request<CapabilityReadiness>(`/semesters/${semesterId}/capability-readiness`),
  importCapabilityMatrix: (semesterId: number, file: File, confirmed: boolean = true) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<Record<string, unknown>>(`/semesters/${semesterId}/capabilities/import-matrix?confirmed=${confirmed}`, {
      method: "POST",
      body: formData,
    });
  },
  learnHistoricalCapabilities: (semesterId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<Record<string, unknown>>(`/semesters/${semesterId}/capabilities/learn-history`, {
      method: "POST",
      body: formData,
    });
  },
  departments: () => request<Array<{ id: number; name: string; code: string; description?: string }>>("/departments"),
  departmentPolicy: (deptId: number) => request<Record<string, unknown>>(`/departments/${deptId}/policy`),
  updateDepartmentPolicy: (deptId: number, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/departments/${deptId}/policy`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  updateResolutionStatus: (classId: number, status: string, notes: string | null, semesterId: number) =>
    request<{ class_id: number; resolution_status: string; resolution_notes: string | null }>(
      `/classes/${classId}/resolution-status?semester_id=${semesterId}`,
      { method: "PATCH", body: JSON.stringify({ status, notes }) }
    ),
  overrideLock: (classId: number, lecturerId: number, reason: string, lock: boolean, semesterId: number) =>
    request<{ success: boolean; class_id: number; new_lecturer_id: number; locked: boolean }>(
      `/classes/${classId}/override-lock?semester_id=${semesterId}`,
      { method: "POST", body: JSON.stringify({ lecturer_id: lecturerId, reason, lock }) }
    ),
  checkAssignment: (classId: number, lecturerId: number, semesterId: number) => request<AssignmentCheck>(`/classes/${classId}/assignment/check?semester_id=${semesterId}`, { method: "POST", body: JSON.stringify({ lecturer_id: lecturerId }) }),
  assign: (classId: number, lecturerId: number, lock: boolean, semesterId: number, allowOverrideLock: boolean = false, overrideReason: string = "") =>
    request<AssignmentCheck>(`/classes/${classId}/assignment?semester_id=${semesterId}`, {
      method: "PATCH",
      body: JSON.stringify({ lecturer_id: lecturerId, lock, allow_override_lock: allowOverrideLock, override_reason: overrideReason }),
    }),
  lock: (classId: number, semesterId: number) => request<{ locked: boolean }>(`/classes/${classId}/lock?semester_id=${semesterId}`, { method: "POST" }),
  unlock: (classId: number, semesterId: number) => request<{ locked: boolean }>(`/classes/${classId}/unlock?semester_id=${semesterId}`, { method: "POST" }),
  exportUrl: (mode: "draft" | "final" = "draft", semesterId?: number, exportType: "detailed" | "matrix" = "detailed", allowOverride: boolean = false, overrideReason: string = "") =>
    `${API_URL}/api/v1/exports/latest?mode=${mode}&export_type=${exportType}${semesterId ? `&semester_id=${semesterId}` : ""}${allowOverride ? `&allow_unassigned_override=true&override_reason=${encodeURIComponent(overrideReason)}` : ""}`,
  matrixExportUrl: (mode: "draft" | "final" = "draft", semesterId?: number, allowOverride: boolean = false, overrideReason: string = "") =>
    `${API_URL}/api/v1/exports/matrix?mode=${mode}${semesterId ? `&semester_id=${semesterId}` : ""}${allowOverride ? `&allow_unassigned_override=true&override_reason=${encodeURIComponent(overrideReason)}` : ""}`,
};

