"""Department-agnostic teaching assignment capabilities, department profiles, and historical imports."""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

revision = "0009_department_agnostic_capabilities"
down_revision = "0008_source_version_authority"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # PostgreSQL enforces Alembic's default VARCHAR(32); this revision is
    # longer. Widen the bookkeeping column before Alembic records it.
    if bind.dialect.name == "postgresql":
        op.alter_column("alembic_version", "version_num", type_=sa.String(128), existing_nullable=False)
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # 1. Create departments
    if "departments" not in existing_tables:
        op.create_table(
            "departments",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("code", sa.String(50), unique=True, nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )

    # 2. Create department_profiles
    if "department_profiles" not in existing_tables:
        op.create_table(
            "department_profiles",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("department_id", sa.Integer, sa.ForeignKey("departments.id"), unique=True, nullable=False),
            sa.Column("allow_provisional_capability", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("course_capability_mode", sa.String(30), nullable=False, server_default="STRICT"),
            sa.Column("default_max_classes", sa.Integer, nullable=True),
            sa.Column("default_max_sessions_per_day", sa.Integer, nullable=True),
            sa.Column("default_max_days_per_week", sa.Integer, nullable=True),
            sa.Column("policy_config", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )

    # 3. Create historical_assignment_imports
    if "historical_assignment_imports" not in existing_tables:
        op.create_table(
            "historical_assignment_imports",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("semester_id", sa.Integer, sa.ForeignKey("semesters.id"), nullable=False),
            sa.Column("department_id", sa.Integer, sa.ForeignKey("departments.id"), nullable=True),
            sa.Column("source_version_id", sa.Integer, sa.ForeignKey("source_versions.id"), nullable=True),
            sa.Column("source_file", sa.String(300), nullable=False),
            sa.Column("source_sheet", sa.String(100), nullable=False),
            sa.Column("row_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("learned_capabilities", sa.Integer, nullable=False, server_default="0"),
            sa.Column("summary", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )

    # 4. Add department_id to semesters
    semester_cols = {c["name"] for c in inspector.get_columns("semesters")}
    with op.batch_alter_table("semesters") as batch_op:
        if "department_id" not in semester_cols:
            batch_op.add_column(sa.Column("department_id", sa.Integer, nullable=True))
            batch_op.create_foreign_key("fk_semesters_department_id", "departments", ["department_id"], ["id"])

    # 5. Add department_id to lecturers
    lecturer_cols = {c["name"] for c in inspector.get_columns("lecturers")}
    with op.batch_alter_table("lecturers") as batch_op:
        if "department_id" not in lecturer_cols:
            batch_op.add_column(sa.Column("department_id", sa.Integer, nullable=True))
            batch_op.create_foreign_key("fk_lecturers_department_id", "departments", ["department_id"], ["id"])

    # 6. Add columns to lecturer_course_capabilities
    if "lecturer_course_capabilities" in existing_tables:
        cap_cols = {c["name"] for c in inspector.get_columns("lecturer_course_capabilities")}
        with op.batch_alter_table("lecturer_course_capabilities") as batch_op:
            if "department_id" not in cap_cols:
                batch_op.add_column(sa.Column("department_id", sa.Integer, nullable=True))
                batch_op.create_foreign_key("fk_lcc_department_id", "departments", ["department_id"], ["id"])
            if "confidence" not in cap_cols:
                batch_op.add_column(sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"))
            if "evidence" not in cap_cols:
                batch_op.add_column(sa.Column("evidence", sa.JSON, nullable=False, server_default="{}"))
            if "created_at" not in cap_cols:
                batch_op.add_column(sa.Column("created_at", sa.DateTime, nullable=True, server_default=sa.func.now()))
            if "updated_at" not in cap_cols:
                batch_op.add_column(sa.Column("updated_at", sa.DateTime, nullable=True, server_default=sa.func.now()))

    # 7. Seed standard default departments if empty
    res = bind.execute(sa.text("SELECT COUNT(*) FROM departments")).scalar()
    if res == 0:
        import json
        now_iso = datetime.utcnow()
        math_cfg = json.dumps({
            "baseline_course_codes": ["390111", "390121"],
            "special_capabilities": [
                {"course_code": "398804", "lecturer_codes": ["TG000027", "0003"], "name_contains": "thuan"}
            ],
            "default_roster": [
                ["00187", "Phạm Đức Thoan"], ["00172", "Lê Viết Cường"], ["00181", "Nguyễn Xuân Linh"],
                ["00177", "Nguyễn Mai Hồng"], ["00175", "Trịnh Thị Minh Hằng"], ["00174", "Nguyễn Thị Lệ Hải"],
                ["00957", "Vũ Thị Hương Giang"], ["00182", "Nguyễn Hải Nam"], ["00184", "Nguyễn Minh Nguyệt"],
                ["00183", "Vũ Thị Ngân"], ["00180", "Trần Thị Liễu"], ["00189", "Bùi Khánh Trình"],
                ["00191", "Lương Thị Tuyết"], ["00188", "Vũ Thị Thủy"], ["00190", "Nguyễn Văn Tuyên"],
                ["00934", "Kiều Thị Thùy Linh"], ["00178", "Ngô Quang Hùng"], ["00179", "Trần Văn Khiên"],
                ["00173", "Nguyễn Bằng Giang"], ["TG000027", "Nguyễn Thị Thuần"]
            ]
        })
        bind.execute(
            sa.text(
                "INSERT INTO departments (id, code, name, description, active, created_at, updated_at) "
                "VALUES (:id, :code, :name, :description, :active, :created_at, :updated_at)"
            ),
            [
                {"id": 1, "code": "MATH", "name": "Bộ môn Toán học", "description": "Bộ môn Toán học - HUCE", "active": True, "created_at": now_iso, "updated_at": now_iso},
                {"id": 2, "code": "FOREIGN_LANGUAGES", "name": "Bộ môn Ngoại ngữ", "description": "Bộ môn Ngoại ngữ - HUCE", "active": True, "created_at": now_iso, "updated_at": now_iso},
                {"id": 3, "code": "PHYSICAL_EDUCATION", "name": "Bộ môn Giáo dục thể chất", "description": "Bộ môn Giáo dục thể chất - HUCE", "active": True, "created_at": now_iso, "updated_at": now_iso},
            ],
        )
        bind.execute(
            sa.text(
                "INSERT INTO department_profiles (department_id, allow_provisional_capability, course_capability_mode, policy_config, created_at, updated_at) "
                "VALUES (:department_id, :allow_prov, :mode, :cfg, :created_at, :updated_at)"
            ),
            [
                {"department_id": 1, "allow_prov": False, "mode": "STRICT", "cfg": math_cfg, "created_at": now_iso, "updated_at": now_iso},
                {"department_id": 2, "allow_prov": False, "mode": "STRICT", "cfg": "{}", "created_at": now_iso, "updated_at": now_iso},
                {"department_id": 3, "allow_prov": False, "mode": "STRICT", "cfg": "{}", "created_at": now_iso, "updated_at": now_iso},
            ],
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "lecturer_course_capabilities" in existing_tables:
        with op.batch_alter_table("lecturer_course_capabilities") as batch_op:
            batch_op.drop_column("updated_at")
            batch_op.drop_column("created_at")
            batch_op.drop_column("evidence")
            batch_op.drop_column("confidence")
            batch_op.drop_column("department_id")

    with op.batch_alter_table("lecturers") as batch_op:
        batch_op.drop_column("department_id")

    with op.batch_alter_table("semesters") as batch_op:
        batch_op.drop_column("department_id")

    if "historical_assignment_imports" in existing_tables:
        op.drop_table("historical_assignment_imports")
    if "department_profiles" in existing_tables:
        op.drop_table("department_profiles")
    if "departments" in existing_tables:
        op.drop_table("departments")
