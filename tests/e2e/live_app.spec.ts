import { expect, test } from "@playwright/test";

test("Live App: loads homepage, checks brand title, wizard tabs, and input data page", async ({ page }) => {
  // Navigate to live Next.js app
  await page.goto("http://127.0.0.1:3000/");
  
  // Verify main branding and heading
  await expect(page.locator("body")).toContainText("Thiết lập kỳ học");
  
  // Take screenshot of step 1
  await page.screenshot({ path: "/Users/mac/AI/Huce_timetable/screenshot_step1_setup.png", fullPage: true });

  // Navigate to Step 2: Dữ liệu đầu vào
  const step2Btn = page.getByRole("button", { name: "Dữ liệu đầu vào" });
  if (await step2Btn.isVisible()) {
    await step2Btn.click();
    await expect(page.locator("body")).toContainText("Nhập dữ liệu");
    await page.screenshot({ path: "/Users/mac/AI/Huce_timetable/screenshot_step2_inputs.png", fullPage: true });
  }

  // Navigate to Step 3: Rà soát nguyện vọng
  const step3Btn = page.getByRole("button", { name: "Rà soát nguyện vọng" });
  if (await step3Btn.isVisible()) {
    await step3Btn.click();
    await page.screenshot({ path: "/Users/mac/AI/Huce_timetable/screenshot_step3_preferences.png", fullPage: true });
  }

  // Navigate to Step 4: Xếp lịch & Tối ưu
  const step4Btn = page.getByRole("button", { name: /Xếp lịch|Tối ưu/ });
  if (await step4Btn.isVisible()) {
    await step4Btn.click();
    await page.screenshot({ path: "/Users/mac/AI/Huce_timetable/screenshot_step4_solver.png", fullPage: true });
  }
});
