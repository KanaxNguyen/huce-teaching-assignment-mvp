from fastapi.testclient import TestClient

from app.main import app


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
