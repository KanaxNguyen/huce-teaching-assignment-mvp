"""Add current assignment source and snapshot source."""
from alembic import op
import sqlalchemy as sa

revision = "0003_human_in_loop"
down_revision = "0002_domain_correctness"
branch_labels = None
depends_on = None

def upgrade():
    # SQLite DDL is non-transactional.  A prior interrupted startup can leave
    # one column in place while Alembic still records revision 0002.  Treat
    # that state as a resumable migration instead of preventing the API from
    # starting forever.
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("classes")}
    if "assignment_source" not in existing:
        op.add_column("classes", sa.Column("assignment_source", sa.String(20), nullable=True))
    columns = {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns("assignments")}
    if "source" not in columns:
        op.add_column("assignments", sa.Column("source", sa.String(20), nullable=False, server_default="SOLVER"))
    else:
        # A partially applied or pre-created column may lack the migration's
        # NOT NULL/default. Preserve known sources and backfill only NULLs.
        op.execute("UPDATE assignments SET source = 'SOLVER' WHERE source IS NULL")
        source = columns["source"]
        if source["nullable"] or str(source["default"]).strip("'\"") != "SOLVER":
            with op.batch_alter_table("assignments") as batch:
                batch.alter_column("source", existing_type=source["type"],
                                   nullable=False, server_default="SOLVER")

def downgrade():
    op.drop_column("assignments", "source")
    op.drop_column("classes", "assignment_source")
