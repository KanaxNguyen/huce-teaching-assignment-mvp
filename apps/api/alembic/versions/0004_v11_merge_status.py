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
    classes = sa.table(
        "classes",
        sa.column("merged_confirmed", sa.Boolean()),
        sa.column("merged_group_id", sa.String()),
        sa.column("merge_status", sa.String()),
    )
    op.execute(classes.update().where(classes.c.merged_confirmed.is_(True)).values(merge_status="confirmed"))
    op.execute(classes.update().where(
        classes.c.merged_confirmed.is_(False),
        classes.c.merged_group_id.is_not(None),
        classes.c.merge_status == "single",
    ).values(merge_status="candidate"))


def downgrade():
    op.drop_column("classes", "merge_status")
