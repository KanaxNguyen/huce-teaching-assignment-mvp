"""Add reviewable normalized preference drafts."""

from alembic import op
import sqlalchemy as sa


revision = "0005_preference_normalization_v2"
down_revision = "0004_v11_merge_status"
branch_labels = None
depends_on = None


def upgrade():
    if "normalized_preference_drafts" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "normalized_preference_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), sa.ForeignKey("semesters.id"), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), sa.ForeignKey("import_batches.id"), nullable=True),
        sa.Column("lecturer_id", sa.Integer(), sa.ForeignKey("lecturers.id"), nullable=True),
        sa.Column("lecturer_code", sa.String(30), nullable=True),
        sa.Column("lecturer_alias", sa.String(200), nullable=True),
        sa.Column("draft_kind", sa.String(30), nullable=False, server_default="CONSTRAINT"),
        sa.Column("context_type", sa.String(20), nullable=True),
        sa.Column("context_confidence", sa.String(10), nullable=True),
        sa.Column("context_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("constraint_type", sa.String(60), nullable=False),
        sa.Column("day_scope", sa.String(30), nullable=True),
        sa.Column("periods", sa.JSON(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("hardness", sa.String(10), nullable=False, server_default="soft"),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("numeric_value", sa.Float(), nullable=True),
        sa.Column("target", sa.JSON(), nullable=False),
        sa.Column("participant_codes", sa.JSON(), nullable=False),
        sa.Column("seminar_link", sa.String(100), nullable=True),
        sa.Column("source_file", sa.String(300), nullable=False),
        sa.Column("source_sheet", sa.String(100), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("source_cell", sa.String(60), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(10), nullable=False, server_default="LOW"),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("applied_constraint_id", sa.Integer(), sa.ForeignKey("constraints.id"), nullable=True),
        sa.Column("applied_seminar_id", sa.Integer(), sa.ForeignKey("seminars.id"), nullable=True),
    )
    op.create_index("ix_preference_drafts_semester_status", "normalized_preference_drafts", ["semester_id", "status"])
    op.create_index("ix_preference_drafts_batch", "normalized_preference_drafts", ["import_batch_id"])


def downgrade():
    op.drop_index("ix_preference_drafts_batch", table_name="normalized_preference_drafts")
    op.drop_index("ix_preference_drafts_semester_status", table_name="normalized_preference_drafts")
    op.drop_table("normalized_preference_drafts")
