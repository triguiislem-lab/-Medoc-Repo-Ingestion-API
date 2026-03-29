from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


UPDATE_KIND_VALUES = ("github", "official", "manual")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_delivery_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event: Mapped[str] = mapped_column(String(50))
    ref: Mapped[str] = mapped_column(String(255), index=True)
    before_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="received")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RepoUpdate(Base):
    __tablename__ = "repo_updates"
    __table_args__ = (
        Index("ix_repo_updates_kind_branch_created_at", "update_kind", "branch", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch: Mapped[str] = mapped_column(String(255), index=True)
    update_kind: Mapped[str] = mapped_column(String(20), default="github", index=True)
    source_name: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    before_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_sha: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    compare_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_files_json: Mapped[str] = mapped_column(Text, default="[]")
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    snapshots: Mapped[list["RawSnapshot"]] = relationship(back_populates="update")
    changes: Mapped[list["MedicineChange"]] = relationship(back_populates="update")
    artifacts: Mapped[list["IngestedArtifact"]] = relationship(back_populates="update")


class RawSnapshot(Base):
    __tablename__ = "raw_snapshots"
    __table_args__ = (UniqueConstraint("update_id", "path", name="uq_snapshot_update_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    update_id: Mapped[int] = mapped_column(ForeignKey("repo_updates.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(512), index=True)
    file_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    update: Mapped[RepoUpdate] = relationship(back_populates="snapshots")


class MedicineRecord(Base):
    __tablename__ = "medicine_records"
    __table_args__ = (UniqueConstraint("dataset", "source_key", name="uq_medicine_dataset_source_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset: Mapped[str] = mapped_column(String(50), index=True)
    source_key: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    dosage: Mapped[str | None] = mapped_column(String(255), nullable=True)
    form: Mapped[str | None] = mapped_column(String(255), nullable=True)
    packaging: Mapped[str | None] = mapped_column(String(255), nullable=True)
    public_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reimbursed_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    reimbursement_flag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extra_flag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_path: Mapped[str] = mapped_column(String(255))
    raw_json: Mapped[str] = mapped_column(Text)
    first_seen_update_id: Mapped[int | None] = mapped_column(ForeignKey("repo_updates.id"), nullable=True)
    last_seen_update_id: Mapped[int | None] = mapped_column(ForeignKey("repo_updates.id"), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MedicineChange(Base):
    __tablename__ = "medicine_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    update_id: Mapped[int] = mapped_column(ForeignKey("repo_updates.id", ondelete="CASCADE"), index=True)
    dataset: Mapped[str] = mapped_column(String(50), index=True)
    source_key: Mapped[str] = mapped_column(String(255), index=True)
    medicine_record_id: Mapped[int | None] = mapped_column(ForeignKey("medicine_records.id"), nullable=True)
    change_type: Mapped[str] = mapped_column(String(20), index=True)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    update: Mapped[RepoUpdate] = relationship(back_populates="changes")


class MonitoredSource(Base):
    __tablename__ = "monitored_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    source_url: Mapped[str] = mapped_column(Text)
    latest_marker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latest_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latest_item_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_page_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_item_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="new")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    artifacts: Mapped[list["IngestedArtifact"]] = relationship(back_populates="monitored_source")


class IngestedArtifact(Base):
    __tablename__ = "ingested_artifacts"
    __table_args__ = (UniqueConstraint("source_name", "sha256", name="uq_source_sha256"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_update_id: Mapped[int | None] = mapped_column(ForeignKey("repo_updates.id", ondelete="SET NULL"), nullable=True, index=True)
    monitored_source_id: Mapped[int | None] = mapped_column(ForeignKey("monitored_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    source_name: Mapped[str] = mapped_column(String(100), index=True)
    kind: Mapped[str] = mapped_column(String(50), default="file")
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    origin_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parser_hint: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(50), default="stored")
    marker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effective_date_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    update: Mapped[RepoUpdate | None] = relationship(back_populates="artifacts")
    monitored_source: Mapped[MonitoredSource | None] = relationship(back_populates="artifacts")
