# Tóm tắt audit HUCE Teaching Assignment · 26-10-2026

**Kết luận: chưa đủ điều kiện bàn giao.** Thuật toán đúng trong phạm vi đã kiểm bằng oracle, và nghiệm trên dữ liệu thật hợp lệ. Tuy vậy, audit xác nhận:

- 2 đường dẫn tới vi phạm ràng buộc cứng (BUG-01, BUG-02);
- 1 lỗi export làm file Excel chứa trùng lịch (BUG-03);
- 1 mặc định API tự xác nhận ghép lớp (BUG-04);
- staging không có backend hoạt động.

## Phạm vi và cách làm

Đối tượng audit:
- commit `b25a522` cộng thay đổi chưa commit. Ảnh chụp trạng thái ở `evidence/git-status-before.txt` và `evidence/pre-existing-uncommitted.patch`. Một phần thay đổi là của các phiên làm việc trước (precheck, kịch bản thẩm quyền, kéo thả, 2 sửa solver).
- Audit không sửa mã sản phẩm.

Môi trường:
- Bản sao `/private/tmp/huce-audit-20261026/src`, DB SQLite mới cho từng harness.
- Workbook gốc chỉ đọc; SHA-256 ở `DATASET_MANIFEST.json`.

Bằng chứng độc lập:
- `harness/independent_checker.py` (chỉ stdlib `sqlite3`, không import module sản phẩm);
- oracle vét cạn;
- reader openpyxl/xlrd;
- Chrome thật qua Playwright.

## Kết quả chính

| Nhóm | Kết quả |
|---|---|
| Pytest backend | 335 pass, 7 fail, 1 skip. Cả 7 fail do thiếu fixture ngoài repo; cấp fixture bản sao thì 12/12 pass. PostgreSQL: BLOCKED. |
| Frontend | Vitest 27/27, lint, typecheck và build PASS. Lockfile pnpm cài được với `--frozen-lockfile`. |
| Oracle vét cạn | **150/150** instance: objective CP-SAT bằng tối ưu của oracle, 0 vi phạm. |
| Metamorphic | 5/5 PASS: thứ tự dòng, tuần không giao nhau, ghép chưa xác nhận, giữ khóa, đơn điệu khi thêm năng lực. |
| TC01–TC17 qua API thật | 15 PASS; TC16/TC17 phân công đúng (export trống bị từ chối có chủ đích). TC12/TC13 "đúng" nhưng ràng buộc của chúng **không áp được** qua bước duyệt (BUG-05, BUG-06). |
| Audit API | 45 kiểm tra: 37 PASS, 8 FAIL. Import, nguồn và token stale, cách ly kỳ, chuỗi manual → khóa → chạy lại → mở khóa, chặn bản final, export chi tiết và ma trận đều PASS. |
| Trình duyệt | 8/8 PASS: double-click chỉ tạo 1 run, 13 tab không lỗi, sửa và khóa hiển thị sau reload, tải file nháp, backend sập hiện lỗi, khóa chọn kỳ khi đang chạy, không cuộn ngang ở 375px. |
| Restart backend | 5/5 snapshot API giống hệt. |
| Thực nghiệm (`EXPERIMENT_RESULTS.csv`) | 33 lần chạy, **0 vi phạm cứng**. 03-08-2026.xls: 115/176 lớp `optimal`, khớp audit 10-10. 85 khóa giữ nguyên. Cặp file thật: 132/158, còn 127/158 sau khi áp 54 nguyện vọng file đã đánh CONFIRMED. 30 lớp cùng ca / 10 GV: đúng cận 10. Bài toán 600 lớp chạm giới hạn 30 giây ở 2/3 lần. |

## Lỗi nghiêm trọng nhất

Chi tiết ở `BUGS.md`.

1. **BUG-01: cấm theo học phần bị bỏ qua.** Một `FORBIDDEN_ASSIGNMENT {course_id}` cứng mất hiệu lực hoàn toàn khi giảng viên đã bị loại khỏi *một* lớp của học phần. Solver vẫn giao các lớp còn lại cho chính giảng viên bị cấm.
2. **BUG-02: lớp ghép xác nhận một nửa.** Chỉ cần một bên `confirmed` là cặp lớp được miễn kiểm tra trùng giờ, nhưng không bị ràng cùng giảng viên. Kết quả là trùng lịch thật. Tái hiện qua API: `POST /classes/merge` với `merged_group_id` có sẵn.
3. **BUG-03: export nháp lấy lại giảng viên từ file nguồn.** Lớp chưa phân trong phương án hiện hành vẫn ghi tên giảng viên của file nguồn. Trên dữ liệu thật, file xuất ra có **7 cặp trùng lịch**, trong khi phương án có 0.
4. **BUG-04: API tự xác nhận ghép lớp.** Mặc định `confirm_merged_suggestions=True` xác nhận ngầm mọi gợi ý ghép và ghi vào DB. Frontend ở HEAD (bản đã deploy) luôn gửi `true`.
5. **Triển khai:** backend staging trả 404 "Application not found" (Railway). Mọi thay đổi local chưa có trên remote.

Mức trung bình:
- **BUG-05/06:** nguyện vọng V2 dạng ngày và dạng chỉ định/cấm lớp không duyệt được.
- **BUG-07:** `POST /constraints` không kiểm tra target.
- **BUG-08:** solve ghi đè năng lực.
- **BUG-09:** `MAX_DAYS_PER_WEEK` tính sai đơn vị.
- **BUG-10:** mã giảng viên lạ tự thành giảng viên đã xác nhận.

Công cụ QA cũ: `qa_auditor.py` và `re_audit.py` gán cứng PASS; `compare_test_case.py` bỏ qua bước duyệt nên báo 17/17 PASS và che mất BUG-05/06.

## Trả lời các câu hỏi

**Thuật toán đúng trong phạm vi nào?**
- Đúng với: năng lực trực tiếp, tham gia kỳ, bận và ưu tiên (cứng và mềm), không trùng giờ theo ngày thực tế, tuần so le, khóa, ghép đã xác nhận đầy đủ, và hàm mục tiêu 4 thành phần. Kiểm bằng oracle 150 instance, 17 fixture và 33 lần chạy thực nghiệm.
- Thứ tự ưu tiên objective đúng **trong miền dữ liệu hiện có** (2–4 tín chỉ/lớp, trọng số 0..1), nhưng không bảo đảm về mặt toán học (POL-01).
- Các loại ràng buộc chưa được oracle bao phủ: seminar nhiều slot, giới hạn buổi/ngày, khối liên tiếp, buổi sáng trống, lịch gọn, tải thấp. Chúng chỉ được kiểm bằng pytest có sẵn, tức là gọi lại code sản phẩm.

**Có phản ví dụ hoặc lỗi đã xác nhận?**
- Có. Hai phản ví dụ vi phạm cứng (BUG-01, BUG-02), một sai nghiệp vụ (BUG-09), một đảo ưu tiên ở dữ liệu cực trị (POL-01), và một tác dụng phụ ghi DB (BUG-08).
- Mỗi phản ví dụ có fixture tối thiểu trong `harness/algo_audit.py`.

**Chức năng nào chưa ổn?**
- Export nháp (BUG-03).
- Mặc định ghép lớp của API (BUG-04).
- Duyệt nguyện vọng V2 dạng ngày và dạng lớp (BUG-05/06).
- Tạo ràng buộc thủ công (BUG-07).
- Import tạo giảng viên (BUG-10).
- Staging.
- Tính tái lập giữa các lần chạy (BUG-11).
- Chưa có xác thực người dùng (POL-05).

**Đủ điều kiện bàn giao chưa?**
- **Chưa.** Có thể bàn giao khi đáp ứng đủ các điều kiện sau:
  1. Sửa BUG-01..04 và chuyển các probe tương ứng (`ALG-FORBIDDEN-COURSE`, `ALG-HALF-MERGE`, `API-DEFAULT-MERGE*`, `MERGE-PARTIAL-API-TIGHT`, kiểm tra export) thành hồi quy và để chúng PASS, **không** đổi expected.
  2. Sửa BUG-05/06 để TC12/TC13 PASS qua bước duyệt thật.
  3. Commit thay đổi local, dựng lại backend staging (PostgreSQL, S3, migration `0009`) và chạy smoke staging gồm cả restart.
  4. Chủ dự án quyết định POL-01..05: ưu tiên objective, cầu nối tên môn, trạng thái CONFIRMED từ file, năng lực toàn cục, xác thực.
- Không cần dữ liệu 308 lớp để bàn giao. Nhưng **không** được dùng số 115/176 hay 132/158 thay cho bảng 3 của bài viết.

**Thứ tự sửa đề xuất**
1. BUG-01, BUG-02 (vi phạm cứng).
2. BUG-03 (export sai, có trùng lịch).
3. BUG-04 (ghép ngầm).
4. Dựng lại staging, commit và deploy (điều kiện bàn giao).
5. BUG-05, BUG-06, BUG-07 (duyệt nguyện vọng, ràng buộc thủ công).
6. BUG-08, BUG-09, BUG-10.
7. Quyết định POL-01..05.
8. Dọn công cụ QA: TQ-01..05, đưa fixture vào repo.
9. Tính tái lập (BUG-11), tài liệu.

## Tệp

- [TEST_MATRIX.md](TEST_MATRIX.md)
- [BUGS.md](BUGS.md)
- [ALGORITHM_REVIEW.md](ALGORITHM_REVIEW.md)
- [DATASET_MANIFEST.json](DATASET_MANIFEST.json)
- [EXPERIMENT_RESULTS.csv](EXPERIMENT_RESULTS.csv)
- [DEPLOYMENT_REVIEW.md](DEPLOYMENT_REVIEW.md)
- [RERUN.md](RERUN.md)
- `evidence/` (JUnit, log, ảnh chụp, phản hồi API, workbook export, fixture tối thiểu)
- `harness/` (mã kiểm tra)
