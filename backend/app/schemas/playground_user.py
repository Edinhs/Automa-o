from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class WorkspaceExternalUserBase(BaseModel):
    name: str
    email: Optional[str] = None
    user_identifier: Optional[str] = None
    area: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = "active"

class WorkspaceExternalUserCreate(WorkspaceExternalUserBase):
    pass

class WorkspaceExternalUserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    user_identifier: Optional[str] = None
    area: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None

class WorkspaceExternalUserInDB(WorkspaceExternalUserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
