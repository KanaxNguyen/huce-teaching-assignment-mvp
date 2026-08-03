from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_mvp_api_contract_is_exposed():
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert {
        "/api/v1/imports/upload-bundle",
        "/api/v1/settings",
        "/api/v1/imports/latest",
        "/api/v1/constraints/{constraint_id}",
        "/api/v1/seminars/{seminar_id}",
        "/api/v1/optimization/runs",
        "/api/v1/exports/latest",
        "/api/v1/exports/calendar.ics",
        "/api/v1/exports/assignments.csv",
        "/api/v1/exports/schedule.json",
    }.issubset(paths)


def test_semester_settings_round_trip():
    with TestClient(app) as client:
        current = client.get("/api/v1/settings")
        assert current.status_code == 200
        payload = current.json()
        updated = client.put("/api/v1/settings", json=payload)

    assert updated.status_code == 200
    assert updated.json()["academic_year"] == payload["academic_year"]
    assert updated.json()["semester"] == payload["semester"]
