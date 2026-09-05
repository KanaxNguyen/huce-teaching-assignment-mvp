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
  course_code: string;
  course_name: string;
  class_code: string;
  credits: number;
  merged_group_id: string | null;
  merged_confirmed: boolean;
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

export type Candidate = { lecturer_id: number; status: string };

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
