# HUCE Teaching Assignment System

Ứng dụng web hỗ trợ Bộ môn Toán học nhập lịch học từ Excel, chuẩn hóa dữ liệu, quản lý ràng buộc cứng/mềm, nhận diện lớp ghép, tự động phân công bằng OR-Tools CP-SAT và xuất thời khóa biểu có định dạng.

> Thiết kế hướng tới **Option 02 — Minimal SaaS**. Kết nối Figma có mặt nhưng file được cung cấp trả về `INVALID_ARGUMENT`, vì vậy chưa có frame/node hoặc asset nào được tuyên bố là đã trích xuất. Wordmark chữ HUCE hiện là fallback, không phải logo chính thức.

## Chức năng MVP

- Upload lịch học, nguyện vọng và file mẫu `.xls/.xlsx`, hoặc nhập nguồn cục bộ.
- Tự tìm header, chỉ đọc A:N và loại vùng chữ ký/định dạng trống.
- Bảo toàn chuỗi tuần học theo vị trí; lưu cả `raw_weeks` và `active_weeks`.
- Gom nhiều dòng thành một lớp học phần.
- Khóa phân công có sẵn.
- Đề xuất lớp ghép khi toàn bộ lịch giống nhau.
- Tách mã/tên giảng viên và quản lý alias.
- Nhận dạng nguyện vọng thành ràng buộc mềm cần xác nhận.
- Tạo ràng buộc cứng/mềm, trọng số 0–1.
- Tối ưu CP-SAT: một giảng viên mỗi lớp, không trùng lịch, cân bằng tải.
- Dashboard, bảng kết quả, lịch tuần theo trục 15 tiết, danh sách xung đột.
- Giao diện sáng/tối, nhớ lựa chọn của người dùng và hỗ trợ responsive trên điện thoại.
- Xuất workbook, ICS cho Google/Outlook/Apple Calendar, CSV và JSON tích hợp.
- Chỉnh sửa, bật/tắt hoặc xóa ràng buộc trực tiếp trên giao diện.
- Điều chỉnh độ cứng và trọng số seminar; xem phương án seminar được chọn.
- Theo dõi lần nhập dữ liệu và các lần tối ưu gần nhất.
- Cài đặt học kỳ, năm học, khoảng ngày, tên Calendar, múi giờ và giảng viên mặc định.
- Mục **Hướng dẫn MVP** cung cấp checklist vận hành và bàn giao.

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

Sau khi API chạy, bấm **Nhập dữ liệu mẫu cục bộ** để nhập các workbook đang có.

## Docker

```powershell
docker compose up --build
```

Docker chưa được cài trên máy phát triển hiện tại, nên cấu hình đã được tạo nhưng chưa thể chạy xác minh tại đây.

## Đưa lên GitHub và triển khai

Repository có sẵn CI, Dockerfile và `render.yaml`. Xem [hướng dẫn triển khai](docs/deployment.md) để deploy frontend Next.js, API FastAPI và ổ lưu trữ bền vững từ GitHub.

Mô hình khuyến nghị cho bản MVP là frontend trên Vercel và API trên Render. SQLite, file upload và file xuất cần ổ đĩa bền vững nên không đặt API vào Vercel Function tạm thời.

## Kiểm thử

```powershell
python -m pytest apps/api/tests
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm e2e
```

CI dùng fixture ẩn danh, không dùng Excel thật.

## Xuất và kết nối

Chạy tối ưu thành công, sau đó chọn **Xuất Excel** trên topbar. File `Thoi_Khoa_Bieu_To_Bo_Mon_2026_2027_Hoan_Chinh.xlsx` được lưu dưới `storage/exports` và tải qua API `/api/v1/exports/latest`.

Trong mục **Thời khóa biểu**, có thể xuất `.ics` để nhập vào Google Calendar, Outlook hoặc Apple Calendar; `.csv` và `.json` dùng để kết nối với khoa, phòng đào tạo hoặc hệ thống khác. Lớp ghép được gộp thành một sự kiện Calendar nhưng vẫn giữ đủ mã lớp.

Ở máy local, chọn **Tải ICS cho Google Calendar** rồi nhập tệp tại trang **Nhập và xuất** của Google Calendar. Sau khi deploy công khai, có thể dùng **Sao chép link ICS** để đăng ký bằng URL; khi đó Calendar sẽ định kỳ đọc lại lịch từ endpoint công khai.

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
- `docs/mvp-handover.md`

## Giới hạn hiện tại

- Figma chưa đọc được do connector trả `INVALID_ARGUMENT`; giao diện dùng các đặc trưng Option 02 trong yêu cầu làm fallback.
- Nhận dạng văn bản nguyện vọng chỉ hỗ trợ các mẫu cơ bản và cố ý đưa trường hợp mơ hồ vào danh sách xác nhận.
- Chưa có xác thực nhiều người dùng hay phân quyền.
- Docker cần được cài để kiểm chứng build container local.
