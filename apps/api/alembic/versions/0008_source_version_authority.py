"""Immutable source files, explicit activation and additive provenance."""
from alembic import op
import sqlalchemy as sa

revision = "0008_source_version_authority"
down_revision = "0007_preference_draft_rejection"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "source_versions" not in sa.inspect(bind).get_table_names():
        op.create_table("source_versions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("semester_id", sa.Integer, sa.ForeignKey("semesters.id"), nullable=False),
            sa.Column("import_batch_id", sa.Integer, sa.ForeignKey("import_batches.id")),
            sa.Column("source_type", sa.String(30), nullable=False),
            sa.Column("original_filename", sa.String(300), nullable=False),
            sa.Column("storage_ref", sa.String(600)),
            sa.Column("content_hash", sa.String(64)),
            sa.Column("provenance_status", sa.String(30), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("parent_version_id", sa.Integer, sa.ForeignKey("source_versions.id")),
            sa.Column("parse_summary", sa.JSON, nullable=False))

    additions = {
        "semesters": [sa.Column("active_schedule_source_id", sa.Integer), sa.Column("active_preference_source_id", sa.Integer), sa.Column("source_revision", sa.Integer, nullable=False, server_default="0")],
        "sessions": [sa.Column("source_rows", sa.JSON, nullable=False, server_default="[]")],
        "validation_issues": [sa.Column("details", sa.JSON, nullable=False, server_default="{}"), sa.Column("resolution_status", sa.String(40), nullable=False, server_default="OPEN")],
        "optimization_runs": [sa.Column("schedule_source_id", sa.Integer), sa.Column("preference_source_id", sa.Integer), sa.Column("source_revision", sa.Integer, nullable=False, server_default="0")],
    }
    for table in ("classes", "sessions", "normalized_preference_drafts", "output_template_profiles", "historical_evidence", "validation_issues", "constraints", "seminars"):
        additions.setdefault(table, []).append(sa.Column("source_version_id", sa.Integer))
    for table, columns in additions.items():
        existing = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        foreign_keys = {tuple(f["constrained_columns"]) for f in sa.inspect(bind).get_foreign_keys(table)}
        with op.batch_alter_table(table) as batch:
            for column in columns:
                if column.name not in existing:
                    batch.add_column(column)
                if column.name.endswith("source_id") or column.name == "source_version_id":
                    if (column.name,) not in foreign_keys:
                        batch.create_foreign_key(f"fk_{table}_{column.name}", "source_versions", [column.name], ["id"])
    # NULL lineage intentionally means LEGACY/UNVERIFIED. Never infer workbook
    # ownership from filename or fabricate a content hash for old rows.


def downgrade():
    raise RuntimeError("Restore a verified backup; source provenance must not be discarded.")
