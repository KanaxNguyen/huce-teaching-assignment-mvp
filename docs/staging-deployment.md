# Staging deployment

Tài liệu này chỉ dành cho staging/preview. Không dùng các lệnh dưới đây để promote production.

## Kiến trúc

- Frontend: Vercel Preview chạy Next.js production build.
- API access: browser gọi `/api/backend/*`; Next.js route handler chuyển tiếp tới FastAPI và gắn `INTERNAL_API_TOKEN` ở server.
- Backend: FastAPI container chạy một hoặc nhiều replica, không tự chạy migration.
- Database: managed PostgreSQL.
- File bền vững: private S3-compatible bucket. Schedule/preference chỉ tồn tại trong temp directory khi parse; output template được lưu bằng object key ổn định.

## Biến môi trường

Backend cần `ENVIRONMENT=staging`, PostgreSQL `DATABASE_URL`, exact `ALLOWED_ORIGINS`, `STORAGE_BACKEND=s3`, toàn bộ biến `S3_*`, `INTERNAL_API_TOKEN` và `RUN_MIGRATIONS_ON_STARTUP=false`.

Frontend cần server-only `BACKEND_API_URL` và `INTERNAL_API_TOKEN`. Không cấu hình token dưới tên `NEXT_PUBLIC_*`. Với BFF, để `NEXT_PUBLIC_API_URL` trống; frontend sẽ gọi same-origin `/api/backend`.

## Release sequence

1. Build backend image từ `infra/backend.Dockerfile`.
2. Cấu hình secret trực tiếp trong provider; không ghi vào file được Git track.
3. Chạy migration một lần bằng cùng image/revision:

   ```bash
   alembic -c alembic.ini upgrade head
   alembic -c alembic.ini current
   ```

4. Deploy/restart FastAPI sau khi migration đạt `0004_v11_merge_status`.
5. Deploy `apps/web` thành Vercel Preview với BFF server variables.
6. Xác minh `/api/v1/health` công khai trả success; request backend khác thiếu hoặc sai `x-internal-api-key` trả `401`.
7. Chạy smoke flow bằng một semester staging riêng, rồi redeploy backend và xác minh DB/template/export vẫn tồn tại.

## Rollback

Không thay đổi các tag frozen. Khi deployment lỗi, rollback image/config của nhánh `deploy/staging`; không reset database hoặc xóa bucket. Alembic downgrade chỉ được thực hiện sau khi review riêng về data safety.
