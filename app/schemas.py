from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EmergencyCallBase(BaseModel):
    call_number: str = Field(min_length=1, max_length=50)
    urgency_category: int = Field(ge=1, le=4)
    address: str = Field(min_length=1)
    received_at: datetime
    arrived_at: datetime
    outcome: str = Field(min_length=1, max_length=255)

    @field_validator("arrived_at")
    @classmethod
    def arrived_after_received(cls, value: datetime, info):
        received_at = info.data.get("received_at")
        if received_at is None:
            return value
        # Naive and aware datetimes can't be compared directly (TypeError), so
        # treat a naive value as UTC for the comparison only.
        value_utc = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        received_utc = (
            received_at if received_at.tzinfo is not None else received_at.replace(tzinfo=timezone.utc)
        )
        if value_utc <= received_utc:
            raise ValueError("arrived_at must be later than received_at")
        return value


class EmergencyCallCreate(EmergencyCallBase):
    pass


class EmergencyCallUpdate(EmergencyCallBase):
    pass


class EmergencyCallOut(EmergencyCallBase):
    id: UUID

    model_config = {"from_attributes": True}


class EmergencyCallList(BaseModel):
    items: list[EmergencyCallOut]
    total: int
    limit: int
    offset: int
