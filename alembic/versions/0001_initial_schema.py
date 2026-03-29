from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return inspect(bind).has_table(name)


def upgrade() -> None:
    if not _has_table("repo_updates"):
        op.create_table(
            "repo_updates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("branch", sa.String(length=255), nullable=False),
            sa.Column("before_sha", sa.String(length=64), nullable=True),
            sa.Column("after_sha", sa.String(length=64), nullable=False),
            sa.Column("compare_url", sa.Text(), nullable=True),
            sa.Column("changed_files_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_repo_updates_branch", "repo_updates", ["branch"])
        op.create_index("ix_repo_updates_after_sha", "repo_updates", ["after_sha"], unique=True)

    if not _has_table("raw_snapshots"):
        op.create_table(
            "raw_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("update_id", sa.Integer(), sa.ForeignKey("repo_updates.id", ondelete="CASCADE"), nullable=False),
            sa.Column("path", sa.String(length=512), nullable=False),
            sa.Column("file_sha", sa.String(length=64), nullable=True),
            sa.Column("content_type", sa.String(length=100), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("update_id", "path", name="uq_snapshot_update_path"),
        )
        op.create_index("ix_raw_snapshots_update_id", "raw_snapshots", ["update_id"])
        op.create_index("ix_raw_snapshots_path", "raw_snapshots", ["path"])

    if not _has_table("medicine_records"):
        op.create_table(
            "medicine_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("dataset", sa.String(length=50), nullable=False),
            sa.Column("source_key", sa.String(length=255), nullable=False),
            sa.Column("code", sa.String(length=100), nullable=True),
            sa.Column("name", sa.String(length=500), nullable=False),
            sa.Column("dosage", sa.String(length=255), nullable=True),
            sa.Column("form", sa.String(length=255), nullable=True),
            sa.Column("packaging", sa.String(length=255), nullable=True),
            sa.Column("public_price", sa.Float(), nullable=True),
            sa.Column("reimbursed_price", sa.Float(), nullable=True),
            sa.Column("manufacturer", sa.String(length=255), nullable=True),
            sa.Column("category", sa.String(length=255), nullable=True),
            sa.Column("reimbursement_flag", sa.String(length=50), nullable=True),
            sa.Column("extra_flag", sa.String(length=50), nullable=True),
            sa.Column("source_path", sa.String(length=255), nullable=False),
            sa.Column("raw_json", sa.Text(), nullable=False),
            sa.Column("first_seen_update_id", sa.Integer(), sa.ForeignKey("repo_updates.id"), nullable=True),
            sa.Column("last_seen_update_id", sa.Integer(), sa.ForeignKey("repo_updates.id"), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.UniqueConstraint("dataset", "source_key", name="uq_medicine_dataset_source_key"),
        )
        op.create_index("ix_medicine_records_dataset", "medicine_records", ["dataset"])
        op.create_index("ix_medicine_records_source_key", "medicine_records", ["source_key"])
        op.create_index("ix_medicine_records_code", "medicine_records", ["code"])
        op.create_index("ix_medicine_records_name", "medicine_records", ["name"])
        op.create_index("ix_medicine_records_category", "medicine_records", ["category"])

    if not _has_table("medicine_changes"):
        op.create_table(
            "medicine_changes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("update_id", sa.Integer(), sa.ForeignKey("repo_updates.id", ondelete="CASCADE"), nullable=False),
            sa.Column("dataset", sa.String(length=50), nullable=False),
            sa.Column("source_key", sa.String(length=255), nullable=False),
            sa.Column("medicine_record_id", sa.Integer(), sa.ForeignKey("medicine_records.id"), nullable=True),
            sa.Column("change_type", sa.String(length=20), nullable=False),
            sa.Column("before_json", sa.Text(), nullable=True),
            sa.Column("after_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_medicine_changes_update_id", "medicine_changes", ["update_id"])
        op.create_index("ix_medicine_changes_dataset", "medicine_changes", ["dataset"])
        op.create_index("ix_medicine_changes_source_key", "medicine_changes", ["source_key"])
        op.create_index("ix_medicine_changes_change_type", "medicine_changes", ["change_type"])

    if not _has_table("webhook_deliveries"):
        op.create_table(
            "webhook_deliveries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("github_delivery_id", sa.String(length=255), nullable=False),
            sa.Column("event", sa.String(length=50), nullable=False),
            sa.Column("ref", sa.String(length=255), nullable=False),
            sa.Column("before_sha", sa.String(length=64), nullable=True),
            sa.Column("after_sha", sa.String(length=64), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="received"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_webhook_deliveries_github_delivery_id", "webhook_deliveries", ["github_delivery_id"], unique=True)
        op.create_index("ix_webhook_deliveries_ref", "webhook_deliveries", ["ref"])

    if not _has_table("monitored_sources"):
        op.create_table(
            "monitored_sources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_name", sa.String(length=100), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("latest_marker", sa.String(length=255), nullable=True),
            sa.Column("latest_title", sa.String(length=500), nullable=True),
            sa.Column("latest_item_url", sa.Text(), nullable=True),
            sa.Column("last_page_hash", sa.String(length=64), nullable=True),
            sa.Column("last_item_hash", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="new"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("requires_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_monitored_sources_source_name", "monitored_sources", ["source_name"], unique=True)

    if not _has_table("ingested_artifacts"):
        op.create_table(
            "ingested_artifacts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("repo_update_id", sa.Integer(), sa.ForeignKey("repo_updates.id", ondelete="SET NULL"), nullable=True),
            sa.Column("monitored_source_id", sa.Integer(), sa.ForeignKey("monitored_sources.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_name", sa.String(length=100), nullable=False),
            sa.Column("kind", sa.String(length=50), nullable=False, server_default="file"),
            sa.Column("title", sa.String(length=500), nullable=True),
            sa.Column("path", sa.String(length=512), nullable=True),
            sa.Column("origin_url", sa.Text(), nullable=True),
            sa.Column("storage_path", sa.Text(), nullable=True),
            sa.Column("content_type", sa.String(length=255), nullable=True),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=True),
            sa.Column("parser_hint", sa.String(length=50), nullable=True),
            sa.Column("parse_status", sa.String(length=50), nullable=False, server_default="stored"),
            sa.Column("marker", sa.String(length=255), nullable=True),
            sa.Column("effective_date_text", sa.String(length=255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("source_name", "sha256", name="uq_source_sha256"),
        )
        op.create_index("ix_ingested_artifacts_repo_update_id", "ingested_artifacts", ["repo_update_id"])
        op.create_index("ix_ingested_artifacts_monitored_source_id", "ingested_artifacts", ["monitored_source_id"])
        op.create_index("ix_ingested_artifacts_source_name", "ingested_artifacts", ["source_name"])
        op.create_index("ix_ingested_artifacts_sha256", "ingested_artifacts", ["sha256"])


def downgrade() -> None:
    pass
