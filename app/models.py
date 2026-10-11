import uuid
from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EmergencyCall(Base):
    __tablename__ = "emergency_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_number: Mapped[str] = mapped_column(String(50), nullable=False)
    urgency_category: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(255), nullable=False)
