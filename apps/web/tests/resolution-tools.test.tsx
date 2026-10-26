import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PrecheckPanel, ScenarioDialog } from "../src/features/dashboard/resolution-tools";
import { api } from "../src/services/api";

vi.mock("../src/services/api", () => ({ api: { scenarios: vi.fn(), applyScenario: vi.fn() } }));
afterEach(cleanup);

const ladder = [1, 2, 3, 4, 5].map((level) => ({ level, approver: `Cấp ${level}`, label: "", description: "" }));
const consentOption = { lecturer_id: 7, lecturer_name: "GV A", lecturer_code: "A", department: null, load: { classes: 3, credits: 9 }, bends: ["đăng ký bận cứng"], moves: [], note: null };

it("requires a named approver and a reason before bending a rule", async () => {
  vi.mocked(api.scenarios).mockResolvedValue({
    class: { id: 1, class_code: "L1", course_code: "C", course_name: "Giải tích", credits: 3, current_lecturer_id: null, sessions: [] },
    scenarios: [
      { key: "consent", level: 2, authority: { approver: "Trưởng bộ môn + giảng viên đồng ý", label: "", description: "" }, title: "Xin giảng viên dạy ngoài nguyện vọng", summary: "", options: [consentOption], available: true },
      { key: "escalate", level: 5, authority: { approver: "Phòng Đào tạo", label: "", description: "" }, title: "Chuyển Phòng Đào tạo xử lý", summary: "", options: [], available: true },
    ],
    recommended: "consent", why_blocked: [], authority_ladder: ladder,
  });
  vi.mocked(api.applyScenario).mockResolvedValue({ applied: true });
  const onApplied = vi.fn();
  render(<ScenarioDialog classId={1} semesterId={9} focusLecturerId={7} onClose={vi.fn()} onApplied={onApplied} onMerge={vi.fn()} />);
  const apply = await screen.findByRole("button", { name: "Áp dụng" });
  expect(apply).toBeDisabled();
  fireEvent.change(screen.getByPlaceholderText("Họ tên người phê duyệt"), { target: { value: "TBM Toán" } });
  fireEvent.change(screen.getByPlaceholderText(/GV đã đồng ý/), { target: { value: "GV đồng ý qua email" } });
  fireEvent.click(apply);
  await waitFor(() => expect(api.applyScenario).toHaveBeenCalledWith(1, 9, { scenario: "consent", lecturer_id: 7, approver: "TBM Toán", reason: "GV đồng ý qua email" }));
  expect(onApplied).toHaveBeenCalled();
});

it("states the proven minimum of unassigned classes and marks short slots", () => {
  render(<PrecheckPanel loading={false} onRefresh={vi.fn()} onOpenClass={vi.fn()} report={{
    status: "warning", can_run: true, estimated_min_unassigned: 2, shortages: [], stats: {},
    items: [{ code: "SLOT_SHORTAGE", severity: "warning", title: "Thứ 3 tiết 4–6: thiếu 1 giảng viên", detail: "", class_ids: [1], class_codes: ["L1"], suggestion: null }],
    heatmap: [{ weekday: 3, block: 1, demand: 3, capable: 2, deficit: 1 }],
  }} />);
  expect(screen.getByText(/ít nhất 2 lớp không xếp được/)).toBeInTheDocument();
  expect(screen.getByTitle(/T3 Ca 2: 3 lớp cùng lúc, 2 giảng viên đủ điều kiện, thiếu 1/)).toHaveTextContent("−1");
});
