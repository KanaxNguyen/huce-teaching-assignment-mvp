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

export type AppSettings = {
  academic_year: string;
  semester: number;
  semester_start: string | null;
  semester_end: string | null;
  institution: string;
  department: string;
  calendar_name: string;
  timezone_name: string;
  primary_lecturer: string | null;
  updated_at: string | null;
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
  lecturer: string | null;
  sessions: Session[];
};

export type Constraint = {
  id: number;
  name: string;
  constraint_type: string;
  hardness: "hard" | "soft";
  weight: number;
  lecturer?: string;
  lecturer_id?: number;
  target?: Record<string, unknown>;
  raw_text?: string;
  confirmed: boolean;
  active?: boolean;
};

export type Lecturer = {
  id: number;
  code: string | null;
  name: string;
  aliases: string[];
  confirmed: boolean;
  max_credits: number;
};

export type Seminar = {
  id: number;
  name: string;
  chair_name: string;
  members: string[];
  alternatives: Array<{ weekday: number; start_period: number; end_period: number }>;
  weight: number;
  hardness: "hard" | "soft";
};

export type ImportBatch = {
  id: number;
  created_at: string;
  source_files: string[];
  summary: Record<string, number>;
};

export type OptimizationRun = {
  id: number;
  created_at: string;
  status: string;
  score: number | null;
  summary: {
    classes?: number;
    lecturers?: number;
    hard_conflict_pairs?: number;
    merged_groups_confirmed?: boolean;
    seminar_slots?: Record<string, { weekday: number; start_period: number; end_period: number }>;
  };
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
