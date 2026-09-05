# HUCE Teaching Assignment System

Ứng dụng web hỗ trợ Bộ môn Toán học nhập lịch học từ Excel, chuẩn hóa dữ liệu, quản lý ràng buộc cứng/mềm, nhận diện lớp ghép, tự động phân công bằng OR-Tools CP-SAT và xuất thời khóa biểu có định dạng.

**Release status:** MVP v1.1 release-ready và đã đóng băng phạm vi tính năng.

> Thiết kế hướng tới **Option 02 — Minimal SaaS**. Kết nối Figma có mặt nhưng file được cung cấp trả về `INVALID_ARGUMENT`, vì vậy chưa có frame/node hoặc asset nào được tuyên bố là đã trích xuất. Wordmark chữ HUCE hiện là fallback, không phải logo chính thức.

## Chức năng MVP

- Tạo kỳ học với thời gian, đơn vị chuyên môn và trưởng bộ môn phụ trách.
- Học cấu trúc từ file đầu ra kỳ trước, tự nhận diện và cho phép sửa ánh xạ cột.
- Upload `.xls/.xlsx` hoặc nhập nguồn cục bộ.
- Tự tìm header, chỉ đọc A:N và loại vùng chữ ký/định dạng trống.
- Bảo toàn chuỗi tuần học theo vị trí; lưu cả `raw_weeks` và `active_weeks`.
- Gom nhiều dòng thành một lớp học phần.
- Khóa phân công có sẵn.
- Đề xuất lớp ghép khi toàn bộ lịch giống nhau.
- Tách mã/tên giảng viên và quản lý alias.
- Nhận dạng nguyện vọng thành ràng buộc mềm cần xác nhận.
- Duyệt nguyện vọng theo cơ chế human-in-the-loop trước khi tối ưu.
- Tạo ràng buộc cứng/mềm, trọng số 0–1.
- Tối ưu CP-SAT: một giảng viên mỗi lớp, không trùng lịch, cân bằng tải.
- Dashboard, bảng kết quả, lịch tuần, danh sách xung đột.
- Bàn phân công gồm dashboard tổng quan, log kiểm tra, lịch preview và trình sửa ràng buộc realtime.
- Xuất workbook gồm bảng phân công và TKB theo giảng viên.

## MVP v1.1

MVP v1.1 bổ sung semantics Hard/Soft rõ ràng; lecturer identity và Data Readiness; trạng thái Imported/Manual/Locked; merge review; shared seminar; workload view và workload constraints; `MAX_CONSECUTIVE_BLOCKS`; Problem Log có action; giữ workspace context sau mutation; và re-solve diff.

Partial merge hiện chỉ hỗ trợ **REVIEW-ONLY**. True partial merge ở Meeting level chưa được hỗ trợ.

## Kiến trúc

- `apps/web`: Next.js, React, TypeScript, CSS Modules.
- `apps/api`: FastAPI, SQLAlchemy, SQLite, openpyxl/xlrd, OR-Tools.
- `data/local`: dữ liệu Excel thật, bị Git ignore.
- `data/fixtures`: dữ liệu kiểm thử ẩn danh.
- `storage`: database, upload và export cục bộ, bị Git ignore.

## Chuẩn bị dữ liệu thật

Đặt workbook trong `data/local/source/`, hoặc dùng vùng upload trên giao diện. File lịch mới nhất mặc định là `schedule-2026-07-28.xls`. Không commit workbook thật.

Để copy lại từ thư mục cha và cập nhật manifest:

```powershell
python scripts/import-source-files.py
```

## Chạy local bằng PowerShell

```powershell
cd D:\APP_listing\huce-teaching-assignment-mvp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/api[dev]"
pnpm install
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoExit','-Command','cd D:\APP_listing\huce-teaching-assignment-mvp; .\.venv\Scripts\Activate.ps1; python -m uvicorn app.main:app --app-dir apps/api --reload --host 127.0.0.1 --port 8000'
pnpm --filter @huce/web dev
```

- Frontend: http://127.0.0.1:3000
- API: http://127.0.0.1:8000
- Swagger: http://127.0.0.1:8000/docs

Trên macOS/Linux, sau khi cài dependencies, chạy hai terminal:

```bash
PYTHONPATH=apps/api .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pnpm --filter @huce/web dev --hostname 127.0.0.1
```

Sau khi API chạy, bấm **Nhập dữ liệu mẫu cục bộ** để nhập các workbook đang có.

## Docker

```powershell
docker compose up --build
```

Docker chưa được cài trên máy phát triển hiện tại, nên cấu hình đã được tạo nhưng chưa thể chạy xác minh tại đây.

## Kiểm thử

```powershell
python -m pytest apps/api/tests
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm e2e
```

## Chạy demo đầy đủ với dữ liệu thật

Script dưới đây chạy độc lập trên database tạm: tạo kỳ học, nhận dạng mẫu ma trận,
nhập hai file, xác nhận nguyện vọng còn chờ, tối ưu và xuất workbook cuối cùng.

```powershell
python scripts/demo-mvp-flow.py `
  --template "Thoi_Khoa_Bieu_To_Bo_Mon_Nguyen_Ven_Lop.xlsx" `
  --schedule "phan-cong-giang-day-lich-hoc-to-bo-mon-03-09-2026.xls" `
  --preferences "Nguyện vọng TKB 2026-2027.xlsx" `
  --output "DEMO_KET_QUA_MVP_HUCE.xlsx"
```

CI dùng fixture ẩn danh, không dùng Excel thật.

## Xuất Excel

Chạy tối ưu thành công, sau đó chọn **Xuất Excel** trên topbar. File được lưu dưới `storage/exports` và tải qua API `/api/v1/exports/latest`.

## Thay logo HUCE

Khi có asset chính thức, đặt SVG tại `apps/web/public/brand/huce-logo.svg` và thay component `apps/web/src/components/brand/huce-wordmark.tsx`. Không sử dụng logo tìm thấy từ nguồn không rõ ràng.

## Bảo vệ dữ liệu

`.gitignore` loại toàn bộ `data/local`, `storage`, workbook, database, `.env`, log và báo cáo kiểm thử. Chỉ schema, manifest mẫu và fixture ẩn danh được commit.

## Tài liệu

- [Figma source](https://www.figma.com/design/OdSLKDuaAwEoQePRugRIA1)
- [GitHub repository (private)](https://github.com/KanaxNguyen/huce-teaching-assignment-mvp)
- `docs/environment-audit.md`
- `docs/figma-analysis.md`
- `docs/data-analysis.md`
- `docs/architecture.md`
- `docs/api.md`

## Giới hạn hiện tại

- True partial merge ở Meeting level chưa được hỗ trợ; các trường hợp partial merge chỉ được đưa vào review.
- Figma chưa đọc được do connector trả `INVALID_ARGUMENT`; giao diện dùng các đặc trưng Option 02 trong yêu cầu làm fallback.
- Nhận dạng văn bản nguyện vọng chỉ hỗ trợ các mẫu cơ bản và cố ý đưa trường hợp mơ hồ vào danh sách xác nhận.
- Chưa có xác thực nhiều người dùng hay phân quyền.
- Docker cần được cài để kiểm chứng build container local.
