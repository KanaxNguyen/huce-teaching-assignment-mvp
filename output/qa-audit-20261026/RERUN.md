# Chạy lại audit trên database QA mới

Mọi lệnh chạy trên **bản sao** và **DB mới**; không đụng `storage/database/*` của repo hay workbook gốc. Không ghi đè thư mục audit này: đặt `R` sang thư mục mới (ví dụ `output/qa-audit-YYYYMMDD`) và chép thư mục `harness/` sang đó.

## 0. Chuẩn bị bản sao

```bash
A=/Users/mac/AI/Huce_timetable/huce-teaching-assignment-mvp
Q=/private/tmp/huce-audit-NEW
R=$A/output/qa-audit-NEW
mkdir -p $Q $R/evidence && cp -R $A/output/qa-audit-20261026/harness $R/
rsync -a --exclude node_modules --exclude .next --exclude '*.db' --exclude storage --exclude output --exclude .venv --exclude __pycache__ $A/ $Q/src/
ln -s $A/.venv $Q/src/.venv; ln -s $A/node_modules $Q/src/node_modules; ln -s $A/apps/web/node_modules $Q/src/apps/web/node_modules
mkdir -p $Q/src/storage/uploads/schedule $Q/src/storage/database
```

Điều kiện:
- Python 3.12 + `.venv` của repo (OR-Tools 9.15.6755), Node 24, Chrome hệ thống cho Playwright.
- Các workbook thật ở `/Users/mac/AI/Huce_timetable/INPUT Gốc`, `/Users/mac/AI/Huce_timetable/test_fixtures`, và `/Users/mac/Downloads/phan-cong-giang-day-lich-hoc-to-bo-mon-03-08-2026.xls` (SHA-256 trong `DATASET_MANIFEST.json`).

## 1. Baseline

```bash
cd $Q/src
PYTHONPATH=apps/api UPLOAD_DIR=$PWD/storage/test-uploads EXPORT_DIR=$PWD/storage/test-exports .venv/bin/python -m pytest -q -p no:cacheprovider --junitxml=$R/evidence/pytest-backend.xml
```

Kỳ vọng: 335 pass, 7 fail do thiếu fixture, 1 skip (PostgreSQL). Cấp fixture **bản sao, giữ quyền ghi** (BUG-12), rồi chạy lại 7 test đó:

```bash
cp "$A/storage/uploads/schedule/phan-cong-giang-day-lich-hoc-to-bo-mon-03-09-2026.xls" $Q/src/storage/uploads/schedule/
cp "/Users/mac/AI/Huce_timetable/INPUT Gốc/Phan_Cong_Giang_Day_HK1_2026_2027.xlsx" "/Users/mac/AI/Huce_timetable/INPUT Gốc/Nguyện vọng TKB 2026-2027.xlsx" $Q/
cp $A/storage/database/huce_test.db $Q/src/storage/database/
PYTHONPATH=apps/api .venv/bin/python -m pytest -q apps/api/tests/test_phase5_real_data.py apps/api/tests/test_regression.py apps/api/tests/test_template_multirow.py "apps/api/tests/test_qa_full_audit_regressions.py::test_xls_template_export_preserves_date_display_format"
```

Kỳ vọng: 12 pass. Frontend:

```bash
cd $Q/src/apps/web && npm run lint && npm run typecheck && npx vitest run && BACKEND_API_URL=http://127.0.0.1:8026 INTERNAL_API_TOKEN=qa-audit-local npm run build
```

## 2. Thuật toán (oracle, metamorphic, probe)

```bash
cd $Q/src && DATABASE_URL=sqlite:///$Q/algo.db PYTHONPATH=apps/api .venv/bin/python $R/harness/algo_audit.py $R/evidence
```

Kỳ vọng với code hiện tại: oracle 150/150; metamorphic 5/5 PASS; probe FAIL ở `ALG-FORBIDDEN-COURSE`, `ALG-HALF-MERGE`, `ALG-SPREAD-INVERSION`, `ALG-NAME-BRIDGE`, `ALG-MAX-DAYS-WEEK`, `ALG-SOLVE-MUTATES-CAPS`. Khi các lỗi này được sửa, cùng các probe đó phải chuyển PASS mà không đổi expected.

## 3. TC01–TC17 qua API, và audit API

```bash
PYTHONPATH=apps/api .venv/bin/python $R/harness/fixture_e2e.py /Users/mac/AI/Huce_timetable/test_fixtures $R/evidence/fixtures-e2e $Q/work/fx
PYTHONPATH=apps/api .venv/bin/python $R/harness/api_audit.py $R/evidence/api $Q/work/api
```

## 4. Manifest và thực nghiệm (mỗi kịch bản 3 lần)

```bash
$A/.venv/bin/python $R/harness/manifest.py $R/evidence/manifest-raw.json
H=$( (cd $A && git rev-parse HEAD && git diff && git status --porcelain) | shasum -a 256 | cut -c1-16)
cd $Q/src && PYTHONPATH=apps/api .venv/bin/python $R/harness/experiments.py $R $Q/work/exp $H
```

Không so tốc độ giữa các kịch bản khác dữ liệu hoặc khác giới hạn thời gian.

## 5. Trình duyệt

Backend và frontend QA, mỗi lệnh ở một terminal:

```bash
cd $Q/src && PYTHONPATH=apps/api DATABASE_URL=sqlite:///$Q/ui/ui.db UPLOAD_DIR=$Q/ui/up EXPORT_DIR=$Q/ui/ex ENVIRONMENT=development INTERNAL_API_TOKEN=qa-audit-local .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8026
```

```bash
cd $Q/src/apps/web && BACKEND_API_URL=http://127.0.0.1:8026 INTERNAL_API_TOKEN=qa-audit-local npx next start --hostname 127.0.0.1 --port 3026
```

Seed DB **mới** (1 kỳ bắt đầu 2026-08-03; upload, preview rồi activate file 03-08-2026.xls). Kỳ vọng in ra `1 200 176`:

```bash
cd $Q/src && .venv/bin/python $R/harness/seed_ui.py
```

Chép spec và config, rồi chạy:

```bash
mkdir -p $Q/src/tests/audit && cp $R/harness/ui-audit.spec.ts $Q/src/tests/audit/ && cp $R/harness/playwright.audit.config.ts $Q/src/apps/web/
cd $Q/src/apps/web && AUDIT_SHOTS=$R/evidence/ui npx playwright test --config playwright.audit.config.ts
```

Sửa đường dẫn reporter trong config sang `$R`. Spec dùng thứ tự serial và DB sạch: U02 tạo đúng 1 run; U04 sửa và khóa 1 lớp; U07 tạo kỳ thứ 2.

Kiểm tra restart: lưu hash của 5 endpoint (`assignments`, `classes`, `optimization/runs`, `readiness`, `semesters`), dừng đúng tiến trình backend QA, khởi động lại với cùng `DATABASE_URL`, rồi so hash.

Đối chiếu export: gọi `GET /api/v1/exports/latest?semester_id=1&mode=draft`, đọc sheet "Phân công" bằng openpyxl, khóa theo (Tên môn học, Mã lớp) và so với `/assignments`. Lưu ý: mã lớp **không** duy nhất giữa các môn.

## 6. Dọn dẹp

Dừng tiến trình uvicorn và next ở cổng 8026/3026; có thể xoá `$Q`. Workbook gốc chỉ được đọc; SHA-256 phải khớp `DATASET_MANIFEST.json`.
