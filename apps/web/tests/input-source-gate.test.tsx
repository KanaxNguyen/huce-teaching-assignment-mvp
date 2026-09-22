import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { LecturerHitlSection } from "../src/features/dashboard/semester-workflow-app";
import { api } from "../src/services/api";

vi.mock("../src/services/api", () => ({
  api: { lecturerReview: vi.fn(), exportLecturersUrl: vi.fn(() => "#") },
}));

afterEach(cleanup);

beforeEach(() => {
  vi.mocked(api.lecturerReview).mockResolvedValue({
    semester_id: 1,
    semester_name: "HK1",
    total_lecturers: 0,
    ready_count: 0,
    needs_review_count: 0,
    blockers_count: 0,
    blockers: [],
    items: [],
  });
});

it("blocks Preference Review until both staged sources are active", async () => {
  const onNext = vi.fn();
  const { rerender } = render(<LecturerHitlSection semesterId={1} onNext={onNext} sourcesActive={false} />);

  const next = screen.getByRole("button", { name: "Chuyển sang duyệt nguyện vọng" });
  expect(next).toBeDisabled();
  expect(screen.getByText(/Kích hoạt cả nguồn Lịch học và Nguyện vọng/)).toBeInTheDocument();

  rerender(<LecturerHitlSection semesterId={1} onNext={onNext} sourcesActive />);
  expect(screen.getByRole("button", { name: "Chuyển sang duyệt nguyện vọng" })).toBeEnabled();
});
