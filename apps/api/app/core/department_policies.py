"""Department policies, default profiles, and resolution helpers."""
from __future__ import annotations

import re
from typing import Any
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.entities import Department, DepartmentProfile, Semester

# Default configurations for HUCE academic departments
DEFAULT_DEPARTMENT_POLICIES: dict[str, dict[str, Any]] = {
    "MATH": {
        "code": "MATH",
        "name": "Bộ môn Toán học",
        "description": "Bộ môn Toán học - Khoa CNTT / HUCE",
        "allow_provisional_capability": False,
        "course_capability_mode": "STRICT",
        "policy_config": {
            "baseline_course_codes": ["390111", "390121"],
            "special_capabilities": [
                {"course_code": "398804", "lecturer_codes": ["TG000027", "0003"], "name_contains": "thuan"}
            ],
            "default_roster": [
                ("00187", "Phạm Đức Thoan"), ("00172", "Lê Viết Cường"), ("00181", "Nguyễn Xuân Linh"),
                ("00177", "Nguyễn Mai Hồng"), ("00175", "Trịnh Thị Minh Hằng"), ("00174", "Nguyễn Thị Lệ Hải"),
                ("00957", "Vũ Thị Hương Giang"), ("00182", "Nguyễn Hải Nam"), ("00184", "Nguyễn Minh Nguyệt"),
                ("00183", "Vũ Thị Ngân"), ("00180", "Trần Thị Liễu"), ("00189", "Bùi Khánh Trình"),
                ("00191", "Lương Thị Tuyết"), ("00188", "Vũ Thị Thủy"), ("00190", "Nguyễn Văn Tuyên"),
                ("00934", "Kiều Thị Thùy Linh"), ("00178", "Ngô Quang Hùng"), ("00179", "Trần Văn Khiên"),
                ("00173", "Nguyễn Bằng Giang"), ("TG000027", "Nguyễn Thị Thuần")
            ],
        },
    },
    "FOREIGN_LANGUAGES": {
        "code": "FOREIGN_LANGUAGES",
        "name": "Bộ môn Ngoại ngữ",
        "description": "Bộ môn Ngoại ngữ - HUCE",
        "allow_provisional_capability": False,
        "course_capability_mode": "STRICT",
        "policy_config": {},
    },
    "PHYSICAL_EDUCATION": {
        "code": "PHYSICAL_EDUCATION",
        "name": "Bộ môn Giáo dục thể chất",
        "description": "Bộ môn Giáo dục thể chất - HUCE",
        "allow_provisional_capability": False,
        "course_capability_mode": "STRICT",
        "policy_config": {},
    },
    "ENGINEERING": {
        "code": "ENGINEERING",
        "name": "Khoa Kỹ thuật",
        "description": "Khoa Kỹ thuật - HUCE",
        "allow_provisional_capability": False,
        "course_capability_mode": "STRICT",
        "policy_config": {},
    },
}


def _guess_department_code(raw_name: str) -> str | None:
    norm = raw_name.strip().casefold()
    if any(k in norm for k in ["toán", "toan", "math"]):
        return "MATH"
    if any(k in norm for k in ["ngoại ngữ", "ngoai ngu", "foreign", "tiếng anh"]):
        return "FOREIGN_LANGUAGES"
    if any(k in norm for k in ["thể chất", "the chat", "pe", "sport", "thể dục"]):
        return "PHYSICAL_EDUCATION"
    if any(k in norm for k in ["kỹ thuật", "ky thuat", "engineer"]):
        return "ENGINEERING"
    return None


def resolve_or_create_department(
    db: Session,
    name_or_code: str | None = None,
    department_id: int | None = None,
) -> Department | None:
    """Resolve an existing Department or create one with default profile if absent."""
    if department_id is not None:
        dept = db.get(Department, department_id)
        if dept:
            # Ensure profile exists
            if not dept.profile:
                _ensure_department_profile(db, dept)
            return dept

    if not name_or_code:
        return None

    cleaned = name_or_code.strip()
    dept = db.scalar(
        select(Department).where(or_(Department.code == cleaned, Department.name == cleaned))
    )
    if not dept:
        code_guess = _guess_department_code(cleaned)
        if code_guess:
            dept = db.scalar(select(Department).where(Department.code == code_guess))

    if not dept:
        # Create department
        code_guess = _guess_department_code(cleaned)
        defaults = DEFAULT_DEPARTMENT_POLICIES.get(code_guess or "")
        code = defaults["code"] if defaults else re.sub(r"[^A-Za-z0-9_]+", "_", cleaned.upper())[:40] or "DEPT"
        # Check code collision
        collision = db.scalar(select(Department).where(Department.code == code))
        if collision:
            import time
            code = f"{code}_{int(time.time())}"

        name = defaults["name"] if defaults else cleaned
        desc = defaults.get("description") if defaults else f"Bộ môn {name}"
        dept = Department(name=name, code=code, description=desc, active=True)
        db.add(dept)
        db.flush()

    _ensure_department_profile(db, dept)
    return dept


def _ensure_department_profile(db: Session, dept: Department) -> DepartmentProfile:
    profile = db.scalar(select(DepartmentProfile).where(DepartmentProfile.department_id == dept.id))
    if not profile:
        defaults = DEFAULT_DEPARTMENT_POLICIES.get(dept.code, {})
        profile = DepartmentProfile(
            department_id=dept.id,
            allow_provisional_capability=defaults.get("allow_provisional_capability", False),
            course_capability_mode=defaults.get("course_capability_mode", "STRICT"),
            policy_config=defaults.get("policy_config", {}),
        )
        db.add(profile)
        db.flush()
    return profile


def get_department_profile_for_semester(db: Session, semester: Semester | None) -> DepartmentProfile | None:
    """Retrieve the department profile for a semester, auto-resolving department if needed."""
    if not semester:
        return None

    dept_id = semester.department_id
    if not dept_id and semester.department_name:
        dept = resolve_or_create_department(db, semester.department_name)
        if dept:
            semester.department_id = dept.id
            dept_id = dept.id
            db.flush()

    if not dept_id:
        return None

    profile = db.scalar(select(DepartmentProfile).where(DepartmentProfile.department_id == dept_id))
    if not profile:
        dept = db.get(Department, dept_id)
        if dept:
            profile = _ensure_department_profile(db, dept)
    return profile
