"""Database models for repositories and analysis jobs."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


class AnalysisStatus(StrEnum):
    """Persisted lifecycle states for an analysis job."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


analysis_status_enum = Enum(
    AnalysisStatus,
    name="analysis_status",
    values_callable=lambda enum: [member.value for member in enum],
)


class Repository(Base):
    """Canonical identity for a public GitHub repository."""

    __tablename__ = "repositories"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_url: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    owner: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
    )


class Analysis(Base):
    """One asynchronous analysis request and its lifecycle state."""

    __tablename__ = "analyses"

    terminal_statuses: ClassVar[frozenset[AnalysisStatus]] = frozenset(
        {AnalysisStatus.COMPLETED, AnalysisStatus.FAILED}
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    repository_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        analysis_status_enum,
        default=AnalysisStatus.QUEUED,
        index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="analyses")
