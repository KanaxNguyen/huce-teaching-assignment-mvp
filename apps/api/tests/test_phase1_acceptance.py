from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.api.routes import get_assignments, get_constraints, get_latest_template, get_optimization_runs
from app.db.session import Base, SessionLocal, engine
from app.models.entities import Assignment, ClassSection, Constraint, Course, ImportBatch, Lecturer, LecturerCourseCapability, NormalizedPreferenceDraft, OptimizationRun, OutputTemplateProfile, Semester, Seminar, ValidationIssue
from app.parsers.preferences import ParsedPreference
from app.parsers.schedule import ParsedClass, ParsedSession, ScheduleParseResult
from app.services import importer
from app.optimization.solver import solve


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def semester(db, name):
    row = Semester(name=name, department_name="D", start_date=date(2026, 1, 1), end_date=date(2026, 6, 1), head_name="H")
    db.add(row); db.commit(); return row


def parsed(version, lecturer=True):
    meeting = ParsedSession(2, 1, 3, f"P-{version}", date(2026, 1, 1), date(2026, 6, 1), "123", [1, 2, 3], 3)
    group = ParsedClass("MATH", f"Math {version}", f"L-{version}", 3, "GV01" if lecturer else None, "Teacher One" if lecturer else None, lecturer, "schedule.xlsx", "S", 3, {"version": version}, [meeting])
    return ScheduleParseResult([group], [], [], 1, 0, 1)


def preference(version):
    return ParsedPreference("Teacher One", "Teacher One", 3, "unavailable", {"weekday": 3, "periods": [1, 2, 3]}, f"constraint-{version}", .9, 4)


def run_import(monkeypatch, db, sid, version, lecturer=True):
    monkeypatch.setattr(importer, "parse_schedule", lambda _: parsed(version, lecturer))
    monkeypatch.setattr(importer, "parse_preferences", lambda _: [preference(version)] if lecturer else [])
    return importer.import_files(db, [Path("schedule.xlsx"), Path("preference.xlsx")], semester_id=sid, schedule_paths=[Path("schedule.xlsx")], preference_paths=[Path("preference.xlsx")])


def snapshot(db, sid):
    classes = db.scalars(select(ClassSection).where(ClassSection.semester_id == sid).order_by(ClassSection.id)).all()
    return {
        "classes": [(x.id, x.class_code, x.course_id, x.assigned_lecturer_id, x.raw_values, [(s.id, s.room) for s in x.sessions]) for x in classes],
        "constraints": [(x.id, x.name, x.raw_text) for x in db.scalars(select(Constraint).where(Constraint.semester_id == sid).order_by(Constraint.id))],
        "seminars": [(x.id, x.name, x.hardness) for x in db.scalars(select(Seminar).where(Seminar.semester_id == sid).order_by(Seminar.id))],
        "issues": [(x.id, x.code, x.message) for x in db.scalars(select(ValidationIssue).where(ValidationIssue.semester_id == sid).order_by(ValidationIssue.id))],
        "batches": [(x.id, x.source_files, x.summary) for x in db.scalars(select(ImportBatch).where(ImportBatch.semester_id == sid).order_by(ImportBatch.id))],
        "runs": [(x.id, x.status) for x in db.scalars(select(OptimizationRun).where(OptimizationRun.semester_id == sid).order_by(OptimizationRun.id))],
        "assignments": [(x.id, x.run_id, x.class_id) for x in db.scalars(select(Assignment).where(Assignment.semester_id == sid).order_by(Assignment.id))],
        "templates": [(x.id, x.source_file) for x in db.scalars(select(OutputTemplateProfile).where(OutputTemplateProfile.semester_id == sid).order_by(OutputTemplateProfile.id))],
    }


def test_import_b_preserves_a(monkeypatch):
    with SessionLocal() as db:
        a = semester(db, "A"); run_import(monkeypatch, db, a.id, "A")
        klass = db.scalar(select(ClassSection).where(ClassSection.semester_id == a.id)); teacher = db.scalar(select(Lecturer).where(Lecturer.code == "GV01"))
        run = OptimizationRun(semester_id=a.id, status="optimal", summary={}); db.add(run); db.flush()
        db.add_all([Assignment(semester_id=a.id, run_id=run.id, class_id=klass.id, lecturer_id=teacher.id), OutputTemplateProfile(semester_id=a.id, source_file="A.xlsx", source_sheet="S", header_row=1)]); db.commit()
        before = snapshot(db, a.id); b = semester(db, "B"); run_import(monkeypatch, db, b.id, "B")
        assert snapshot(db, a.id) == before
        assert all(x.semester_id == b.id for x in db.scalars(select(ClassSection).where(ClassSection.semester_id == b.id)))


def test_reimport_is_scoped_and_preserves_masters(monkeypatch):
    with SessionLocal() as db:
        a, b = semester(db, "A"), semester(db, "B"); run_import(monkeypatch, db, a.id, "A"); run_import(monkeypatch, db, b.id, "B")
        before_b = snapshot(db, b.id); teacher_id = db.scalar(select(Lecturer.id).where(Lecturer.code == "GV01")); course_id = db.scalar(select(Course.id).where(Course.code == "MATH"))
        run_import(monkeypatch, db, a.id, "A2")
        assert snapshot(db, b.id) == before_b
        assert db.scalar(select(ClassSection.class_code).where(ClassSection.semester_id == a.id)) == "L-A2"
        assert db.scalar(select(Lecturer.id).where(Lecturer.code == "GV01")) == teacher_id
        assert db.scalar(select(Course.id).where(Course.code == "MATH")) == course_id
        assert db.query(LecturerCourseCapability).count() == 1


def test_capability_is_preserved_and_ambiguous_preference_is_flagged(monkeypatch):
    with SessionLocal() as db:
        a = semester(db, "A")
        run_import(monkeypatch, db, a.id, "A")
        monkeypatch.setattr(importer, "parse_preferences", lambda _: [ParsedPreference("Unknown", "Unknown", None, "unavailable", {}, "unknown", .4, 4)])
        importer.import_files(db, [Path("schedule.xlsx"), Path("preference.xlsx")], semester_id=a.id, schedule_paths=[Path("schedule.xlsx")], preference_paths=[Path("preference.xlsx")])
        assert db.query(LecturerCourseCapability).count() == 1
        assert db.scalar(select(ValidationIssue.code).where(ValidationIssue.semester_id == a.id, ValidationIssue.code == "LECTURER_IDENTITY_AMBIGUOUS"))


def test_confirmed_alias_matches_existing_lecturer_without_creating_a_duplicate(monkeypatch):
    with SessionLocal() as db:
        a = semester(db, "A")
        run_import(monkeypatch, db, a.id, "A")
        teacher = db.scalar(select(Lecturer).where(Lecturer.code == "GV01"))
        teacher.aliases = ["T. One"]
        db.commit()
        monkeypatch.setattr(importer, "parse_preferences", lambda _: [ParsedPreference("T. One", "T. One", 2, "unavailable", {"weekday": 2, "periods": [1, 2, 3]}, "no Tuesday", .9, 4)])
        importer.import_files(db, [Path("schedule.xlsx"), Path("preference.xlsx")], semester_id=a.id, schedule_paths=[Path("schedule.xlsx")], preference_paths=[Path("preference.xlsx")])
        assert db.query(Lecturer).count() == 1
        assert db.scalar(select(NormalizedPreferenceDraft.lecturer_id).where(NormalizedPreferenceDraft.semester_id == a.id)) == teacher.id
        assert db.scalar(select(Constraint).where(Constraint.semester_id == a.id)) is None


def test_many_rows_form_one_teaching_group_and_many_meetings(monkeypatch):
    with SessionLocal() as db:
        a = semester(db, "A")
        monkeypatch.setattr(importer, "parse_schedule", lambda _: ScheduleParseResult([ParsedClass("M", "Math", "L", 3, None, None, False, "f", "s", 1, {}, [ParsedSession(2, 1, 3, "P1", None, None, "1", [1], 1), ParsedSession(3, 4, 6, "P2", None, None, "1", [1], 2)], merged_group_id="MG-1")], [], [], 2, 0, 1))
        monkeypatch.setattr(importer, "parse_preferences", lambda _: [])
        importer.import_files(db, [Path("schedule.xlsx")], semester_id=a.id, schedule_paths=[Path("schedule.xlsx")], preference_paths=[])
        assert db.query(ClassSection).filter_by(semester_id=a.id).count() == 1
        section = db.query(ClassSection).filter_by(semester_id=a.id).one()
        assert len(section.sessions) == 2
        assert section.merged_group_id == "MG-1" and section.merged_confirmed is False


def test_atomic_rollback_after_persistence_started(monkeypatch):
    with SessionLocal() as db:
        a = semester(db, "A"); aid = a.id; run_import(monkeypatch, db, aid, "A"); before = snapshot(db, aid)
        monkeypatch.setattr(importer, "parse_schedule", lambda _: parsed("BROKEN")); monkeypatch.setattr(importer, "parse_preferences", lambda _: [preference("BROKEN")])
        original_flush = db.flush; calls = 0
        def failing_flush(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 4: raise RuntimeError("forced persistence failure")
            return original_flush(*args, **kwargs)
        monkeypatch.setattr(db, "flush", failing_flush)
        with pytest.raises(RuntimeError): importer.import_files(db, [Path("schedule.xlsx"), Path("preference.xlsx")], semester_id=aid, schedule_paths=[Path("schedule.xlsx")], preference_paths=[Path("preference.xlsx")])
    with SessionLocal() as verify:
        assert snapshot(verify, aid) == before
        assert verify.scalars(select(ImportBatch).where(ImportBatch.semester_id == aid)).all()


def test_constraint_isolation_api():
    with SessionLocal() as db:
        a, b = semester(db, "A"), semester(db, "B"); teacher = Lecturer(code="TX", canonical_name="X"); db.add(teacher); db.flush()
        db.add_all([Constraint(semester_id=a.id, name="A", constraint_type="unavailable", lecturer_id=teacher.id), Constraint(semester_id=b.id, name="B", constraint_type="unavailable", lecturer_id=teacher.id)]); db.commit()
        assert [x["name"] for x in get_constraints(a.id, db)] == ["A"]
        assert [x["name"] for x in get_constraints(b.id, db)] == ["B"]


def test_solver_loads_constraints_only_from_target_semester(monkeypatch):
    with SessionLocal() as db:
        a, b = semester(db, "A"), semester(db, "B")
        run_import(monkeypatch, db, a.id, "A"); run_import(monkeypatch, db, b.id, "B")
        teacher = db.scalar(select(Lecturer).where(Lecturer.code == "GV01"))
        b_constraint = Constraint(semester_id=b.id, lecturer_id=teacher.id, name="B only", constraint_type="unavailable", hardness="hard", weight=1, target={"weekday": 2, "periods": [1, 2, 3]}, confirmed=True)
        db.add(b_constraint); db.commit()
        assert solve(db, 2, False, a.id).status in {"optimal", "feasible"}
        run_b = solve(db, 2, False, b.id)
        assert run_b.status in {"optimal", "feasible"}
        assert run_b.summary["unassigned"]


def test_run_assignment_and_template_isolation():
    with SessionLocal() as db:
        a, b = semester(db, "A"), semester(db, "B"); t = Lecturer(code="T", canonical_name="T"); c = Course(code="C", name="C"); db.add_all([t, c]); db.flush()
        ca = ClassSection(semester_id=a.id, course_id=c.id, class_code="A", source_file="f", source_sheet="s", source_row=1); cb = ClassSection(semester_id=b.id, course_id=c.id, class_code="B", source_file="f", source_sheet="s", source_row=1); db.add_all([ca, cb]); db.flush()
        ra = OptimizationRun(semester_id=a.id, status="optimal", summary={}); rb = OptimizationRun(semester_id=b.id, status="optimal", summary={}); db.add_all([ra, rb]); db.flush()
        db.add_all([Assignment(semester_id=a.id, run_id=ra.id, class_id=ca.id, lecturer_id=t.id), Assignment(semester_id=b.id, run_id=rb.id, class_id=cb.id, lecturer_id=t.id), OutputTemplateProfile(semester_id=a.id, source_file="A.xlsx", source_sheet="S", header_row=1), OutputTemplateProfile(semester_id=b.id, source_file="B.xlsx", source_sheet="S", header_row=1)]); db.commit()
        assert [x["id"] for x in get_optimization_runs(a.id, db)] == [ra.id]
        assert [x["class_code"] for x in get_assignments(a.id, db)] == ["A"]
        assert get_latest_template(a.id, db)["source_file"] == "A.xlsx"
        assert get_latest_template(b.id, db)["source_file"] == "B.xlsx"


def test_foreign_keys_are_enabled_by_application_engine():
    with engine.connect() as connection: assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    with SessionLocal() as db:
        db.add(OutputTemplateProfile(semester_id=999999, source_file="x", source_sheet="s", header_row=1))
        with pytest.raises(IntegrityError): db.commit()


def test_semester_delete_is_restricted_and_masters_survive():
    with SessionLocal() as db:
        a = semester(db, "A"); t = Lecturer(code="T", canonical_name="T"); c = Course(code="C", name="C"); db.add_all([t, c]); db.flush(); db.add(ClassSection(semester_id=a.id, course_id=c.id, class_code="A", source_file="f", source_sheet="s", source_row=1)); db.commit()
        with pytest.raises(IntegrityError): db.execute(delete(Semester).where(Semester.id == a.id))
        db.rollback(); assert db.get(Lecturer, t.id) and db.get(Course, c.id) and db.get(Semester, a.id)


def test_end_to_end_multi_semester_isolation(monkeypatch):
    with SessionLocal() as db:
        a, b = semester(db, "A"), semester(db, "B")
        run_import(monkeypatch, db, a.id, "A")
        run_import(monkeypatch, db, b.id, "B")
        run_import(monkeypatch, db, a.id, "A2")
        db.add_all([
            OutputTemplateProfile(semester_id=a.id, source_file="A2.xlsx", source_sheet="S", header_row=1),
            OutputTemplateProfile(semester_id=b.id, source_file="B.xlsx", source_sheet="S", header_row=1),
        ]); db.commit()
        stable_a = snapshot(db, a.id)
        result = solve(db, 2, False, b.id)
        assert result.semester_id == b.id
        assert get_assignments(a.id, db) == []
        assert [x["class_code"] for x in get_assignments(b.id, db)] == ["L-B"]
        assert get_latest_template(a.id, db)["source_file"] == "A2.xlsx"
        assert get_latest_template(b.id, db)["source_file"] == "B.xlsx"
        assert snapshot(db, a.id) == stable_a
