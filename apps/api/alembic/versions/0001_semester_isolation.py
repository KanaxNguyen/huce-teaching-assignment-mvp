"""Add semester ownership to transactional data."""
from alembic import op
import sqlalchemy as sa
from pathlib import Path

revision = "0001_semester_isolation"
down_revision = None
branch_labels = None
depends_on = None


def _create_fresh_portable_schema():
    """Frozen revision-0001 schema expressed with portable Alembic types."""
    op.create_table("courses", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(50), nullable=False, unique=True), sa.Column("name", sa.String(300), nullable=False))
    op.create_table("lecturers", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(30), unique=True), sa.Column("canonical_name", sa.String(200), nullable=False, unique=True), sa.Column("aliases", sa.JSON(), nullable=False), sa.Column("confirmed", sa.Boolean(), nullable=False), sa.Column("max_credits", sa.Float(), nullable=False), sa.Column("source_file", sa.String(300)), sa.Column("source_sheet", sa.String(100)), sa.Column("source_row", sa.Integer()))
    op.create_table("semesters", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("department_name", sa.String(200), nullable=False), sa.Column("start_date", sa.Date(), nullable=False), sa.Column("end_date", sa.Date(), nullable=False), sa.Column("head_name", sa.String(200), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("classes", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("semester_id", sa.Integer(), sa.ForeignKey("semesters.id"), nullable=False), sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False), sa.Column("class_code", sa.String(100), nullable=False), sa.Column("credits", sa.Float(), nullable=False), sa.Column("merged_group_id", sa.String(100)), sa.Column("merged_confirmed", sa.Boolean(), nullable=False), sa.Column("locked_assignment", sa.Boolean(), nullable=False), sa.Column("assigned_lecturer_id", sa.Integer(), sa.ForeignKey("lecturers.id")), sa.Column("source_file", sa.String(300), nullable=False), sa.Column("source_sheet", sa.String(100), nullable=False), sa.Column("source_row", sa.Integer(), nullable=False), sa.Column("raw_values", sa.JSON(), nullable=False), sa.UniqueConstraint("semester_id", "course_id", "class_code"))
    op.create_table("constraints", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("semester_id", sa.Integer(), sa.ForeignKey("semesters.id"), nullable=False), sa.Column("name", sa.String(200), nullable=False), sa.Column("constraint_type", sa.String(50), nullable=False), sa.Column("hardness", sa.String(10), nullable=False), sa.Column("weight", sa.Float(), nullable=False), sa.Column("lecturer_id", sa.Integer(), sa.ForeignKey("lecturers.id")), sa.Column("target", sa.JSON(), nullable=False), sa.Column("raw_text", sa.Text()), sa.Column("confirmed", sa.Boolean(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False))
    op.create_table("import_batches", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("semester_id", sa.Integer(), sa.ForeignKey("semesters.id"), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("source_files", sa.JSON(), nullable=False), sa.Column("summary", sa.JSON(), nullable=False))
    op.create_table("optimization_runs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("semester_id", sa.Integer(), sa.ForeignKey("semesters.id"), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("score", sa.Float()), sa.Column("summary", sa.JSON(), nullable=False))
    op.create_table("output_template_profiles", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("semester_id", sa.Integer(), sa.ForeignKey("semesters.id"), nullable=False), sa.Column("source_file", sa.String(300), nullable=False), sa.Column("source_sheet", sa.String(100), nullable=False), sa.Column("header_row", sa.Integer(), nullable=False), sa.Column("mappings", sa.JSON(), nullable=False), sa.Column("missing_fields", sa.JSON(), nullable=False), sa.Column("preview", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("seminars", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("semester_id", sa.Integer(), sa.ForeignKey("semesters.id"), nullable=False), sa.Column("name", sa.String(200), nullable=False), sa.Column("chair_name", sa.String(200), nullable=False), sa.Column("members", sa.JSON(), nullable=False), sa.Column("alternatives", sa.JSON(), nullable=False), sa.Column("weight", sa.Float(), nullable=False), sa.Column("hardness", sa.String(10), nullable=False))
    op.create_table("validation_issues", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("semester_id", sa.Integer(), sa.ForeignKey("semesters.id"), nullable=False), sa.Column("severity", sa.String(20), nullable=False), sa.Column("code", sa.String(60), nullable=False), sa.Column("message", sa.Text(), nullable=False), sa.Column("source_file", sa.String(300)), sa.Column("source_sheet", sa.String(100)), sa.Column("source_row", sa.Integer()), sa.Column("field", sa.String(100)), sa.Column("raw_value", sa.Text()), sa.Column("suggestion", sa.Text()))
    op.create_table("assignments", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("semester_id", sa.Integer(), sa.ForeignKey("semesters.id"), nullable=False), sa.Column("run_id", sa.Integer(), sa.ForeignKey("optimization_runs.id"), nullable=False), sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=False), sa.Column("lecturer_id", sa.Integer(), sa.ForeignKey("lecturers.id"), nullable=False), sa.Column("locked", sa.Boolean(), nullable=False), sa.Column("penalty", sa.Float(), nullable=False), sa.UniqueConstraint("run_id", "class_id"))
    op.create_table("sessions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=False), sa.Column("weekday", sa.Integer(), nullable=False), sa.Column("start_period", sa.Integer(), nullable=False), sa.Column("end_period", sa.Integer(), nullable=False), sa.Column("room", sa.String(200), nullable=False), sa.Column("start_date", sa.Date()), sa.Column("end_date", sa.Date()), sa.Column("raw_weeks", sa.String(80), nullable=False), sa.Column("active_weeks", sa.JSON(), nullable=False), sa.Column("source_row", sa.Integer(), nullable=False))


def upgrade():
    bind = op.get_bind()
    # Must be disabled before the first metadata query/transaction for the
    # SQLite table rebuild below; changing it after a transaction starts is a
    # no-op in SQLite.
    dialect = bind.dialect.name
    if dialect == "sqlite":
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "import_batches" not in tables and "classes" not in tables:
        # Historical migrations must not create tables/columns from later
        # ORM revisions: 0002 and 0003 own those additions.
        if dialect == "sqlite":
            schema = Path(__file__).resolve().parents[1] / "schema_0001.sql"
            sql = "\n".join(line for line in schema.read_text().splitlines()
                            if not line.lstrip().startswith("--"))
            for statement in sql.split(";"):
                if statement.strip():
                    bind.exec_driver_sql(statement)
        else:
            _create_fresh_portable_schema()
        return
    if dialect != "sqlite":
        raise RuntimeError("Pre-Alembic legacy upgrades are supported only for the existing SQLite database.")
    if "semesters" not in tables:
        op.create_table(
            "semesters",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("department_name", sa.String(200), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("head_name", sa.String(200), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        tables.add("semesters")
    current = bind.execute(sa.text("SELECT id FROM semesters ORDER BY is_active DESC, id DESC LIMIT 1")).scalar()
    if current is None:
        bind.execute(sa.text("INSERT INTO semesters (name, department_name, start_date, end_date, head_name, status, is_active, created_at) VALUES (:name, :department, :start, :end, 'Chưa xác định', 'draft', 1, CURRENT_TIMESTAMP)"), {"name": "Kỳ dữ liệu cũ", "department": "Chưa xác định", "start": "2000-01-01", "end": "2099-12-31"})
        current = bind.execute(sa.text("SELECT id FROM semesters ORDER BY id DESC LIMIT 1")).scalar()
    owned_tables = ("import_batches", "output_template_profiles", "classes", "constraints", "seminars", "validation_issues", "optimization_runs", "assignments")
    for table in owned_tables:
        if table not in tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "semester_id" not in columns:
            op.add_column(table, sa.Column("semester_id", sa.Integer(), nullable=True))
        bind.execute(sa.text(f"UPDATE {table} SET semester_id = :semester WHERE semester_id IS NULL"), {"semester": current})
    inspector = sa.inspect(bind)
    for table in ("import_batches", "output_template_profiles", "constraints", "seminars", "validation_issues", "optimization_runs", "assignments"):
        if table not in tables:
            continue
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.alter_column("semester_id", existing_type=sa.Integer(), nullable=False)
            batch.create_foreign_key(f"fk_{table}_semester", "semesters", ["semester_id"], ["id"])
    # Rebuild classes explicitly so the old anonymous SQLite UNIQUE index on
    # (course_id, class_code) cannot prevent the same class code in another
    # semester. The child sessions keep their class_id values.
    op.execute("CREATE TABLE classes_phase1 (id INTEGER NOT NULL PRIMARY KEY, semester_id INTEGER NOT NULL, course_id INTEGER NOT NULL, class_code VARCHAR(100) NOT NULL, credits FLOAT NOT NULL, merged_group_id VARCHAR(100), merged_confirmed BOOLEAN NOT NULL, locked_assignment BOOLEAN NOT NULL, assigned_lecturer_id INTEGER, source_file VARCHAR(300) NOT NULL, source_sheet VARCHAR(100) NOT NULL, source_row INTEGER NOT NULL, raw_values JSON NOT NULL, CONSTRAINT uq_classes_semester_course_code UNIQUE (semester_id, course_id, class_code), FOREIGN KEY(semester_id) REFERENCES semesters (id), FOREIGN KEY(course_id) REFERENCES courses (id), FOREIGN KEY(assigned_lecturer_id) REFERENCES lecturers (id))")
    op.execute("INSERT INTO classes_phase1 SELECT id, semester_id, course_id, class_code, credits, merged_group_id, merged_confirmed, locked_assignment, assigned_lecturer_id, source_file, source_sheet, source_row, raw_values FROM classes")
    op.execute("DROP TABLE classes")
    op.execute("ALTER TABLE classes_phase1 RENAME TO classes")
    # New application connections enable foreign keys through db/session.py.


def downgrade():
    raise RuntimeError("Restore the pre-Phase-1 backup instead of dropping semester ownership.")
