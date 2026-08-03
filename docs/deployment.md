# Triển khai ứng dụng

Kho mã đã sẵn sàng đưa lên GitHub và triển khai bằng Docker. Dữ liệu Excel thật, SQLite và file xuất nằm trong các thư mục đã bị `.gitignore` loại bỏ.

## Vercel production (đang sử dụng)

- Frontend: project `huce-tkb`, root directory `apps/web`.
- API: project `huce-tkb-api`, root directory `apps/api`.
- Database: Neon PostgreSQL được cài từ Vercel Marketplace và tự cấp `DATABASE_URL`.
- API dùng `/tmp/uploads`, `/tmp/exports` và `/tmp/source` cho file tạm; dữ liệu đã nhập, ràng buộc và kết quả tối ưu được lưu trong Neon.
- `NEXT_PUBLIC_API_URL` trỏ tới URL production của API; `CORS_ORIGINS` chỉ cho phép URL production của frontend và địa chỉ local phục vụ phát triển.

Triển khai lại bằng CLI từ thư mục repository:

```powershell
pnpm dlx vercel@latest deploy --prebuilt --prod --cwd apps/api
pnpm dlx vercel@latest deploy --prod --yes --cwd apps/web
```

Sau mỗi lần triển khai cần kiểm tra health API, upload ba workbook, chạy tối ưu và thử các định dạng xuất trên URL công khai.

## Render Blueprint

1. Push repository lên GitHub.
2. Trong Render, chọn **New > Blueprint** và kết nối repository.
3. Render đọc `render.yaml` và tạo hai dịch vụ `huce-tkb-api` và `huce-tkb-web`.
4. Nhập biến `NEXT_PUBLIC_API_URL` bằng URL HTTPS của dịch vụ API, ví dụ `https://huce-tkb-api.onrender.com`.
5. Nhập `CORS_ORIGINS` bằng URL HTTPS của frontend, ví dụ `https://huce-tkb-web.onrender.com`.
6. Deploy lại frontend sau khi URL API đã được thiết lập, vì biến `NEXT_PUBLIC_API_URL` được nhúng lúc build Next.js.

Ổ đĩa bền vững của API giữ database, tệp upload và tệp xuất qua các lần deploy. Không đặt workbook thật trong repository.

## Vercel cho frontend

1. Push repository lên GitHub và tạo project mới trong Vercel từ repository đó.
2. Chọn **Root Directory** là `apps/web`.
3. Đặt `NEXT_PUBLIC_API_URL` bằng URL HTTPS của `huce-tkb-api` trên Render cho cả Production, Preview và Development.
4. Deploy lại frontend, sau đó thêm URL Vercel vào `CORS_ORIGINS` của API Render.
5. Kiểm tra lần lượt tải file, tối ưu, xuất Excel, ICS, CSV, JSON và sao chép link Calendar trên URL công khai.

Frontend Next.js phù hợp với Vercel. API FastAPI hiện dùng SQLite và lưu workbook/upload trên filesystem, vì vậy cần Render Disk hoặc một máy chủ có ổ lưu trữ bền vững. Không deploy API này như Vercel Function nếu chưa chuyển database và file sang dịch vụ lưu trữ ngoài.

## Docker trên máy chủ riêng

```bash
docker compose up --build -d
```

Frontend mặc định chạy cổng `3000`, API chạy cổng `8000`. Khi dùng tên miền thật, cập nhật `NEXT_PUBLIC_API_URL` và `CORS_ORIGINS` trong cấu hình triển khai.

## Chuẩn kết nối dữ liệu

- Excel hoàn chỉnh: `/api/v1/exports/latest`
- iCalendar: `/api/v1/exports/calendar.ics`
- CSV: `/api/v1/exports/assignments.csv`
- JSON: `/api/v1/exports/schedule.json`
- Cài đặt học kỳ: `/api/v1/settings`

Tham số `lecturer` có thể được truyền vào endpoint ICS, CSV hoặc JSON để lọc đúng một giảng viên.

Google Calendar có hai cách sử dụng:

- Nhập tệp: tải `.ics` trong ứng dụng rồi vào **Settings > Import & export** của Google Calendar.
- Đăng ký URL: sau khi API có URL HTTPS công khai, sao chép endpoint ICS có tham số `lecturer` và thêm bằng **From URL**. URL local `127.0.0.1` không thể được máy chủ Google truy cập.
