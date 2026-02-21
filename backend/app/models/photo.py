import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Google Vision analysis results (populated at upload)
    vision_labels: Mapped[list | None] = mapped_column(JSON, nullable=True)
    vision_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    vision_objects: Mapped[list | None] = mapped_column(JSON, nullable=True)

    job: Mapped["Job"] = relationship("Job", back_populates="photos")
