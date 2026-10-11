from datetime import datetime
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
        if received_at is not None and value <= received_at:
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
