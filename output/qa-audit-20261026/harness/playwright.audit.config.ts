import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "../../tests/audit",
  timeout: 180_000,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: "/Users/mac/AI/Huce_timetable/huce-teaching-assignment-mvp/output/qa-audit-20261026/evidence/ui/playwright-results.json" }], ["junit", { outputFile: "/Users/mac/AI/Huce_timetable/huce-teaching-assignment-mvp/output/qa-audit-20261026/evidence/ui/playwright-junit.xml" }]],
  outputDir: "/private/tmp/huce-audit-20261026/ui/pw-output",
  use: { channel: "chrome", baseURL: "http://127.0.0.1:3026", trace: "retain-on-failure", screenshot: "only-on-failure", acceptDownloads: true },
});
