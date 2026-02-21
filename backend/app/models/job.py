import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, Float, Integer, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # Statuts: pending → estimating → awaiting_approval → processing → completed / failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    voiceover_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    music_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    include_music: Mapped[bool] = mapped_column(Boolean, default=True)
    custom_music_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transition_type: Mapped[str] = mapped_column(String(20), default="crossfade")
    montage_plan: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    photos: Mapped[list["Photo"]] = relationship("Photo", back_populates="job", cascade="all, delete-orphan")
