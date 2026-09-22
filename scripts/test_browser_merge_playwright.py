import os
import sys
import time
from playwright.sync_api import sync_playwright

OUTPUT_DIR = "/Users/mac/AI/Huce_timetable/test-results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Add apps/api to path
sys.path.insert(0, "/Users/mac/AI/Huce_timetable/huce-teaching-assignment-mvp/apps/api")
from app.db.session import SessionLocal
from app.models.entities import Semester, ClassSection

def set_active_semester(sem_id: int):
    db = SessionLocal()
    for s in db.query(Semester).all():
        s.is_active = (s.id == sem_id)
    db.commit()
    db.close()
    print(f"Set active semester to {sem_id}")

def test_merge_flow():
    # Set semester 8 as active for testing unassigned classes with merge recommendation
    set_active_semester(8)
    
    # Ensure 69CLC1 and 69CLC2 are unmerged before test
    db = SessionLocal()
    cls1 = db.query(ClassSection).filter(ClassSection.semester_id == 8, ClassSection.class_code == "69CLC1").first()
    cls2 = db.query(ClassSection).filter(ClassSection.semester_id == 8, ClassSection.class_code == "69CLC2").first()
    if cls1 and cls2:
        cls1.merged_group_id = None
        cls1.merged_confirmed = False
        cls1.merge_status = "single"
        cls2.merged_group_id = None
        cls2.merged_confirmed = False
        cls2.merge_status = "single"
        db.commit()
    db.close()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                headless=True,
                args=["--window-size=1600,1050", "--no-sandbox"]
            )
            context = browser.new_context(viewport={"width": 1600, "height": 1050})
            page = context.new_page()

            print("1. Navigating to http://localhost:3000...")
            page.goto("http://localhost:3000", wait_until="networkidle")
            time.sleep(2)

            # Navigate to Step 05: Phân công
            print("2. Clicking sidebar step 'Phân công'...")
            page.locator("nav button:has-text('Phân công')").first.click()
            time.sleep(2)

            # Switch to 'unassigned' tab
            print("3. Switching to 'Lớp chưa phân' tab...")
            unassigned_tab_btn = page.locator("button:has-text('Xem lớp chưa phân'), nav button:has-text('Lớp chưa phân')").first
            if unassigned_tab_btn.is_visible():
                unassigned_tab_btn.click()
                time.sleep(2)

            page.screenshot(path=f"{OUTPUT_DIR}/playwright_01_unassigned_panel.png")
            print(f"  Screenshot saved: {OUTPUT_DIR}/playwright_01_unassigned_panel.png")

            # Look for 69CLC1 in the table
            print("4. Finding 69CLC1 row and verifying merge button...")
            row_69 = page.locator("tr:has-text('69CLC1')").first
            assert row_69.is_visible(), "Row for 69CLC1 must be visible"

            # Check recommendation badge and quick merge button in the row
            quick_merge_btn = row_69.locator("button:has-text('Ghép gỡ nghẽn')")
            assert quick_merge_btn.is_visible(), "Quick merge button 'Ghép gỡ nghẽn' must be visible in the row"
            print("  Verified: Quick merge button is present in row!")

            # Click 'Phân công' to open candidate inspector drawer
            print("5. Clicking 'Phân công' to open Candidate Inspector drawer...")
            assign_btn = row_69.locator("button:has-text('Phân công')")
            assign_btn.click()
            time.sleep(2)

            page.screenshot(path=f"{OUTPUT_DIR}/playwright_02_inspector_drawer_with_merge_card.png")
            print(f"  Screenshot saved: {OUTPUT_DIR}/playwright_02_inspector_drawer_with_merge_card.png")

            # Verify the merge recommendation card in drawer
            print("6. Verifying Merge Recommendation Card in drawer...")
            merge_card = page.locator("aside div:has-text('Gợi ý ghép lớp cùng ca')").first
            assert merge_card.is_visible(), "Merge recommendation card must be visible in drawer"

            # Verify candidate badge '69CLC2'
            candidate_badge = page.locator("aside span:has-text('69CLC2')").first
            assert candidate_badge.is_visible(), "Candidate badge '69CLC2' must be visible in drawer"

            # Verify action button 'Ghép lớp để gỡ nghẽn'
            drawer_merge_btn = page.locator("aside button:has-text('Ghép lớp để gỡ nghẽn')").first
            assert drawer_merge_btn.is_visible(), "Action button 'Ghép lớp để gỡ nghẽn' must be visible in drawer"
            print("  Verified: Merge card, candidate badge and merge button are all visible in drawer!")

            # Click the merge button in drawer
            print("7. Clicking 'Ghép lớp để gỡ nghẽn' in drawer...")
            drawer_merge_btn.click()
            time.sleep(3)

            page.screenshot(path=f"{OUTPUT_DIR}/playwright_03_after_merge_success.png")
            print(f"  Screenshot saved: {OUTPUT_DIR}/playwright_03_after_merge_success.png")

            # Verify success notice or unmerge button in drawer
            unmerge_btn = page.locator("aside button:has-text('Hủy ghép')").first
            assert unmerge_btn.is_visible(), "'Hủy ghép' button must now be visible in drawer"
            print("  Verified: 'Hủy ghép' button is now visible in drawer!")

            # Check database state to confirm merged_group_id
            db = SessionLocal()
            cls1 = db.query(ClassSection).filter(ClassSection.semester_id == 8, ClassSection.class_code == "69CLC1").first()
            cls2 = db.query(ClassSection).filter(ClassSection.semester_id == 8, ClassSection.class_code == "69CLC2").first()
            print(f"8. Database verification: 69CLC1 group={cls1.merged_group_id}, confirmed={cls1.merged_confirmed}; 69CLC2 group={cls2.merged_group_id}, confirmed={cls2.merged_confirmed}")
            assert cls1.merged_group_id is not None and cls1.merged_group_id == cls2.merged_group_id
            assert cls1.merged_confirmed is True
            db.close()
            print("  Database confirmed: both classes have identical merged_group_id and merged_confirmed=True!")

            # Test Unmerge button
            print("9. Testing 'Hủy ghép' button in drawer...")
            unmerge_btn.click()
            time.sleep(3)

            page.screenshot(path=f"{OUTPUT_DIR}/playwright_04_after_unmerge.png")
            print(f"  Screenshot saved: {OUTPUT_DIR}/playwright_04_after_unmerge.png")

            # Check database state to confirm unmerged
            db = SessionLocal()
            cls1 = db.query(ClassSection).filter(ClassSection.semester_id == 8, ClassSection.class_code == "69CLC1").first()
            cls2 = db.query(ClassSection).filter(ClassSection.semester_id == 8, ClassSection.class_code == "69CLC2").first()
            print(f"10. Database unmerge verification: 69CLC1 group={cls1.merged_group_id}; 69CLC2 group={cls2.merged_group_id}")
            assert cls1.merged_group_id is None
            assert cls2.merged_group_id is None
            db.close()
            print("  Database confirmed: both classes successfully unmerged!")

            browser.close()
            print("🎉 ALL PLAYWRIGHT E2E TESTS PASSED!")
    finally:
        # Restore active semester to 12
        set_active_semester(12)

if __name__ == "__main__":
    test_merge_flow()
