# Đánh giá thuật toán CP-SAT · 26-10-2026

Mô hình mô tả dưới đây được đọc từ code thực tế (`apps/api/app/optimization/solver.py`, 859 dòng, gồm cả thay đổi chưa commit), không lấy từ tài liệu cũ.

Môi trường: Python 3.12.14, OR-Tools 9.15.6755, macOS arm64, 10 CPU.

## 1. Mô hình thực tế

**Biến quyết định**
- `x[lớp, gv]` là biến Boolean. Biến chỉ được tạo khi giảng viên là ứng viên của lớp.
- `unassigned[lớp]` là biến Boolean.
- Mỗi lớp: `Σx + unassigned = 1`, nên mỗi lớp có tối đa 1 giảng viên.

**Điều kiện để là ứng viên**
- Có năng lực `allowed`, không phải `HYPOTHETICAL_ALL`, và `confirmed` (hoặc chính sách bộ môn cho phép năng lực tạm).
- Năng lực cùng bộ môn hoặc không gắn bộ môn.
- Giảng viên đang tham gia kỳ.
- Không nằm trong danh sách cấm (`allowed=False`, áp cho toàn cục).
- Hai bổ sung:
  - Cầu nối theo tên môn (`INFERRED_HISTORY`, xem POL-02).
  - Ngoại lệ đã duyệt: lớp khóa có nguồn `MANUAL_OVERRIDE`.
- Ràng buộc cứng `UNAVAILABLE`/`BUSY_EVENT`/`AVOID_*` hoặc `PREFERRED*` không khớp sẽ loại cặp (lớp, gv) khỏi danh sách ứng viên.

**Ràng buộc cứng**
- Không trùng giờ theo ngày thực tế. Mốc là thứ Hai của tuần chứa ngày bắt đầu kỳ, có cắt theo ngày bắt đầu/kết thúc của buổi học. Cặp lớp ghép đã xác nhận được miễn.
- Khóa: `x == 1`.
- Nhóm ghép đã xác nhận phải cùng giảng viên. Chỉ ràng các lớp ghép được với lớp đầu nhóm.
- `MIN/MAX_CLASSES`, `MAX_SESSIONS_PER_DAY`, `MAX_DAYS_PER_WEEK`, `MAX_CONSECUTIVE_BLOCKS`, `REQUIRED/FORBIDDEN_ASSIGNMENT` khi đặt là hard.
- Seminar hard: chọn đúng 1 slot, và loại các thành viên khỏi lớp trùng slot đó.

**Hàm mục tiêu** (tổng có trọng số, không phải thứ tự ưu tiên tuyệt đối):

```
1.000.000 × số lớp chưa phân
+ 100.000 × số GV tham gia có ít nhất 1 ứng viên nhưng 0 lớp
+ 1.000 × (tải max − tải min), tải = Σ int(tín chỉ × 10) trên lớp đại diện của nhóm ghép
+ phạt mềm: weight×100 cho mỗi (lớp, GV) vi phạm; ×0,6 với AVOID;
  50 cho năng lực chưa xác nhận; 5 cho năng lực lịch sử;
  500 / 0,1 tín chỉ thiếu hoặc vượt định mức;
  khoảng trống tiết × số tuần × số ngày; …
```

**Lưu ý về các thành phần**
- Tải và số lớp của nhóm ghép chỉ tính một lần (qua lớp đại diện).
- Giảng viên không có ứng viên nào không tham gia vào min/max tải.
- Tần suất tính phạt mềm không đồng nhất:
  - `UNAVAILABLE`/`PREFERRED`: 1 lần cho mỗi cặp (lớp, GV), bất kể bao nhiêu buổi.
  - `PREFER_CONSECUTIVE`: theo từng (tuần, ngày, tiết trống).
  - `MIN_FREE_MORNING`: theo từng tuần.
  - Hệ quả: trọng số giữa các loại nguyện vọng không so sánh trực tiếp được với nhau.

**Tham số solver:** 8 worker, không đặt seed (mặc định 1), không có gợi ý khởi đầu.

## 2. Bộ kiểm tra độc lập và oracle

**`harness/independent_checker.py`**
- Đọc SQLite bằng `sqlite3`, không import module sản phẩm.
- Tự tính ngày học thực tế, va chạm, năng lực trực tiếp, khóa, ghép đã xác nhận, các loại hard chính, và tải.
- Không gọi helper nào của solver.

**`harness/algo_audit.py::oracle`**
- Vét cạn mọi cách phân công cho bài toán nhỏ, tự tính objective theo công thức ở mục 1.
- Bao phủ:
  - unassigned, giảng viên 0 lớp, chênh lệch tải;
  - `UNAVAILABLE`/`PREFERRED` hard và soft;
  - khóa hợp lệ, nhóm ghép đã xác nhận;
  - các guard chặn run (`DATA_READINESS_FAILURE`, `LOCKED_ASSIGNMENT_INVALID`).

| Kiểm tra | Kết quả |
|---|---|
| 150 instance ngẫu nhiên (seed 20261026), so objective tối ưu của oracle với CP-SAT, và kiểm tra vi phạm bằng checker | **150/150 khớp**, 0 vi phạm |
| Lần chạy đầu của oracle | 27 lệch. Nguyên nhân là **harness**: oracle chưa xử lý `PREFERRED` hard và chưa mô hình hóa các guard. Đã sửa oracle, không sửa kỳ vọng. Lần chạy lỗi giữ ở `evidence/algo-audit-v1-oracle-missing-hard-preferred.json` |
| 17 fixture TC01–TC17 chạy qua API thật | 15 PASS đầy đủ. TC16/TC17 đúng phân công (0/1); export bị từ chối "không thể xuất file rỗng", đây là hành vi có chủ đích |
| Thắt cổ chai 8 lớp cùng ca / 7 GV (nhóm ghép chưa xác nhận) | 7 giao, 1 trống, đúng bằng cận ghép cặp tối đa |
| 30 lớp cùng ca / 10 GV | 10 giao, đúng cận 20 lớp trống (đã chứng minh `optimal`, bound = objective) |

## 3. Kiểm tra metamorphic

| ID | Thuộc tính | Kết quả |
|---|---|---|
| META-ORDER | Đổi thứ tự dòng không đổi objective tối ưu | PASS |
| META-DISJOINT-WEEKS | Tuần lẻ và tuần chẵn cùng ca không bị coi là trùng | PASS |
| META-UNCONFIRMED-MERGE | Ghép chưa xác nhận không được miễn trùng giờ | PASS |
| META-LOCK-RESOLVE | Khóa giữ nguyên qua nhiều lần chạy lại | PASS |
| META-MONOTONE-CAPABILITY | Thêm năng lực không làm objective tối ưu (đã chứng minh) tệ hơn | PASS |
| DETERMINISM-3RUNS | Cùng dữ liệu, 3 lần chạy | Cùng objective, 3 phương án khác nhau (đồng tối ưu). INFO |

## 4. Phản ví dụ đã tìm được

Fixture tối thiểu nằm trong các hàm `probe_*` của `harness/algo_audit.py`. Kết quả ở `evidence/algo-audit.json`.

| ID | Loại | Mô tả ngắn | Lỗi |
|---|---|---|---|
| ALG-FORBIDDEN-COURSE | **Vi phạm cứng** | Lệnh cấm theo học phần bị bỏ qua khi giảng viên không phải ứng viên của một lớp trong học phần | BUG-01 |
| ALG-HALF-MERGE | **Vi phạm cứng** | Một lớp confirmed và một lớp candidate cùng nhóm: bị xếp trùng giờ cho cùng giảng viên | BUG-02 |
| ALG-MAX-DAYS-WEEK | Sai nghiệp vụ | Đếm thứ trong cả kỳ thay vì theo tuần, bỏ trống lớp không cần thiết | BUG-09 |
| ALG-SPREAD-INVERSION | Đảo ưu tiên objective | Lớp 150 tín chỉ bị bỏ trống vì làm chênh lệch tải tăng | POL-01 |
| ALG-NAME-BRIDGE | Chính sách | Năng lực lan sang học phần khác mã nhưng cùng tên | POL-02 |
| ALG-SOLVE-MUTATES-CAPS | Tác dụng phụ | Solve ghi đè năng lực `HYPOTHETICAL_ALL` | BUG-08 |
| ALG-MIN-NO-CAND | Biên | `MIN_CLASSES` hard với GV không có ứng viên trả `infeasible` (không crash) | PASS |
| ALG-PRIORITY | Biên | Phạt mềm lớn nhất dựng được với weight ≤ 1 là 19.600, nhỏ hơn 1.000.000 | PASS |

## 5. Ưu tiên của hàm mục tiêu

- **Bỏ một lớp để giảm phạt mềm:** không xảy ra trong miền trọng số hợp lệ (0..1). Trường hợp xấu nhất dựng được chỉ 19.600.
- **Bỏ một lớp để giảm chênh lệch tải:** chỉ xảy ra khi một lớp lớn hơn 100 tín chỉ (1.000 đơn vị × 1.000 > 1.000.000). Dữ liệu thật có 2–4 tín chỉ/lớp, nên không gặp.
- **Phạt giảng viên 0 lớp** (100.000 × n): không thể làm tăng số lớp bỏ trống, vì giao thêm lớp không bao giờ làm tăng số giảng viên 0 lớp.
- **Kết luận:** thứ tự ưu tiên đúng trong miền dữ liệu hiện có, nhưng **không được bảo đảm về mặt toán học**. Không sửa vì cần phê duyệt (AGENTS.md, quy tắc 4).
- **Miền biến tải:** `max_load` và `min_load` thuộc 0..10.000. Một giảng viên vượt 1.000 tín chỉ sẽ làm mô hình infeasible. Không thực tế với dữ liệu hiện có.

## 6. Chất lượng nghiệm trên dữ liệu thật

Chi tiết ở `EXPERIMENT_RESULTS.csv`, mỗi kịch bản 3 lần.

- **03-08-2026.xls** (176 lớp, 316 buổi, 17 giảng viên):
  - 115/176 lớp, `optimal`, bound = objective, 0 vi phạm độc lập.
  - Khớp số liệu của audit 10-10, nên kết quả ổn định giữa hai lần audit.
  - 85 khóa giữ nguyên; solver chạy 0,011 giây.
- **Cặp file thật** (158 lớp, 286 buổi, 20 giảng viên):
  - Chưa áp nguyện vọng: 132/158.
  - Sau khi áp 54 bản nháp mà **file** đã đánh CONFIRMED: 127/158, có phạt mềm 20.118.
- **Lớp trống trên dữ liệu thật:** precheck (phiên trước) và chẩn đoán cho thấy nguyên nhân là thiếu năng lực và nghẽn theo ca, không phải lỗi solver. Phạt chênh lệch tải là 340.000–400.000.
- **Đọc đúng số liệu:**
  - `OPTIMAL` ở đây nghĩa là tối ưu **của mô hình cho phép bỏ trống**. Không đồng nghĩa phân công 100% hay đã sẵn sàng xuất bản chính thức.
  - Phạt mềm = 0 khi chưa áp nguyện vọng không có nghĩa là nguyện vọng đã được thỏa.

## 7. Giới hạn: phần chưa kiểm chứng độc lập

- Oracle chưa bao phủ:
  - `MAX_SESSIONS_PER_DAY`, `MAX_CONSECUTIVE_BLOCKS`, `MIN_FREE_MORNING`, `PREFER_CONSECUTIVE/COMPACT`, `PREFER_LOW_WORKLOAD`;
  - định mức tải theo hồ sơ giảng viên;
  - seminar có nhiều slot.
- Các loại trên chỉ được kiểm qua pytest có sẵn, tức là gọi lại chính code sản phẩm.
- Chưa chạy bộ dữ liệu 308 lớp / 20 giảng viên của bài viết. **Không** dùng kết quả 176 hay 158 lớp để thay cho bảng 3 của bài viết.
- Lớp ghép mức buổi học (partial merge) chưa được hỗ trợ theo thiết kế, nên không kiểm tra.
- Bài toán lớn (600 lớp, 40 giảng viên) chạm giới hạn 30 giây ở 2/3 lần. Chất lượng khi timeout chưa được đánh giá cho dữ liệu thật cỡ lớn.
