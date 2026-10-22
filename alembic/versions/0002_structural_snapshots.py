"""add structural_snapshots table"""
from alembic import op
from app.db.base import Base

revision = "0002_structural_snapshots"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.tables["structural_snapshots"].drop(bind=op.get_bind())
