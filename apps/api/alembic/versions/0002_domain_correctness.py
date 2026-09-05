"""Add lecturer-course capability master table."""
from alembic import op
import sqlalchemy as sa

revision = "0002_domain_correctness"
down_revision = "0001_semester_isolation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lecturer_course_capabilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lecturer_id", sa.Integer(), sa.ForeignKey("lecturers.id"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(300), nullable=True),
        sa.UniqueConstraint("lecturer_id", "course_id"),
    )


def downgrade():
    op.drop_table("lecturer_course_capabilities")
