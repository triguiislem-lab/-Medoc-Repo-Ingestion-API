from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_repo_update_kind_src_name"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def _has_index(table: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table))


def upgrade() -> None:
    if not _has_column("repo_updates", "update_kind"):
        op.add_column("repo_updates", sa.Column("update_kind", sa.String(length=20), nullable=True))
        op.execute("UPDATE repo_updates SET update_kind = 'github' WHERE update_kind IS NULL")
        op.alter_column("repo_updates", "update_kind", nullable=False, server_default="github")
    if not _has_column("repo_updates", "source_name"):
        op.add_column("repo_updates", sa.Column("source_name", sa.String(length=100), nullable=True))

    if not _has_index("repo_updates", "ix_repo_updates_update_kind"):
        op.create_index("ix_repo_updates_update_kind", "repo_updates", ["update_kind"])
    if not _has_index("repo_updates", "ix_repo_updates_source_name"):
        op.create_index("ix_repo_updates_source_name", "repo_updates", ["source_name"])
    if not _has_index("repo_updates", "ix_repo_updates_kind_branch_created_at"):
        op.create_index("ix_repo_updates_kind_branch_created_at", "repo_updates", ["update_kind", "branch", "created_at"])


def downgrade() -> None:
    if _has_index("repo_updates", "ix_repo_updates_kind_branch_created_at"):
        op.drop_index("ix_repo_updates_kind_branch_created_at", table_name="repo_updates")
    if _has_index("repo_updates", "ix_repo_updates_source_name"):
        op.drop_index("ix_repo_updates_source_name", table_name="repo_updates")
    if _has_index("repo_updates", "ix_repo_updates_update_kind"):
        op.drop_index("ix_repo_updates_update_kind", table_name="repo_updates")
    if _has_column("repo_updates", "source_name"):
        op.drop_column("repo_updates", "source_name")
    if _has_column("repo_updates", "update_kind"):
        op.drop_column("repo_updates", "update_kind")
