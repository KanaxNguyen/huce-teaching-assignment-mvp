"""Lecturer master lifecycle and historical evidence, preserving existing references."""
from alembic import op
import sqlalchemy as sa

revision = "0006_lecturer_reference"
down_revision = "0005_preference_normalization_v2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("lecturers")}
    for column in [
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("department", sa.String(200)), sa.Column("email", sa.String(200)),
        sa.Column("note", sa.Text()), sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    ]:
        if column.name not in columns:
            op.add_column("lecturers", column)
    op.execute(sa.text("UPDATE lecturers SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL"))
    op.execute(sa.text("UPDATE lecturers SET updated_at=CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
    uniques = sa.inspect(bind).get_unique_constraints("lecturers")
    name_unique = next((u for u in uniques if u["column_names"] == ["canonical_name"]), None)
    if name_unique:
        with op.batch_alter_table("lecturers", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}) as batch:
            batch.drop_constraint(name_unique["name"] or "uq_lecturers_canonical_name", type_="unique")
    profile_columns = {c["name"] for c in sa.inspect(bind).get_columns("output_template_profiles")}
    if "profile_type" not in profile_columns:
        op.add_column("output_template_profiles", sa.Column("profile_type", sa.String(40), nullable=False, server_default="DETAILED_ASSIGNMENT"))
        # Matrix profiles have only a lecturer mapping; no source files need opening.
        profiles = sa.table("output_template_profiles", sa.column("id", sa.Integer), sa.column("mappings", sa.JSON), sa.column("profile_type", sa.String))
        for row in bind.execute(sa.select(profiles.c.id, profiles.c.mappings)):
            if row.mappings and set(row.mappings) == {"lecturer"}:
                bind.execute(profiles.update().where(profiles.c.id == row.id).values(profile_type="LECTURER_WEEK_MATRIX"))
    tables = set(sa.inspect(bind).get_table_names())
    if "lecturer_aliases" not in tables:
        op.create_table("lecturer_aliases",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("lecturer_id", sa.Integer, sa.ForeignKey("lecturers.id"), nullable=False),
            sa.Column("alias_text", sa.String(300), nullable=False),
            sa.Column("normalized_alias", sa.String(300), nullable=False, unique=True),
            sa.Column("source", sa.String(300), nullable=False),
            sa.Column("confirmed", sa.Boolean, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False))
    if "lecturer_semester_profiles" not in tables:
        op.create_table("lecturer_semester_profiles",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("semester_id", sa.Integer, sa.ForeignKey("semesters.id"), nullable=False),
            sa.Column("lecturer_id", sa.Integer, sa.ForeignKey("lecturers.id"), nullable=False),
            sa.Column("participation_status", sa.String(30), nullable=False),
            sa.Column("target_workload", sa.Float), sa.Column("min_workload", sa.Float),
            sa.Column("max_workload", sa.Float), sa.Column("note", sa.Text),
            sa.UniqueConstraint("semester_id", "lecturer_id"))
    if "historical_evidence" not in tables:
        op.create_table("historical_evidence",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("semester_id", sa.Integer, sa.ForeignKey("semesters.id"), nullable=False),
            sa.Column("profile_id", sa.Integer, sa.ForeignKey("output_template_profiles.id"), nullable=False),
            sa.Column("lecturer_id", sa.Integer, sa.ForeignKey("lecturers.id")),
            sa.Column("source_text", sa.Text, nullable=False), sa.Column("lecturer_code", sa.String(30)),
            sa.Column("source_row", sa.Integer, nullable=False), sa.Column("source_cell", sa.String(60), nullable=False),
            sa.Column("evidence", sa.JSON, nullable=False), sa.Column("status", sa.String(40), nullable=False),
            sa.Column("human_confirmed", sa.Boolean, nullable=False))
    if "lecturer_identity_audit" not in tables:
        op.create_table("lecturer_identity_audit",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("source_lecturer_id", sa.Integer, sa.ForeignKey("lecturers.id"), nullable=False),
            sa.Column("target_lecturer_id", sa.Integer, sa.ForeignKey("lecturers.id"), nullable=False),
            sa.Column("action", sa.String(30), nullable=False), sa.Column("snapshot", sa.JSON, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False))


def downgrade():
    raise RuntimeError("Restore a verified backup to downgrade lecturer identity changes without data loss.")
