# Danh sách lỗi · audit 26-10-2026

Code được audit: commit `b25a522` cộng các thay đổi chưa commit (24 file sửa, khoảng 50 file chưa track). Ảnh chụp trạng thái có sẵn:

- `evidence/git-status-before.txt`
- `evidence/pre-existing-uncommitted.patch`
- code hash `evidence/code-hash.txt`

Một số thay đổi chưa commit là của các phiên làm việc trước trong cùng dự án: precheck, kịch bản xử lý, sửa ghép lớp và override trong solver, export POST, tab kéo thả. Audit kiểm tra cả các thay đổi này. Audit không sửa mã sản phẩm.

Mức độ: **Cao** là sai phân công, vi phạm ràng buộc cứng, export sai, hoặc chặn bàn giao. **Trung bình** là sai nghiệp vụ hoặc dữ liệu có đường tái hiện. **Thấp** là độ bền, tài liệu, trải nghiệm.

Mọi lỗi "Đã xác nhận" có bước tái hiện chạy được. Kết luận dựa trên bộ kiểm tra độc lập (`harness/independent_checker.py`, chỉ dùng stdlib `sqlite3`, không import module sản phẩm) hoặc dựa trên phản hồi API.


> **Cập nhật sau sửa (BUG-01..04):** đã sửa trong `solver.py`, `exporters/excel.py`, `routes.py` (`POST /classes/merge`) và `schemas/api.py`. Hồi quy: `apps/api/tests/test_audit_regressions_20261026.py` (5 test, đều fail trên code cũ, pass trên code mới). Chạy lại probe và API audit trên code mới: bằng chứng ở `evidence/after-fix/`. Sau sửa: Vitest 27/27, lint, tsc PASS; Playwright 8/8 PASS; export nháp trên dữ liệu thật: 0 lệch giảng viên, 117 dòng lớp chưa phân ghi "Chưa phân công", 0 cặp trùng lịch (trước sửa: 7). Các lỗi BUG-05..13 và POL-01..05 chưa sửa.

---

## A. Lỗi đã xác nhận

### BUG-01 · Cao · `FORBIDDEN_ASSIGNMENT` theo học phần bị bỏ qua toàn bộ

- **Vị trí:** `apps/api/app/optimization/solver.py:533-544`
- **Tái hiện:** `harness/algo_audit.py::probe_forbidden_course_scope`, bằng chứng `evidence/algo-audit.json`, id `ALG-FORBIDDEN-COURSE`.
  - Hai lớp K1 (T2 tiết 1–3) và K2 (T3 tiết 1–3) cùng học phần C. A và B đều có năng lực.
  - A có ràng buộc cứng bận T2 tiết 1–3, và ràng buộc cứng `FORBIDDEN_ASSIGNMENT {course_id: C}`.
  - B bận cứng T3 tiết 1–3.
- **Expected:** A không dạy lớp nào của C; K2 chưa phân.
- **Actual:** `status=optimal`, K2 giao cho A, `invalid_constraints=[2]`. Bộ kiểm tra độc lập báo `HARD_FORBIDDEN_VIOLATED`.
- **Nguyên nhân:** chỉ cần một lớp của học phần không có biến `x[class, A]` (vì A đã bị loại khỏi lớp đó do bận) là `any((item, lecturer_id) not in x ...)` đánh dấu toàn bộ ràng buộc "invalid" và bỏ qua nó cho mọi lớp còn lại.
- **Hướng sửa:** với FORBIDDEN, chỉ áp `x == 0` cho các cặp đang tồn tại. Cặp không có biến đã tự thỏa ràng buộc. Không bao giờ coi FORBIDDEN là invalid vì thiếu biến.

### BUG-02 · Cao · Lớp ghép mới xác nhận một nửa làm mất ràng buộc chống trùng giờ

- **Vị trí:**
  - `solver.py:245-257` (`_is_merged` dùng `OR` trên `merge_status` của từng bên);
  - `solver.py:429-436` (nhóm ràng buộc lại yêu cầu từng lớp đã xác nhận);
  - `routes.py:1182-1213` (`POST /classes/merge` nhận `merged_group_id` có sẵn).
- **Tái hiện:**
  - Mức solver: `ALG-HALF-MERGE` (K1 confirmed, K2 candidate, cùng nhóm, cùng lịch, một giảng viên).
  - Mức API: `evidence/api/api-audit.json`, id `MERGE-PARTIAL-API-TIGHT`. Ba lớp giống nhau được gợi ý chung nhóm `MG-001`, chỉ một giảng viên có năng lực. Gọi `POST /classes/merge` với 2 lớp và `merged_group_id=MG-001`, rồi chạy với `confirm_merged=false`.
- **Expected:** lớp còn `candidate` (T2) không được xếp cùng giảng viên, cùng giờ với T0/T1.
- **Actual:** cả 3 lớp giao cho cùng một giảng viên. Bộ kiểm tra độc lập báo `DOUBLE_BOOKING` (T0–T2, T1–T2).
- **Phạm vi tái hiện:** UI hiện gọi merge không truyền group id, nên chưa thấy đường tái hiện qua UI. Mọi client API, script import, hoặc trạng thái DB cũ có nhóm xác nhận lẫn lộn đều kích hoạt được lỗi.
- **Hướng sửa:**
  - `_is_merged` dùng cùng điều kiện với nhóm ràng buộc: cả hai lớp đều confirmed.
  - `POST /classes/merge` từ chối group id còn thành viên chưa xác nhận, hoặc tách các thành viên đó ra.

### BUG-03 · Cao · Export nháp ghi giảng viên của file nguồn cho lớp chưa phân, gây trùng lịch trong file Excel

- **Vị trí:** `apps/api/app/exporters/excel.py:136-141`. Khi phương án hiện hành không có phân công, code lấy `section.assigned_lecturer` (giảng viên nhập từ file nguồn).
- **Tái hiện:**
  - Backend QA với file 03-08-2026.xls, chạy solver trên UI, rồi gọi `GET /exports/latest?mode=draft`.
  - Bằng chứng: `evidence/ui/export-draft-current.xlsx`, `evidence/ui/export-crosscheck.txt`.
- **Expected:** lớp chưa phân ghi "Chưa phân công", đúng như mô tả trên UI ("Các lớp chưa phân được ghi rõ nhãn Chưa phân công").
- **Actual:**
  - 115/115 lớp đã phân khớp phương án (0 lệch giảng viên, 0 lệch cờ khóa).
  - 8 dòng của các lớp chưa phân vẫn ghi tên, ví dụ 69CLC2 ghi Phạm Đức Thoan, 70KD3/70KD4 ghi Bùi Khánh Trình, 71CSQT ghi Nguyễn Bằng Giang.
  - Trong chính file export có **7 cặp trùng lịch** (cùng giảng viên, cùng ngày, tiết giao nhau), ví dụ Thoan dạy 69CLC1 và 69CLC2 cùng ca. Phương án solver có 0 trùng lịch.
- **Hướng sửa:** export chỉ phản ánh phương án hiện hành. Nếu cần giữ thông tin file nguồn, đưa vào cột riêng "Giảng viên trong file nguồn".

### BUG-04 · Cao · API mặc định tự xác nhận mọi gợi ý ghép lớp, và ghi trạng thái này vào DB

- **Vị trí:**
  - `apps/api/app/schemas/api.py:47` (`confirm_merged_suggestions: bool = True`);
  - `solver.py:812-816` (ghi `merged_confirmed=True` cho các nhóm).
- **Tái hiện:** `API-DEFAULT-MERGE`, `API-DEFAULT-MERGE-SIDE-EFFECT`. Gọi `POST /optimization/run` với body `{}`, sau đó K1, K2, K3 đều thành `confirmed`.
- **Expected:** gợi ý ghép cần người duyệt.
- **Actual:** chạy mặc định là xác nhận ngầm.
- **Liên quan deploy:** frontend ở commit HEAD (bản đã deploy) luôn gửi `true`. Bản chưa commit gửi `false` theo mặc định, nhưng backend vẫn mặc định `true`.
- **Hướng sửa:** đổi mặc định thành `false`, và bắt buộc gửi cờ này một cách tường minh.

### BUG-05 · Trung bình · Dòng V2 `PREFERRED_DAYS`/`AVOID_DAYS` không bao giờ xác nhận được

- **Vị trí:**
  - `routes.py:583-587` (target có `weekday`, hoặc `slots` khi có tiết);
  - `services/preference_validation.py:73-76` (bắt buộc `target.weekdays`).
- **Tái hiện:** TC13 (`evidence/fixtures-e2e/api-trace-TC13_preferred_days_compact.json`) và `PREF-DAYS-CONFIRM`. Kể cả sau khi chọn lại thứ ("T3"), PATCH vẫn trả 422 `MISSING_DAY`.
- **Ghi chú:** `scripts/compare_test_case.py` báo PASS cho TC13 chỉ vì nó bỏ qua bước duyệt.
- **Hướng sửa:** khi `day_scope` là một thứ, lưu cả `weekdays: [n]` cho loại DAY. Thêm hồi quy cho đường V2.

### BUG-06 · Trung bình · Dòng V2 `REQUIRED_ASSIGNMENT`/`FORBIDDEN_ASSIGNMENT` không có cách hoàn tất

- **Vị trí:** `schemas/api.py:87-104`. `PreferenceDraftUpdate` không có trường chọn lớp hoặc target.
- **Tái hiện:** TC12 (`INVALID_TARGET` / `MISSING_TARGET`) và `PREF-REQUIRED-CONFIRM`.
- **Ghi chú:** TC12 vẫn "đúng kết quả" chỉ vì solver tình cờ chọn đúng; ràng buộc REQUIRED/FORBIDDEN không hề được áp.
- **Cách tạm:** tạo bằng `POST /constraints`, nhưng đường này không kiểm tra target (xem BUG-07).
- **Hướng sửa:** thêm trường chọn TeachingGroup hoặc học phần trong màn duyệt, kèm kiểm tra cùng kỳ.

### BUG-07 · Trung bình · `POST /constraints` không kiểm tra target, và ràng buộc cứng sai bị bỏ qua âm thầm

- **Vị trí:** `routes.py:1352-1357`; `solver.py:537` (đưa vào `invalid_constraints` rồi `continue`).
- **Tái hiện:** `ISO-CONSTRAINT-TARGET`. Kỳ B tạo `REQUIRED_ASSIGNMENT` loại cứng trỏ tới lớp của kỳ A và nhận 200. Mặc định `confirmed=True`.
- **Expected:** 422.
- **Hậu quả:** ràng buộc cứng không có tác dụng. Chỉ precheck (chưa commit) mới cảnh báo `REQUIRED_ASSIGNMENT_IGNORED`.
- **Hướng sửa:** kiểm tra lớp thuộc kỳ, giảng viên tồn tại, và loại ràng buộc được hỗ trợ.

### BUG-08 · Trung bình · Chạy solver ghi đè danh mục năng lực

- **Vị trí:** `solver.py:144-152`.
- **Tái hiện:** `ALG-SOLVE-MUTATES-CAPS`. Năng lực `HYPOTHETICAL_ALL` (allowed=1, confirmed=1) thành `(0, 0)` sau một lần chạy, kể cả khi run bị chặn.
- **Expected:** solve chỉ đọc dữ liệu; nếu muốn bỏ loại dữ liệu này thì cần migration hoặc thao tác riêng có xác nhận.

### BUG-09 · Trung bình · `MAX_DAYS_PER_WEEK` tính theo thứ trong cả kỳ, không theo tuần lịch

- **Vị trí:** `solver.py:509-516`.
- **Tái hiện:** `ALG-MAX-DAYS-WEEK`. Hai lớp: T2 tuần 1–7 và T3 tuần 8–15. Giảng viên có ràng buộc cứng tối đa 1 ngày/tuần.
- **Expected:** mỗi tuần chỉ 1 ngày dạy, nên giao được cả hai lớp.
- **Actual:** 1 lớp bị bỏ trống.

### BUG-10 · Trung bình · Import nguyện vọng tự tạo giảng viên "đã xác nhận" từ bất kỳ mã lạ nào

- **Vị trí:** `services/importer.py:133-151` (`confirmed=bool(code)`).
- **Tái hiện:** `PREF-AUTO-LECTURER`, `PREF-UNRESOLVED`. Mã `99999` không có trong danh mục tạo ra giảng viên ACTIVE, `confirmed=True`. Nguyện vọng của mã đó thành "đã resolve", không còn ở trạng thái NEEDS_REVIEW.
- **Rủi ro:** gõ nhầm mã (00178 thay vì 00187) tạo ra giảng viên ảo; nguyện vọng của người thật bị mất mà không có cảnh báo.
- **Ghi chú:** mã có thật trong file thì có thể là chính sách đã chọn. Cần chủ dự án quyết định.

### BUG-11 · Thấp · Kết quả không tái lập giữa các lần chạy

- **Bằng chứng:** `DETERMINISM-3RUNS` cho 3 phương án khác nhau với cùng objective. Bài toán 600 lớp cho `optimal` 10.000 ở lần 1, nhưng `feasible` 20.000 ở lần 2–3 với giới hạn 30 giây.
- **Nguyên nhân:** 8 worker, không cố định thứ tự tìm kiếm, không có gợi ý khởi đầu từ phương án cũ.
- **Hậu quả:** mỗi lần chạy lại xáo các phân công chưa khóa.

### BUG-12 · Thấp · Export sao chép cả quyền read-only của file mẫu

- **Vị trí:** `excel.py:327` (`shutil.copy2`).
- **Tái hiện:** `evidence/pytest-fixture-rerun-readonly-copy.log`. Fixture mẫu đặt read-only gây `PermissionError` khi ghi bản copy.
- **Mức ảnh hưởng thực tế:** thấp, vì file upload do app ghi thì có quyền ghi.

### BUG-13 · Thấp · Mã lỗi cách ly kỳ không nhất quán

`GET /classes/{id}/candidate-analysis` và `POST /classes/unmerge` với lớp của kỳ khác trả `200 []` hoặc `unmerged: 0`. Không lộ dữ liệu, nhưng các endpoint cùng nhóm trả 404/422. Xem `evidence/api/api-audit.json`.

---

## B. Vấn đề cần quyết định chính sách hoặc phê duyệt (không tự sửa)

### POL-01 · Hàm mục tiêu là tổng có trọng số, không phải thứ tự ưu tiên tuyệt đối

- `ALG-SPREAD-INVERSION`: một lớp 150 tín chỉ bị bỏ trống, vì giao lớp đó làm chênh lệch tải tăng 1.500 × 1.000 = 1,5 triệu, lớn hơn phạt 1 triệu cho một lớp chưa phân.
- Với dữ liệu thật (2–4 tín chỉ/lớp, độ lệch quan sát 340.000–400.000), **không** thấy đảo ưu tiên.
- `ALG-PRIORITY`: phạt mềm lớn nhất đo được là 19.600, nhỏ hơn nhiều so với 1 triệu.
- Biến tải có miền 0..10.000 (tức 1.000 tín chỉ), nên hiện chưa chạm.
- Theo AGENTS.md, thay đổi hàm mục tiêu cần chủ dự án phê duyệt.

### POL-02 · Cầu nối năng lực theo tên môn

- **Vị trí:** `solver.py:200-243`.
- `ALG-NAME-BRIDGE`: năng lực của học phần `MATH-1` "Đồ án tốt nghiệp" được dùng cho `ARCH-9` cùng tên, lấy từ toàn bộ bảng course, không lọc theo bộ môn.
- Đây là chính sách viết trong code, chưa có quyết định được ghi lại.

### POL-03 · Trạng thái `CONFIRMED` trong cột "Trạng thái" của workbook được nhận thẳng

Với cặp dữ liệu thật, 54 bản nháp đã ở trạng thái CONFIRMED do file khai báo, không phải do người duyệt. Apply hàng loạt sẽ đưa chúng thành ràng buộc: số lớp được giao giảm 132 → 127, vì có ràng buộc cứng.

### POL-04 · Capability là danh mục toàn cục

`PUT /lecturers/{id}/capabilities` thay đổi cặp giảng viên–học phần cho mọi kỳ. Đây là vấn đề đã ghi nhận trong review 05-10, vẫn chưa có quyết định.

### POL-05 · BFF chuyển tiếp mọi đường dẫn tới backend kèm token nội bộ

Không có lớp đăng nhập người dùng. Ai mở được URL frontend đều gọi được mọi API ghi, kể cả xoá. `ENVIRONMENT` mặc định là `development` (`config.py:10`), và môi trường này tắt kiểm tra token (`main.py:47-50`).

---

## C. Lỗi test và công cụ QA (không phải lỗi sản phẩm)

| ID | Vị trí | Vấn đề |
|---|---|---|
| TQ-01 | `qa_auditor.py`, `re_audit.py` (gốc repo) | Gán cứng `PASS` cho hàng chục mục (`results['HARD-01'] = ('PASS','Enforced')`, `print("... PASS")`). Không phải bằng chứng. Bản sao ở `evidence/old-runners/`. |
| TQ-02 | `run_final.py` | Tự tạo giảng viên từ alias chưa resolve và đặt mọi nguyện vọng thành CONFIRMED (trái quy tắc 3 của AGENTS.md), sau đó báo "PASS WITH WARNINGS". |
| TQ-03 | `scripts/compare_test_case.py` | Gọi thẳng parser và solver, bỏ qua API và bước duyệt, tự đưa mọi bản nháp vào ràng buộc. Báo 17/17 PASS, che mất BUG-05 và BUG-06. |
| TQ-04 | `apps/api/tests/test_regression.py` | Phụ thuộc DB phát triển có thể thay đổi (`storage/database/huce_test.db`: kỳ 2, lớp id 368…). Fail khi không có DB đó. |
| TQ-05 | `test_phase5_real_data.py`, `test_template_multirow.py`, một test trong `test_qa_full_audit_regressions.py` | Cần workbook nằm ngoài repo (`parents[4]`, `storage/uploads`). Fail ở bản sao sạch (7 FAIL, tất cả do thiếu fixture). |
| TQ-06 | `tests/e2e/*.spec.ts` | Chỉ có 2 smoke test (49 dòng), không kiểm tra export hay lịch. |
| TQ-07 | `output/qa-fixes/*.spec.ts` | Gắn cứng cổng 3018 và DB đã seed riêng. Không chạy lại trong audit này. |

## D. Tài liệu

- `docs/staging-deployment.md` ghi migration head `0004_v11_merge_status`, thực tế là `0009_department_agnostic_capabilities`.
- `docs/architecture.md` thiếu thành phần phạt "giảng viên 0 lớp" (đã nêu trong review 05-10, chưa sửa).
- Tiêu đề workbook thật ghi "Tổng số lớp: 286", nhưng 286 là số dòng buổi học; bộ đọc độc lập đếm được 158 lớp.
