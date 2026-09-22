"""Add rejected_at and rejected_reason to normalized_preference_drafts."""
from alembic import op
import sqlalchemy as sa

revision = "0007_preference_draft_rejection"
down_revision = "0006_lecturer_reference"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("normalized_preference_drafts")}
    if "rejected_at" not in columns:
        op.add_column("normalized_preference_drafts", sa.Column("rejected_at", sa.DateTime(), nullable=True))
    if "rejected_reason" not in columns:
        op.add_column("normalized_preference_drafts", sa.Column("rejected_reason", sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("normalized_preference_drafts")}
    if "rejected_reason" in columns:
        op.drop_column("normalized_preference_drafts", "rejected_reason")
    if "rejected_at" in columns:
        op.drop_column("normalized_preference_drafts", "rejected_at")
