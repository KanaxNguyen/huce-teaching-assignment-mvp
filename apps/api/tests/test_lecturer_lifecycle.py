from datetime import date

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models.entities import (
    ClassSection,
    Course,
    Lecturer,
    LecturerAlias,
    LecturerCourseCapability,
    LecturerIdentityAudit,
    LecturerSemesterProfile,
    NormalizedPreferenceDraft,
    Semester,
)


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def test_lecturer_crud_and_safe_delete():
    client = TestClient(app)

    # 1. Create lecturer
    create_resp = client.post("/api/v1/lecturers", json={
        "code": "GV_TEST_1",
        "name": "Nguyễn Văn Test",
        "department": "Toán học",
        "status": "ACTIVE",
    })
    assert create_resp.status_code == 200
    data = create_resp.json()
    lec_id = data["id"]
    assert data["code"] == "GV_TEST_1"
    assert data["name"] == "Nguyễn Văn Test"

    # 2. Edit lecturer
    edit_resp = client.patch(f"/api/v1/lecturers/{lec_id}", json={
        "code": "GV_TEST_1",
        "name": "Nguyễn Văn Đã Sửa",
        "department": "Toán học",
        "status": "ACTIVE",
    })
    assert edit_resp.status_code == 200
    assert edit_resp.json()["name"] == "Nguyễn Văn Đã Sửa"

    # 3. Check dependencies (currently 0)
    dep_resp = client.get(f"/api/v1/lecturers/{lec_id}/dependencies")
    assert dep_resp.status_code == 200
    assert dep_resp.json()["can_delete"] is True

    # 4. Safe delete without confirmed flag returns 422
    del_unconfirmed = client.delete(f"/api/v1/lecturers/{lec_id}")
    assert del_unconfirmed.status_code == 422

    # 5. Delete with confirmed=True succeeds when 0 dependencies
    del_resp = client.delete(f"/api/v1/lecturers/{lec_id}?confirmed=true")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True


def test_lecturer_delete_rejected_when_referenced():
    with SessionLocal() as db:
        sem = Semester(name="S", department_name="D", start_date=date(2026, 1, 1), end_date=date(2026, 6, 1), head_name="H")
        c = Course(code="C_REF", name="Môn Ref")
        lec = Lecturer(code="GV_REF", canonical_name="Giảng viên Có Ref", confirmed=True)
        db.add_all([sem, c, lec]); db.flush()
        sec = ClassSection(semester_id=sem.id, course_id=c.id, class_code="L_REF", assigned_lecturer_id=lec.id, source_file="f", source_sheet="s", source_row=1)
        db.add(sec)
        db.commit()
        lec_id = lec.id

    client = TestClient(app)
    # Check dependencies shows referenced class
    dep_resp = client.get(f"/api/v1/lecturers/{lec_id}/dependencies")
    assert dep_resp.status_code == 200
    assert dep_resp.json()["can_delete"] is False

    # Delete attempt is rejected with 409
    del_resp = client.delete(f"/api/v1/lecturers/{lec_id}?confirmed=true")
    assert del_resp.status_code == 409


def test_lecturer_participation_and_capabilities():
    with SessionLocal() as db:
        sem = Semester(name="S", department_name="D", start_date=date(2026, 1, 1), end_date=date(2026, 6, 1), head_name="H")
        c = Course(code="C_CAP", name="Môn Cap")
        lec = Lecturer(code="GV_CAP", canonical_name="GV Cap", confirmed=True)
        db.add_all([sem, c, lec])
        db.commit()
        sid, cid, lid = sem.id, c.id, lec.id

    client = TestClient(app)

    # Set participation
    part_resp = client.put(f"/api/v1/lecturers/{lid}/participation?semester_id={sid}", json={
        "participation_status": "ON_LEAVE",
        "note": "Nghỉ sinh học kỳ này",
    })
    assert part_resp.status_code == 200
    assert part_resp.json()["saved"] is True

    # Set capability
    cap_resp = client.put(f"/api/v1/lecturers/{lid}/capabilities", json={
        "course_id": cid,
        "allowed": True,
        "confirmed": True,
    })
    assert cap_resp.status_code == 200

    # Read profile
    prof_resp = client.get(f"/api/v1/lecturers/{lid}/profile?semester_id={sid}")
    assert prof_resp.status_code == 200
    pdata = prof_resp.json()
    assert pdata["participation"]["participation_status"] == "ON_LEAVE"
    assert any(cap["course_id"] == cid and cap["allowed"] for cap in pdata["capabilities"])


def test_lecturer_merge_and_audit():
    with SessionLocal() as db:
        sem = Semester(name="S", department_name="D", start_date=date(2026, 1, 1), end_date=date(2026, 6, 1), head_name="H")
        c = Course(code="C_M", name="Môn M")
        source = Lecturer(code="GV_SRC", canonical_name="Nguyễn Văn A (Nhầm)", confirmed=True)
        target = Lecturer(code="GV_TGT", canonical_name="Nguyễn Văn A (Chuẩn)", confirmed=True)
        db.add_all([sem, c, source, target]); db.flush()

        # Add an assigned class to source
        sec = ClassSection(semester_id=sem.id, course_id=c.id, class_code="L_M", assigned_lecturer_id=source.id, source_file="f", source_sheet="s", source_row=1)
        db.add(sec)
        db.commit()
        src_id, tgt_id = source.id, target.id
        sec_id = sec.id

    client = TestClient(app)

    # Preview merge
    preview = client.post(f"/api/v1/lecturers/{src_id}/merge", json={"target_id": tgt_id, "confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["preview"] is True

    # Execute merge
    merged = client.post(f"/api/v1/lecturers/{src_id}/merge", json={"target_id": tgt_id, "confirmed": True})
    assert merged.status_code == 200
    assert merged.json()["merged"] is True

    # Verify source was deactivated or deleted and target received assignment
    with SessionLocal() as db:
        updated_sec = db.get(ClassSection, sec_id)
        assert updated_sec.assigned_lecturer_id == tgt_id

        # Verify audit log exists
        audit = db.scalar(select(LecturerIdentityAudit).where(LecturerIdentityAudit.source_lecturer_id == src_id))
        assert audit is not None
        assert audit.action == "MERGE"
