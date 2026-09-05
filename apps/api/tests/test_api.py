from fastapi.testclient import TestClient
from datetime import date

from app.main import app
from app.db.session import SessionLocal
from app.models.entities import ClassSection, ClassSession, Constraint, Course, Lecturer, LecturerCourseCapability, Semester


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_semester():
    payload = {
        "name": "Học kỳ I · 2026–2027",
        "department_name": "Bộ môn Toán học",
        "start_date": "2026-09-07",
        "end_date": "2027-01-24",
        "head_name": "Phạm Đức Thoan",
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/semesters", json=payload)
        semesters = client.get("/api/v1/semesters")
    assert response.status_code == 200
    assert semesters.status_code == 200
    assert semesters.json()[0]["name"] == payload["name"]
    assert semesters.json()[0]["is_active"] is True


def test_v11_readiness_and_workload_routes_are_http_safe_and_semester_scoped():
    with SessionLocal() as db:
        semester = Semester(name="HTTP v1.1", department_name="D", start_date=date(2026, 1, 1), end_date=date(2026, 6, 1), head_name="H")
        other = Semester(name="Other", department_name="D", start_date=date(2026, 1, 1), end_date=date(2026, 6, 1), head_name="H")
        course = Course(code="HTTP-C", name="HTTP Course")
        lecturer = Lecturer(code="HTTP-L", canonical_name="HTTP Lecturer")
        db.add_all([semester, other, course, lecturer]); db.flush()
        section = ClassSection(semester_id=semester.id, course_id=course.id, class_code="HTTP-1", credits=3, source_file="test", source_sheet="S", source_row=1, assigned_lecturer_id=lecturer.id)
        db.add(section); db.flush()
        db.add_all([
            ClassSession(class_id=section.id, weekday=2, start_period=1, end_period=3, room="P", start_date=None, end_date=None, raw_weeks="1", active_weeks=[1], source_row=1),
            LecturerCourseCapability(lecturer_id=lecturer.id, course_id=course.id, allowed=True, confirmed=True),
            Constraint(semester_id=semester.id, name="Review", constraint_type="raw_preference", hardness="soft", lecturer_id=lecturer.id, target={}, confirmed=True),
        ])
        db.commit(); semester_id = semester.id; lecturer_id = lecturer.id
    with TestClient(app) as client:
        readiness = client.get(f"/api/v1/readiness?semester_id={semester_id}")
        workload = client.get(f"/api/v1/workload?semester_id={semester_id}")
    assert readiness.status_code == 200
    assert readiness.json()["teaching_groups"] == 1
    assert readiness.json()["meetings"] == 1
    assert any(item["code"] == "MALFORMED_CONSTRAINT" for item in readiness.json()["warnings"])
    assert workload.status_code == 200
    assert workload.json() == [{"lecturer_id": lecturer_id, "lecturer": "HTTP Lecturer", "teaching_groups": 1, "meetings": 1, "periods": 3, "credits": 3.0}]
