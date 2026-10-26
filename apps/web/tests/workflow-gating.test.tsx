import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SemesterWorkflowApp } from "../src/features/dashboard/semester-workflow-app";
import { api } from "../src/services/api";

vi.mock("../src/services/api", () => ({
  api: {
    semesters: vi.fn(), dashboard: vi.fn(), classes: vi.fn(), constraints: vi.fn(), lecturers: vi.fn(),
    conflicts: vi.fn(), latestTemplate: vi.fn(), preferenceDrafts: vi.fn(), problems: vi.fn(), capabilityReadiness: vi.fn(),
    sources: vi.fn(), lecturerReview: vi.fn(), exportLecturersUrl: vi.fn(() => "#"),
  },
}));

afterEach(cleanup);

beforeEach(() => {
  vi.mocked(api.semesters).mockResolvedValue([
    { id: 1, name: "HK1", department_name: "Toán", head_name: "A", start_date: "2026-09-07", end_date: "2027-01-24", status: "draft", is_active: true },
  ] as never);
  vi.mocked(api.dashboard).mockResolvedValue({
    classes: 0, locked_classes: 0, unassigned_classes: 0, merged_suggestions: 0, lecturers: 0,
    validation_errors: 0, optimization_status: "not_run", optimization_score: null,
  });
  for (const key of ["classes", "constraints", "lecturers", "conflicts", "preferenceDrafts", "problems"] as const) {
    vi.mocked(api[key] as never as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  }
  vi.mocked(api.latestTemplate).mockResolvedValue(null as never);
  vi.mocked(api.capabilityReadiness).mockRejectedValue(new Error("down"));
  vi.mocked(api.sources).mockResolvedValue({ sources: [], issues: [] } as never);
  vi.mocked(api.lecturerReview).mockResolvedValue({ semester_id: 1, semester_name: "HK1", total_lecturers: 0, ready_count: 0, needs_review_count: 0, blockers_count: 0, blockers: [], items: [] });
});

it("explains the missing prerequisite instead of opening the assignment step with no classes", async () => {
  render(<SemesterWorkflowApp />);
  await waitFor(() => expect(screen.queryByText(/Đang đồng bộ/)).not.toBeInTheDocument());

  fireEvent.click(screen.getByRole("button", { name: /Bước 5: Phân công/ }));
  expect(screen.getByText("Chưa thể mở bước này")).toBeInTheDocument();
  expect(screen.getByText(/Chưa có lớp học phần nào/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Về bước Dữ liệu đầu vào/ }));
  expect(screen.queryByText("Chưa thể mở bước này")).not.toBeInTheDocument();
});

it("shows step state from data rather than from position in the list", async () => {
  render(<SemesterWorkflowApp />);
  await waitFor(() => expect(screen.queryByText(/Đang đồng bộ/)).not.toBeInTheDocument());
  expect(screen.getByRole("button", { name: /Bước 1: Kỳ học — đã hoàn tất/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Bước 6: Xuất kết quả — chưa làm/ })).toBeInTheDocument();
});

it("does not report an error on first run when no semester exists yet", async () => {
  vi.mocked(api.semesters).mockResolvedValue([]);
  vi.mocked(api.dashboard).mockClear();
  render(<SemesterWorkflowApp />);
  await waitFor(() => expect(screen.queryByText(/Đang đồng bộ/)).not.toBeInTheDocument());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(api.dashboard).not.toHaveBeenCalled();
});
