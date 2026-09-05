from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the complete HUCE MVP flow with real workbooks."
    )
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--preferences", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in (args.template, args.schedule, args.preferences):
        if not path.is_file():
            raise SystemExit(f"Không tìm thấy file: {path}")

    with tempfile.TemporaryDirectory(prefix="huce-mvp-demo-") as temp:
        root = Path(temp)
        os.environ["DATABASE_URL"] = f"sqlite:///{root / 'demo.db'}"
        os.environ["UPLOAD_DIR"] = str(root / "uploads")
        os.environ["EXPORT_DIR"] = str(root / "exports")

        from app.main import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            semester = client.post(
                "/api/v1/semesters",
                json={
                    "name": "Học kỳ I · 2026–2027",
                    "department_name": "Bộ môn Toán học",
                    "start_date": "2026-09-07",
                    "end_date": "2027-01-24",
                    "head_name": "Phạm Đức Thoan",
                },
            )
            semester.raise_for_status()
            semester_id = semester.json()["id"]

            with args.template.open("rb") as handle:
                template = client.post(
                    f"/api/v1/templates/detect?semester_id={semester_id}",
                    files={
                        "template_file": (
                            args.template.name,
                            handle,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                    },
                )
            template.raise_for_status()

            with (
                args.schedule.open("rb") as schedule,
                args.preferences.open("rb") as preferences,
            ):
                imported = client.post(
                    "/api/v1/imports/upload-pair",
                    files={
                        "schedule_file": (
                            args.schedule.name,
                            schedule,
                            "application/vnd.ms-excel",
                        ),
                        "preference_file": (
                            args.preferences.name,
                            preferences,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        ),
                    },
                )
            imported.raise_for_status()

            constraints = client.get("/api/v1/constraints")
            constraints.raise_for_status()
            for constraint in constraints.json():
                if not constraint["confirmed"]:
                    response = client.patch(
                        f"/api/v1/constraints/{constraint['id']}",
                        json={"confirmed": True},
                    )
                    response.raise_for_status()

            optimized = client.post(
                "/api/v1/optimization/run",
                json={"time_limit_seconds": 30, "confirm_merged_suggestions": False},
            )
            optimized.raise_for_status()
            dashboard = client.get("/api/v1/dashboard")
            dashboard.raise_for_status()
            assignments = client.get("/api/v1/assignments")
            assignments.raise_for_status()
            exported = client.get("/api/v1/exports/latest")
            exported.raise_for_status()

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(exported.content)
        template_result = template.json()
        import_result = imported.json()
        optimization_result = optimized.json()
        dashboard_result = dashboard.json()
        print("DEMO MVP HOÀN TẤT")
        print(
            f"1. Kỳ học: #{semester_id}\n"
            f"2. Mẫu: {template_result['layout_label']} · dòng {template_result['header_row']}\n"
            f"3. Dữ liệu: {import_result['summary']['classes']} lớp · "
            f"{import_result['summary']['sessions']} buổi · "
            f"{len(constraints.json())} nguyện vọng · "
            f"{import_result['serious_errors']} lỗi chặn\n"
            f"4. Tối ưu: {optimization_result['status']} · "
            f"{len(assignments.json())} phân công\n"
            f"5. Dashboard: {dashboard_result['unassigned_classes']} lớp chưa phân · "
            f"{dashboard_result['validation_errors']} lỗi chặn\n"
            f"6. Đã xuất: {args.output}"
        )


if __name__ == "__main__":
    main()
