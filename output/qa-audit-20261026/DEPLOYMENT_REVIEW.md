# Rà soát triển khai (chỉ đọc) · 26-10-2026

Trong audit này không deploy, không promote, không đổi cấu hình, không chạy migration, không cấp quyền truy cập mới. Không in giá trị secret nào; các file `.env*` chỉ được đọc tên biến.

## Đã xác minh

| Mục | Cách kiểm | Kết quả |
|---|---|---|
| Git remote | `git branch -vv`, `rev-list` | `feat/preference-v2` và `origin/deploy/staging` cùng trỏ `b25a522` (22/09/2026 16:47). `main` local đi trước `origin/main` 1 commit (đóng băng MVP v1). |
| Phần local chưa lên remote | `git status` | 24 file đã sửa và khoảng 50 file chưa track; danh sách ở `evidence/git-status-before.txt`. Gồm: precheck, kịch bản xử lý, sửa ghép lớp và override trong solver, export POST, tab kéo thả, mẫu V3, các script debug ở gốc repo. **Không có trên remote và không có trên staging.** |
| Vercel project | `vercel ls huce-teaching-assignment-staging` (CLI đã đăng nhập) | Preview mới nhất `…-cpynb3oqn.vercel.app` ở trạng thái Ready, tạo 22/09/2026 16:48:30 (~1 phút sau commit `b25a522`). Có một deployment target Production 51 ngày trước ở trạng thái **Error**. |
| Commit của preview | `vercel inspect` | CLI không trả SHA. Thời điểm tạo trùng `b25a522`, nhưng **chưa chứng minh được** đúng commit đó (deploy bằng CLI có thể kèm cả thay đổi chưa commit lúc ấy). |
| Frontend staging | `GET /` | 200 |
| Backend staging qua BFF | `GET /api/backend/health`, `/semesters`, `/dashboard` | **404 `{"message":"Application not found"}`**, là trang 404 của Railway. Service backend tại `BACKEND_API_URL` không còn tồn tại hoặc đã đổi domain. **Staging không dùng được.** |
| Token trong bundle | grep `.next/static` của bản build QA | Token và URL backend không xuất hiện trong bundle client. BFF đọc `INTERNAL_API_TOKEN` lúc chạy, phía server. |
| `NEXT_PUBLIC_*` | grep `apps/web` | Không dùng biến `NEXT_PUBLIC_*` nào chứa token. |
| CORS và cấu hình | `config.py` | Khi môi trường không phải development: bắt buộc PostgreSQL, `ALLOWED_ORIGINS` không phải localhost và không wildcard, có token, có S3. |
| Migration head trong code | `alembic/versions` | `0009_department_agnostic_capabilities`. Tài liệu staging vẫn ghi `0004`. |
| Lưu trữ qua restart | Backend QA trên SQLite file | 5/5 snapshot API giống hệt trước và sau restart (`evidence/ui/snap-*.txt`). Đây là kiểm tra local, **không** phải PostgreSQL hay S3. |

## Bị chặn

| Mục | Lý do |
|---|---|
| Biến môi trường Vercel, deployment API | Vercel MCP trả 403 cho scope `kanaxnguyens-projects`. Tôi không gọi `authorize_team_access` vì việc này cần chủ tài khoản cấp quyền. |
| Railway service, log, biến, migration thực tế trên PostgreSQL | `railway status`: phiên đăng nhập hết hạn. |
| Healthcheck backend staging, 401 khi thiếu token, CORS thực, lỗi upload thực | Không có backend staging đang chạy. |
| Persistence PostgreSQL và S3 qua redeploy | Không có môi trường QA tương ứng. |

## Khác biệt local và remote

1. Toàn bộ thay đổi chưa commit (precheck, kịch bản thẩm quyền, kéo thả, 2 sửa lỗi solver, export POST, mặc định `confirm_merged=false` ở frontend) **chưa** có trên staging.
2. Frontend ở `b25a522` luôn gửi `confirm_merged_suggestions: true`, tức là mỗi lần chạy trên staging sẽ xác nhận ngầm mọi gợi ý ghép lớp (BUG-04).
3. Staging không có backend, nên mọi so sánh hành vi giữa local và remote ở tầng API là **chưa kiểm chứng**.

## Rủi ro cấu hình (nghi vấn, chưa thấy trên môi trường thật)

- `ENVIRONMENT` mặc định là `development` (`config.py:10`). Nếu thiếu biến này, backend tắt kiểm tra `x-internal-api-key` (`main.py:47-50`) và dùng SQLite mặc định.
- BFF chuyển tiếp mọi đường dẫn kèm token nội bộ. Chưa có lớp đăng nhập người dùng, nên ai mở được URL frontend cũng có toàn quyền ghi (POL-05).

## Việc cần làm trước khi bàn giao triển khai

1. Dựng lại backend staging (Railway hoặc nơi khác), PostgreSQL, S3; chạy `alembic upgrade head` tới `0009`; cập nhật `BACKEND_API_URL` trên Vercel.
2. Commit, review và đẩy các thay đổi local lên nhánh; deploy preview mới từ đúng một commit có SHA ghi nhận.
3. Chạy lại smoke staging: health, 401 khi thiếu hoặc sai token, upload lỗi, chạy solver, export, redeploy rồi kiểm tra dữ liệu còn nguyên.
4. Sửa tài liệu migration head.
