# Backend miễn phí trên Render (thay cho Hugging Face)

Chỉ thay mục 3 của `deploy-hf-cloudflare.md`. Neon, Cloudflare R2, Cloudflare Pages và Access làm như cũ.

**Giới hạn cần biết (đối chiếu trang giá của Render trước khi dùng cho dữ liệu thật):**
- Gói miễn phí có 512 MB RAM và 0,1 CPU, tự ngủ sau khoảng 15 phút không có truy cập, thức lại mất khoảng một phút. Render nói rõ gói này không dành cho production.
- Bài 158 lớp có thể giải chậm hơn nhiều so với con số ghi trong doc cũ vì CPU thấp; thử chạy thật rồi tăng `time_limit_seconds` nếu cần.
- Không cần thẻ, nhưng cần tài khoản Render nối GitHub.

## Các bước
1. Đăng ký tại render.com bằng tài khoản GitHub, cho Render truy cập repo `KanaxNguyen/huce-teaching-assignment-mvp`.
2. New → Blueprint → chọn repo, nhánh `feat/deploy-hf-cloudflare`, đường dẫn blueprint `deploy/render/render.yaml`.
3. Điền các biến bí mật Render hỏi (giống bảng ở mục 3 của doc cũ): `DATABASE_URL` (Neon), `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `INTERNAL_API_TOKEN` (`openssl rand -hex 32`), `ALLOWED_ORIGINS` (địa chỉ Pages).
4. Khi build xong, kiểm tra: `curl https://<tên>.onrender.com/api/v1/health` phải trả `{"status":"ok",...}`.
5. Pages: `BACKEND_API_URL` = địa chỉ Render, `INTERNAL_API_TOKEN` giống Render, không cần `HF_TOKEN`.
6. Keep-warm: `npx wrangler secret put BACKEND_API_URL` với địa chỉ Render, bỏ qua `HF_TOKEN`. Cron cũ (mỗi 10 phút, 06:00–11:50) giữ instance thức buổi sáng, ngoài giờ đó nó sẽ ngủ.
