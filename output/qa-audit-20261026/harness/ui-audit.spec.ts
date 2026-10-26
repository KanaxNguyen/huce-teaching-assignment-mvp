/* Browser audit against the QA stack (frontend :3026 via BFF -> backend :8026, DB /private/tmp/huce-audit-20261026/ui/ui.db).
   Seed: one semester (id 1, start 2026-08-03) with the 03-08-2026 real schedule activated; no run yet. */
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

const API = "http://127.0.0.1:8026/api/v1";
const SHOTS = process.env.AUDIT_SHOTS ?? "/tmp";
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
const alerts = (page: Page) => page.locator("[role=alert]:not(#__next-route-announcer__)").filter({ hasText: /\S/ });
const json = async (path: string) => (await fetch(API + path)).json();

test.describe.serial("UI audit", () => {
  test("U01 step navigation renders and workspace is reachable", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Các bước lập lịch" })).toBeVisible();
    await page.getByRole("button", { name: /Phân công/ }).first().click();
    await expect(page.getByRole("button", { name: /Chạy phân công|Chạy lại phân công/ })).toBeVisible();
    await shot(page, "U01-workspace-before-run");
  });

  test("U02 double click on run creates exactly one run and UI matches API", async ({ page }) => {
    const before = (await json("/optimization/runs?semester_id=1")).length;
    await page.goto("/");
    await page.getByRole("button", { name: /Phân công/ }).first().click();
    const run = page.getByRole("button", { name: /Chạy phân công|Chạy lại phân công/ });
    await run.dblclick();
    await expect(page.getByRole("button", { name: /Chạy lại phân công/ })).toBeVisible({ timeout: 120_000 });
    const after = (await json("/optimization/runs?semester_id=1")).length;
    expect(after - before, "runs created by a double click").toBe(1);
    const unassigned = (await json("/classes/unassigned?semester_id=1")).length;
    await page.getByRole("button", { name: /Lớp chưa phân/ }).click();
    await expect(page.locator("body")).toContainText(String(unassigned));
    await shot(page, "U02-after-run");
  });

  test("U03 every workspace tab renders without an error banner", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Phân công/ }).first().click();
    const tabs = ["Tổng quan", "Lớp chưa phân", "Kéo thả phân công", "Bảng phân công", "Lịch tuần", "Tải giảng dạy", "Ràng buộc", "Seminar nhóm", "Lớp ghép", "Vấn đề", "Kiểm tra dữ liệu", "Lịch sử chạy", "Xuất file"];
    const nav = page.getByRole("navigation", { name: "Không gian phân công" });
    for (const tab of tabs) {
      await nav.getByRole("button", { name: tab }).click();
      await page.waitForTimeout(400);
      await expect(alerts(page), `error banner on tab ${tab}`).toHaveCount(0);
      await shot(page, `U03-tab-${tab.replace(/\s+/g, "-")}`);
    }
  });

  test("U04 manual change made through the API is visible after reload", async ({ page }) => {
    const assignments = await json("/assignments?semester_id=1");
    const target = assignments[0];
    const candidates = await json(`/classes/${target.class_id}/candidates?semester_id=1`);
    const other = (Array.isArray(candidates) ? candidates : candidates.candidates ?? []).find((c: { lecturer_id: number; valid?: boolean; lecturer?: string; name?: string }) => (c.valid ?? true) && (c.lecturer ?? c.name) !== target.lecturer);
    test.skip(!other, "no alternative valid lecturer for the first class");
    const r = await fetch(`${API}/classes/${target.class_id}/assignment?semester_id=1`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ lecturer_id: other.lecturer_id, lock: true }) });
    expect(r.status).toBe(200);
    const now = (await json("/assignments?semester_id=1")).find((a: { class_id: number }) => a.class_id === target.class_id);
    await page.goto("/");
    await page.getByRole("button", { name: /Phân công/ }).first().click();
    await page.getByRole("navigation", { name: "Không gian phân công" }).getByRole("button", { name: "Bảng phân công" }).click();
    await page.getByRole("searchbox", { name: "Tìm trong bảng phân công" }).fill(target.class_code);
    const row = page.locator("tr", { hasText: target.class_code }).first();
    await expect(row).toContainText(now.lecturer);
    await expect(row.getByLabel("Đã khóa")).toBeVisible();
    await shot(page, "U04-manual-lock-visible");
  });

  test("U05 draft export downloads a real workbook", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Phân công/ }).first().click();
    await page.getByRole("navigation", { name: "Không gian phân công" }).getByRole("button", { name: "Xuất file" }).click();
    const [download] = await Promise.all([page.waitForEvent("download", { timeout: 60_000 }), page.getByText("Xuất Draft Excel").first().click()]);
    const path = `${SHOTS}/U05-${download.suggestedFilename()}`;
    await download.saveAs(path);
    const head = fs.readFileSync(path).subarray(0, 2).toString();
    expect(head).toBe("PK");
  });

  test("U06 backend unavailable shows an error, never a success notice", async ({ page }) => {
    await page.route("**/api/backend/**", (route) => route.fulfill({ status: 503, body: JSON.stringify({ detail: "Backend unavailable" }), contentType: "application/json" }));
    await page.goto("/");
    await expect(alerts(page).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("status")).toHaveCount(0);
    await shot(page, "U06-backend-down");
  });

  test("U07 switching semester while a run is in flight does not show the old semester's result", async ({ page }) => {
    const created = await fetch(`${API}/semesters`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "QA UI empty", department_name: "Toán học", head_name: "QA", start_date: "2026-08-03", end_date: "2027-01-31" }) });
    const second = (await created.json()).id;
    // Creating a semester makes it active on the server; make semester 1 active again for the UI.
    await fetch(`${API}/semesters/1/activate`, { method: "POST" });
    await page.goto("/");
    await page.getByRole("button", { name: /Phân công/ }).first().click();
    await page.getByRole("button", { name: /Chạy lại phân công|Chạy phân công/ }).click();
    await page.getByRole("button", { name: /Kỳ học/ }).first().click();
    const select = page.getByLabel("Chọn kỳ học");
    if (await select.isDisabled()) {
      test.info().annotations.push({ type: "observed", description: "semester selector disabled while a run is busy (switch prevented)" });
      await shot(page, "U07-switch-disabled");
      return;
    }
    await select.selectOption(String(second));
    await page.waitForTimeout(15_000);
    await page.getByRole("button", { name: /Phân công/ }).first().click();
    await expect(page.locator("body")).not.toContainText("Chạy lại phân công");
    await shot(page, "U07-after-switch");
  });

  test("U08 phone width has no horizontal page scroll", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await shot(page, "U08-mobile");
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
