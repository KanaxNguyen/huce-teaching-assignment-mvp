export type DashboardMetrics = {
  classes: number;
  locked_classes: number;
  unassigned_classes: number;
  merged_suggestions: number;
  lecturers: number;
  validation_errors: number;
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
  id: number;
  batch_id: number | null;
  draft_kind: "CONSTRAINT" | "SHARED_SEMINAR";
  lecturer_id: number | null;
  lecturer?: string | null;
  lecturer_code?: string | null;
  lecturer_alias?: string | null;
  context_type: "TEACHING" | "SEMINAR" | "MIXED";
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
  status: "DRAFT" | "CONFIRMED" | "NEEDS_REVIEW" | "REJECTED";
  applied_constraint_id?: number | null;
  applied_seminar_id?: number | null;
};

export type Lecturer = {
  id: number;
  name: string;
  code?: string | null;
  aliases?: string[];
  confirmed?: boolean;
  max_credits?: number;
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

export type TemplateDetection = {
  profile_id: number;
  source_file: string;
  source_sheet: string;
  layout: "table" | "matrix";
  layout_label: string;
  header_row: number;
  mappings: Record<string, TemplateMapping>;
  missing_fields: string[];
  available_columns: TemplateColumn[];
  weekday_columns: Array<TemplateColumn & { weekday: number }>;
  preview: Record<string, string>[];
  ready: boolean;
};
