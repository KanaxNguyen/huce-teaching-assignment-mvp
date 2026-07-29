import { expect, test } from "@playwright/test";

test("renders the HUCE dashboard and navigates to input data", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/api/v1/**", async (route) => {
    const url = route.request().url();
    if (url.endsWith("/dashboard")) {
      return route.fulfill({ json: { classes: 1, locked_classes: 0, unassigned_classes: 1, merged_suggestions: 0, lecturers: 2, validation_errors: 0, optimization_status: "not_run", optimization_score: null } });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  await expect(page.getByText("Một nơi để biến dữ liệu Excel")).toBeVisible();
  await page.getByRole("button", { name: "Dữ liệu đầu vào" }).click();
  await expect(page.getByText("Thả file Excel vào đây")).toBeVisible();
});

