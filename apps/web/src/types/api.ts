export type UnassignedBreakdown = {
  total: number;
  no_capability: number;
  hard_availability: number;
  timetable_collision: number;
  global_infeasibility: number;
  workload_limit: number;
  locked_conflict: number;
  eligible_available: number;
  no_eligible: number;
  data_quality: number;
  other: number;
};

export type DashboardMetrics = {
  classes: number;
  locked_classes: number;
  unassigned_classes: number;
  unassigned_breakdown?: UnassignedBreakdown;
  merged_suggestions: number;
  lecturers: number;
  validation_errors: number;
  issues_count?: number;
  optimization_status: string;
  optimization_score: number | null;
};

export type Session = {
  weekday: number;
  start_period: number;
  end_period: number;
  room: string;
  start_date?: string;
  end_date?: string;
  raw_weeks: string;
  active_weeks: number[];
};

export type ClassItem = {
  id: number;
  course_id: number;
  course_code: string;
  course_name: string;
  class_code: string;
  credits: number;
  merged_group_id: string | null;
  merged_confirmed: boolean;
  merge_status?: "single" | "candidate" | "confirmed" | "rejected";
  locked_assignment: boolean;
  assignment_source?: string | null;
  lecturer_id: number | null;
  lecturer: string | null;
  sessions: Session[];
};

export type AssignmentItem = {
  id: number;
  class_id: number;
  course_name: string;
  class_code: string;
  lecturer: string;
  locked: boolean;
  source: string;
  sessions: Array<{ weekday: number; periods: string; room: string }>;
};

export type Candidate = { lecturer_id: number; status: string; workload?: { teaching_groups: number; credits: number } };

export type CandidateAnalysisItem = {
  lecturer_id: number;
  lecturer_name: string;
  lecturer_code: string;
  status: string;
  status_label: string;
  status_badge_variant: "success" | "danger" | "warning" | "secondary";
  is_eligible: boolean;
  has_capability: boolean;
  hard_unavailable: boolean;
  has_collision: boolean;
  conflicting_classes?: Array<{
    class_id: number;
    class_code: string;
    course_name: string;
    weekday: number;
    periods: string;
    overlapping_weeks: number[];
  }>;
  preference_source?: { sheet: string; cell: string; raw_text: string } | null;
  workload: { teaching_groups: number; credits: number };
  details: string;
  is_currently_assigned?: boolean;
  is_locked_to_this?: boolean;
};

export type UnassignedDiagnosticItem = {
  class_id: number;
  course_id: number;
  course_code: string;
  course_name: string;
  class_code: string;
  credits: number;
  schedule_summary: string;
  sessions: Session[];
  root_cause: string;
  root_cause_label: string;
  root_cause_severity: "critical" | "warning" | "info";
  eligible_candidates_count: number;
  total_candidates_count: number;
  resolution_status: "NEW" | "UNDER_REVIEW" | "WAITING_FOR_DATA" | "MANUALLY_RESOLVED" | "RESOLVED_BY_SOLVER" | "ACCEPTED_UNRESOLVED";
  resolution_notes?: string | null;
  recommended_actions: Array<{
    type:
      | "OPEN_CALENDAR"
      | "REVIEW_PREFERENCES"
      | "REVIEW_CAPABILITY"
      | "MANUAL_ASSIGN"
      | "REQUEST_FACULTY_CHANGE"
      | "MERGE_CLASSES"
      | "RELAX_PREFERENCES"
      | "DEPARTMENT_POOL"
      | string;
    label: string;
    description: string;
    target_class_id?: number;
    target_class_code?: string;
    candidate_class_ids?: number[];
    candidate_class_codes?: string[];
  }>;
  bottleneck_details?: {
    weekday: number;
    period_range: string;
    overlapping_classes_count: number;
    available_lecturers_count: number;
    shortage: number;
  } | null;
};

export type Readiness = {
  ready: boolean;
  lecturers: { total: number; resolved: number; need_review: number };
  teaching_groups: number;
  meetings: number;
  valid_meetings: boolean;
  groups_without_capability: number;
  warnings: Array<{ code: string; message: string }>;
};

export type Workload = { lecturer_id: number; lecturer: string; teaching_groups: number; meetings: number; periods: number; credits: number };

export type MergeCandidate = { kind: "FULL" | "PARTIAL"; id: string; status: string; classes: Array<{ id: number; class_code: string; course: string }>; matched_meetings: number; different_meetings: number; review_only?: boolean; meeting_details?: unknown };

export type RunDiff = { run_id: number; previous_run_id: number | null; assigned: number; unassigned: number; changed_assignments: number; changes: Array<{ class_id: number; class_code: string; before_lecturer: string | null; after_lecturer: string | null; source: string | null; locked: boolean }>; new_problems: number; resolved_problems: number };

export type Seminar = { id: number; name: string; chair_name: string; members: number[]; alternatives: Array<Record<string, unknown>>; slots?: Array<Record<string, unknown>>; weight: number; hardness: "hard" | "soft" };

export type AssignmentCheck = {
  valid: boolean;
  blocking_reasons: string[];
  warnings: string[];
  affected_groups: number[];
};

export type Problem = {
  code: string;
  severity: "critical" | "warning" | "info";
  entity_type: string;
  entity_id: string;
  lecturer_id: number | null;
  message: string;
  reasons: Array<Record<string, unknown>>;
  related_constraints: Array<string | number>;
  resolvable: boolean;
};

export type OptimizationResult = {
  run_id: number;
  status: string;
  score: number | null;
  summary: Record<string, unknown>;
};

export type Constraint = {
  id: number;
  name: string;
  constraint_type: string;
  hardness: "hard" | "soft";
  weight: number;
  lecturer_id?: number | null;
  lecturer?: string;
  raw_text?: string;
  normalized_text?: string;
  confirmed: boolean;
  active: boolean;
  target?: Record<string, unknown>;
};

export type PreferenceDraft = {
  normalized_text?: string;
  is_confirmable?: boolean;
  validation_errors?: Array<{code: string; field: string; message: string}>;
  validation_warnings?: Array<{code: string; field: string; message: string}>;
  field_provenance?: Record<string, {origin: string}>;
  id: number;
  batch_id: number | null;
  draft_kind: "CONSTRAINT" | "SHARED_SEMINAR";
  lecturer_id: number | null;
  lecturer?: string | null;
  lecturer_code?: string | null;
  lecturer_alias?: string | null;
  context_type: "TEACHING" | "SEMINAR" | "MIXED" | null;
  context_confidence?: "HIGH" | "MEDIUM" | "LOW" | null;
  context_confirmed?: boolean;
  constraint_type: string;
  day_scope?: string | null;
  periods: number[];
  start_date?: string | null;
  end_date?: string | null;
  hardness: "hard" | "soft";
  weight: number;
  numeric_value?: number | null;
  target: Record<string, unknown>;
  participant_codes: string[];
  seminar_link?: string | null;
  source_file: string;
  source_sheet: string;
  source_row: number;
  source_cell: string;
  raw_text?: string | null;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  needs_review: boolean;
  review_reason?: string | null;
  status: "DRAFT" | "CONFIRMED" | "NEEDS_REVIEW" | "REJECTED" | "INTERPRETED";
  rejected_at?: string | null;
  rejected_reason?: string | null;
  applied_constraint_id?: number | null;
  applied_seminar_id?: number | null;
};

export type LecturerReviewItem = {
  id: number;
  code: string | null;
  name: string;
  email: string | null;
  department: string | null;
  quota_min: number;
  quota_max: number;
  aliases: string[];
  identity_status: "STANDARDIZED" | "NEEDS_CONFIRMATION" | "POSSIBLE_DUPLICATE";
  sources: string[];
  participates: boolean;
  courses_can_teach: string[];
  capabilities: Array<{course_id: number; course_code: string; course_name: string; allowed: boolean; confirmed: boolean; source: string | null}>;
  active: boolean;
  notes?: string | null;
};

export type LecturerReviewResponse = {
  semester_id: number;
  semester_name: string;
  total_lecturers: number;
  ready_count: number;
  needs_review_count: number;
  blockers_count: number;
  blockers: string[];
  items: LecturerReviewItem[];
};

export type LecturerImportPreviewRow = {
  row: number;
  code: string;
  name: string;
  email?: string | null;
  department?: string | null;
  quota_min?: number;
  quota_max?: number;
  aliases: string[];
  participates: boolean;
  match_rule: string;
  matched_lecturer_id?: number | null;
  issues: string[];
};

export type LecturerImportPreview = {
  total_rows: number;
  to_add: LecturerImportPreviewRow[];
  to_update: LecturerImportPreviewRow[];
  needs_confirmation: LecturerImportPreviewRow[];
  possible_duplicates: LecturerImportPreviewRow[];
  skipped: LecturerImportPreviewRow[];
  can_commit: boolean;
};

export type LecturerImportResult = {
  added: number;
  updated: number;
  aliases_created: number;
  participations_updated: number;
};

export type Lecturer = {
  id: number;
  name: string;
  code?: string | null;
  aliases?: string[];
  confirmed?: boolean;
  max_credits?: number;
  status?: string;
  department?: string;
  email?: string;
  note?: string;
};

export type ValidationIssue = {
  id: number;
  severity: string;
  code: string;
  message: string;
  source_file?: string;
  source_row?: number;
  suggestion?: string;
  raw_value?: string;
};

export type Semester = {
  id: number;
  name: string;
  department_name: string;
  start_date: string;
  end_date: string;
  head_name: string;
  status: string;
  is_active: boolean;
};

export type TemplateColumn = {
  column_index: number;
  column_letter: string;
  header: string;
};

export type TemplateMapping = TemplateColumn & { confidence: number };

export type HistoricalSummary = {
  columns_count: number;
  data_rows_count: number;
  courses_count: number;
  classes_count: number;
  merged_groups_count: number;
  lecturers_count: number;
  lecturers_with_code?: number;
};

export type LecturerIdentitySummary = {
  total: number;
  with_code: number;
  matched_master: number;
  need_review: number;
  new_candidates: number;
};

export type TemplateDetection = {
  profile_id: number;
  source_file: string;
  source_sheet: string;
  layout: "table" | "matrix";
  layout_label: string;
  header_row: number;
  header_start_row?: number;
  header_end_row?: number;
  mappings: Record<string, TemplateMapping>;
  missing_fields: string[];
  available_columns: TemplateColumn[];
  weekday_columns: Array<TemplateColumn & { weekday: number }>;
  preview: Record<string, string>[];
  ready: boolean;
  historical_summary?: HistoricalSummary;
  lecturer_identity_summary?: LecturerIdentitySummary;
  historical_learning?: {status?: string; message?: string};
};

export type SourceRole = 'CURRENT_SCHEDULE' | 'PREFERENCE' | 'HISTORICAL' | 'OUTPUT_TEMPLATE' | 'REFERENCE_MATRIX';
export type SourceVersion = {
  id: number; source_type: SourceRole; original_filename: string; content_hash: string | null;
  created_at: string; provenance_status: string; active: boolean; parent_version_id: number | null;
  parse_summary: Record<string, unknown>;
};
export type SourceIssue = { id: number; code: string; message: string; details: { rows?: Array<{row: number; raw: string}>; class_code?: string }; resolution_status: string };
export type SourceState = { sources: SourceVersion[]; active_schedule_source_id: number | null; active_preference_source_id: number | null; source_revision: number; legacy_unverified: boolean; issues: SourceIssue[] };
export type SourcePreview = {
  source_id: number; source_type: SourceRole; filename: string; preview_token: string; can_activate: boolean;
  diff: { counts?: Record<string, number>; meetings?: Array<{status: string; before: Record<string, unknown> | null; after: Record<string, unknown> | null; changed_fields: string[]}>; drafts?: number; seminars?: number };
  diagnostics: Array<{code: string; message: string}>; consequences: string[];
};

export type CapabilityReadiness = {
  department_id?: number | null;
  department_name?: string | null;
  total_lecturers: number;
  total_courses: number;
  total_teaching_groups: number;
  confirmed_groups: number;
  historical_groups: number;
  provisional_groups: number;
  zero_candidate_groups: number;
  confirmed_coverage_pct: number;
  historical_coverage_pct: number;
  provisional_coverage_pct: number;
  unknown_coverage_pct: number;
  courses_without_capability: Array<{
    course_id: number;
    course_code: string;
    course_name: string;
    affected_groups: number;
  }>;
  status: "READY" | "CAPABILITY_REVIEW_REQUIRED" | "NOT_READY";
  ready: boolean;
  recommendations: string[];
};

