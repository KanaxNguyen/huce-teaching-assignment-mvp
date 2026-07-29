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
  raw_text?: string;
  confirmed: boolean;
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

