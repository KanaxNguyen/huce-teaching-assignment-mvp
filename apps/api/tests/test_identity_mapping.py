import pytest
from pathlib import Path
from sqlalchemy import select
from app.db.session import SessionLocal, engine, Base
from app.models.entities import Semester, Lecturer, Constraint, LecturerCourseCapability, NormalizedPreferenceDraft
from app.services.importer import _import_files_impl
from app.services.lecturer_master import resolve_identity
from app.api.routes import apply_preference_drafts
from datetime import date

@pytest.fixture
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _semester(db):
    sem = Semester(name="Test Sem", department_name="Toán", start_date=date(2026, 9, 1), end_date=date(2027, 1, 31), head_name="Test Head", status="draft", is_active=True)
    db.add(sem)
    db.commit()
    return sem

def test_resolve_identity_known_aliases(database):
    db = database
    sem = _semester(db)
    l1 = Lecturer(canonical_name="Phạm Đức Thoan", code="001", confirmed=True)
    l2 = Lecturer(canonical_name="Lê Viết Cường", code="002", confirmed=True)
    l3 = Lecturer(canonical_name="Trịnh Thị Minh Hằng", code="003", confirmed=True)
    db.add_all([l1, l2, l3])
    db.commit()

    assert resolve_identity(db, "Thoan")[0].id == l1.id
    assert resolve_identity(db, "Cường")[0].id == l2.id
    assert resolve_identity(db, "Hằng")[0].id == l3.id

    assert resolve_identity(db, "Long")[0] is None
    assert resolve_identity(db, "Long")[1] == "NEW_LECTURER_CANDIDATE"

def test_preference_import_does_not_create_clones(database):
    db = database
    sem = _semester(db)
    schedule_file = Path('/Users/mac/AI/Huce_timetable/INPUT Gốc/Phan_Cong_Giang_Day_HK1_2026_2027.xlsx')
    pref_file = Path('/Users/mac/AI/Huce_timetable/INPUT Gốc/Phieu_Nguyen_Vong_Giang_Vien_2026_2027_Chuan_Hoa.xlsx')

    db.add(Lecturer(canonical_name="Nguyễn Mai Hồng", code="0001", confirmed=True))
    db.add(Lecturer(canonical_name="Nguyễn Văn Tuyên", code="0002", confirmed=True))
    db.add(Lecturer(canonical_name="Nguyễn Thị Thuần", code="0003", confirmed=True))
    db.commit()

    _import_files_impl(db=db, paths=[schedule_file, pref_file], semester_id=sem.id, schedule_paths=[schedule_file], preference_paths=[pref_file], commit=True)
    
    clones = db.scalars(select(Lecturer).where(Lecturer.confirmed == False)).all()
    assert len(clones) == 0

def test_capabilities_and_constraints_share_id(database):
    db = database
    sem = _semester(db)
    schedule_file = Path('/Users/mac/AI/Huce_timetable/INPUT Gốc/Phan_Cong_Giang_Day_HK1_2026_2027.xlsx')
    pref_file = Path('/Users/mac/AI/Huce_timetable/INPUT Gốc/Phieu_Nguyen_Vong_Giang_Vien_2026_2027_Chuan_Hoa.xlsx')

    db.add(Lecturer(canonical_name="Nguyễn Mai Hồng", code="0001", confirmed=True))
    db.add(Lecturer(canonical_name="Nguyễn Văn Tuyên", code="0002", confirmed=True))
    db.add(Lecturer(canonical_name="Nguyễn Thị Thuần", code="0003", confirmed=True))
    db.commit()

    _import_files_impl(db=db, paths=[schedule_file, pref_file], semester_id=sem.id, schedule_paths=[schedule_file], preference_paths=[pref_file], commit=True)

    drafts = db.query(NormalizedPreferenceDraft).filter(NormalizedPreferenceDraft.semester_id == sem.id).all()
    for d in drafts:
        if d.lecturer_id is not None and d.status == "NEEDS_REVIEW" and d.draft_kind == "CONSTRAINT":
            d.status = "CONFIRMED"
            d.needs_review = False
    db.commit()
    sem.active_preference_source_id = drafts[0].source_version_id
    db.commit()

    drafts_to_apply = db.query(NormalizedPreferenceDraft).filter(
        NormalizedPreferenceDraft.semester_id == sem.id,
        NormalizedPreferenceDraft.constraint_type.notin_(["RAW_NOTE", "SEMINAR_NOTE"]),
        NormalizedPreferenceDraft.lecturer_id.isnot(None),
        NormalizedPreferenceDraft.needs_review == False
    ).all()

    class DummyPayload:
        draft_ids = [d.id for d in drafts_to_apply]

    apply_preference_drafts(payload=DummyPayload(), semester_id=sem.id, db=db)
    db.commit()

    constraints = db.query(Constraint).filter(Constraint.lecturer_id.isnot(None)).all()
    assert len(constraints) > 0

    capabilities = db.query(LecturerCourseCapability).filter(LecturerCourseCapability.lecturer_id.isnot(None)).all()
    assert len(capabilities) > 0

    thuy = db.query(Lecturer).filter(Lecturer.canonical_name == "Vũ Thị Thủy").first()
    thuy_constraints = db.query(Constraint).filter(Constraint.lecturer_id == thuy.id).all()
    thuy_caps = db.query(LecturerCourseCapability).filter(LecturerCourseCapability.lecturer_id == thuy.id).all()
    assert len(thuy_constraints) > 0
    assert len(thuy_caps) > 0

def test_import_twice_no_duplicates(database):
    db = database
    sem = _semester(db)
    schedule_file = Path('/Users/mac/AI/Huce_timetable/INPUT Gốc/Phan_Cong_Giang_Day_HK1_2026_2027.xlsx')
    pref_file = Path('/Users/mac/AI/Huce_timetable/INPUT Gốc/Phieu_Nguyen_Vong_Giang_Vien_2026_2027_Chuan_Hoa.xlsx')

    db.add(Lecturer(canonical_name="Nguyễn Mai Hồng", code="0001", confirmed=True))
    db.add(Lecturer(canonical_name="Nguyễn Văn Tuyên", code="0002", confirmed=True))
    db.add(Lecturer(canonical_name="Nguyễn Thị Thuần", code="0003", confirmed=True))
    db.commit()

    _import_files_impl(db=db, paths=[schedule_file, pref_file], semester_id=sem.id, schedule_paths=[schedule_file], preference_paths=[pref_file], commit=True)
    count1 = db.query(Lecturer).count()
    
    _import_files_impl(db=db, paths=[schedule_file, pref_file], semester_id=sem.id, schedule_paths=[schedule_file], preference_paths=[pref_file], commit=True)
    count2 = db.query(Lecturer).count()
    
    assert count1 == count2
