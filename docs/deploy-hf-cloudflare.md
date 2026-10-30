# Triển khai miễn phí: Hugging Face + Cloudflare + Neon

> **Cập nhật 30-10-2026:** Hugging Face hiện yêu cầu gói PRO cho Space kiểu Docker (chỉ Space tĩnh còn miễn phí). Nếu cần miễn phí hoàn toàn, chạy backend trên Render thay cho mục 3: xem `docs/deploy-render.md`. Các mục Neon, R2, Pages và keep-warm giữ nguyên.

Dành cho nhóm dưới khoảng 10 người. Ba nền tảng đều có gói miễn phí; **giới hạn và chính sách có thể đổi, hãy đối chiếu trang giá của từng nơi trước khi dùng cho dữ liệu thật.**

```
Trình duyệt ──► Cloudflare Access (đăng nhập)
                  └─► Cloudflare Pages: giao diện tĩnh + Function /api/backend/*  (BFF, giữ token)
                        └─► Hugging Face Space (Docker): FastAPI + OR-Tools
                              ├─► Neon Postgres  (dữ liệu)
                              └─► Cloudflare R2  (file mẫu đầu ra, tương thích S3)
Cloudflare Worker cron ──► gọi /api/v1/health của Space mỗi 10 phút, 06:00–11:50 giờ Việt Nam
```

Vì sao chia như vậy:
- Cloudflare Workers/Pages không chạy được OR-Tools (thư viện native), nên backend ở Hugging Face.
- Ổ đĩa Space miễn phí là **tạm thời**, mất khi khởi động lại: dữ liệu phải nằm ở Neon và R2, không dùng SQLite.
- Space miễn phí **tự ngủ** khi lâu không có truy cập. Worker cron giữ cho nó thức vào buổi sáng; BFF tự thử lại tối đa khoảng 20 giây khi backend đang dậy.

## 1. Neon (database)
1. Tạo project Neon (region gần Việt Nam nhất, ví dụ Singapore), database `huce`.
2. Lấy connection string **trực tiếp** (không phải bản `-pooler`), dạng `postgresql://user:pass@ep-xxx.region.aws.neon.tech/huce?sslmode=require`. Chỉ có một container nên không cần pooler, và pooler chế độ transaction dễ lỗi với psycopg3.
3. Neon tự tạm dừng sau vài phút không dùng và dậy lại trong khoảng một giây; code đã bật `pool_pre_ping` để xử lý.

## 2. Cloudflare R2 (file)
1. Tạo bucket (ví dụ `huce-files`), tạo API token quyền Object Read & Write cho bucket đó.
2. Ghi lại: Account ID, Access Key ID, Secret Access Key. Endpoint là `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`, region là `auto`.

## 3. Hugging Face Space (backend)
1. Tạo Space mới, SDK **Docker**, chế độ **Private** (dữ liệu giảng viên là dữ liệu cá nhân). Space private cần token truy cập: tạo token dạng *Read* ở Settings → Access Tokens.
2. Lắp thư mục đẩy lên Space, rồi push (cần `git` và đăng nhập Hugging Face):
   ```bash
   deploy/huggingface/prepare_space.sh /tmp/huce-space
   cd /tmp/huce-space && git init && git remote add space https://huggingface.co/spaces/<owner>/<space> \
     && git add . && git commit -m "deploy" && git push space HEAD:main
   ```
3. Space → Settings → **Secrets** (không ghi vào file nào trong Git):

   | Tên | Giá trị |
   |---|---|
   | `ENVIRONMENT` | `production` |
   | `DATABASE_URL` | chuỗi Neon ở bước 1 |
   | `STORAGE_BACKEND` | `s3` |
   | `S3_ENDPOINT_URL` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
   | `S3_BUCKET` | tên bucket |
   | `S3_REGION` | `auto` |
   | `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | token R2 |
   | `INTERNAL_API_TOKEN` | chuỗi ngẫu nhiên dài, ví dụ `openssl rand -hex 32` |
   | `ALLOWED_ORIGINS` | địa chỉ Pages, ví dụ `https://huce-timetable.pages.dev` |

   Container tự chạy `alembic upgrade head` mỗi lần khởi động (đặt `MIGRATE_ON_BOOT=0` để tắt). Đừng đặt `RUN_MIGRATIONS_ON_STARTUP`: cấu hình production từ chối giá trị này.
4. Địa chỉ backend có dạng `https://<owner>-<space>.hf.space`. Kiểm tra: `curl -H "Authorization: Bearer <HF_TOKEN>" https://<owner>-<space>.hf.space/api/v1/health` phải trả `{"status":"ok",...}`.

## 4. Cloudflare Pages (giao diện + BFF)
1. Pages → Create project → kết nối repo GitHub. Root directory: `apps/web`. Build command: `npm install && npm run build:static` (hoặc `pnpm install --frozen-lockfile && pnpm build:static`). Output directory: `out`.
2. Settings → Variables and Secrets (loại Secret):
   - `BACKEND_API_URL` = địa chỉ Space
   - `INTERNAL_API_TOKEN` = đúng giá trị đã đặt trên Space
   - `HF_TOKEN` = token Hugging Face (chỉ khi Space private)
3. Bảo vệ truy cập: Zero Trust → Access → Applications → thêm ứng dụng Self-hosted cho tên miền Pages, chính sách cho phép đúng địa chỉ email của nhóm. Không làm bước này thì ai biết địa chỉ cũng dùng được toàn bộ chức năng, kể cả xóa dữ liệu.
4. Chạy thử local trước khi đẩy: `cd apps/web && npm run build:static && npx wrangler pages dev out --binding BACKEND_API_URL=... INTERNAL_API_TOKEN=...`.

## 5. Giữ cho backend thức buổi sáng
```bash
cd deploy/cloudflare/keepwarm
npx wrangler secret put BACKEND_API_URL     # địa chỉ Space
npx wrangler secret put HF_TOKEN            # nếu Space private
npx wrangler deploy
```
- Cron mặc định `*/10 23,0-4 * * *` (UTC) = mỗi 10 phút từ 06:00 đến 11:50 giờ Việt Nam, mọi ngày. Đổi giờ làm việc thì sửa `wrangler.toml` (nhớ trừ 7 giờ).
- Space miễn phí ngủ sau khoảng 48 giờ không có truy cập, nên việc gọi mỗi sáng là đủ để nó không ngủ. Cần chắc hơn ngoài giờ sáng thì thêm khoảng giờ vào cron.
- Mở địa chỉ Worker để kiểm tra tay: trả `{"backend_status":200}` là backend đang thức.

## Giới hạn cần biết
- Lần mở đầu tiên sau khi Space ngủ hoặc được build lại có thể mất từ 30 giây đến vài phút. BFF chờ tối đa khoảng 20 giây rồi báo "đang khởi động, hãy thử lại".
- Chạy phân công có giới hạn 30 giây phía giao diện (150 giây cho lệnh chạy). Space miễn phí có 2 vCPU: bài 176 lớp giải dưới 1 giây; bài khoảng 600 lớp chạm giới hạn 30 giây.
- Sao lưu: dùng `pg_dump` định kỳ từ máy của bạn, hoặc tính năng khôi phục theo thời điểm của Neon (thời gian lưu của gói miễn phí ngắn).
- Chưa kiểm chứng trên môi trường thật: build Docker (máy kiểm tra không chạy Docker), kết nối Neon, và R2. Phần BFF và bản build tĩnh đã chạy thử local bằng `wrangler pages dev`.
