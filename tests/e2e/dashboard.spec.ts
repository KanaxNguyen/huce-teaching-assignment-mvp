import { expect, test } from "@playwright/test";

test("renders the HUCE dashboard and navigates to input data", async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/dashboard")) {
      return route.fulfill({ json: { classes: 1, locked_classes: 0, unassigned_classes: 1, merged_suggestions: 0, lecturers: 2, validation_errors: 0, optimization_status: "not_run", optimization_score: null } });
    }
    if (path.endsWith("/settings")) {
      return route.fulfill({ json: { academic_year: "2026-2027", semester: 1, semester_start: "2026-08-03", semester_end: "2026-12-18", institution: "HUCE", department: "Bộ môn Toán học", calendar_name: "TKB Bộ môn Toán HUCE", timezone_name: "Asia/Ho_Chi_Minh", primary_lecturer: null, updated_at: null } });
    }
    if (path.endsWith("/imports/latest")) return route.fulfill({ json: { batch: null } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  await expect(page.getByText("Một nơi để biến dữ liệu Excel")).toBeVisible();

  const themeToggle = page.getByRole("button", { name: "Chuyển sang giao diện tối" });
  await themeToggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  await page.getByRole("button", { name: "Dữ liệu đầu vào" }).click();
  await expect(page.getByText("Chưa chọn file lịch học")).toBeVisible();
});
