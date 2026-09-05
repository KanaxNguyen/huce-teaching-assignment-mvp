"""Track merge review decisions explicitly."""
from alembic import op
import sqlalchemy as sa


revision = "0004_v11_merge_status"
down_revision = "0003_human_in_loop"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns("classes")}
    if "merge_status" not in columns:
        op.add_column("classes", sa.Column("merge_status", sa.String(20), nullable=False, server_default="single"))
    op.execute("UPDATE classes SET merge_status = 'confirmed' WHERE merged_confirmed = 1")
    op.execute("UPDATE classes SET merge_status = 'candidate' WHERE merged_confirmed = 0 AND merged_group_id IS NOT NULL AND merge_status = 'single'")


def downgrade():
    op.drop_column("classes", "merge_status")
