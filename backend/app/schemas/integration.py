from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class IntegrationConnectionBase(BaseModel):
    provider: str
    account_label: Optional[str] = None
    status: Optional[str] = "linked"

class IntegrationConnectionCreate(IntegrationConnectionBase):
    pass

class IntegrationConnectionInDB(IntegrationConnectionBase):
    id: int
    linked_by_id: Optional[int] = None
    linked_at: Optional[datetime] = None
    unlinked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
