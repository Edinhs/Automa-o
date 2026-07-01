from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class WorkspaceBase(BaseModel):
    name: str
    description: Optional[str] = None
    playground_workspace_id: Optional[str] = None
    playground_url: Optional[str] = None
    add_data_url: Optional[str] = None
    embedding_model: Optional[str] = None
    data_languages: Optional[str] = None
    owner_user_id: Optional[int] = None
    status: Optional[str] = "active"
    created_via: Optional[str] = None

class WorkspaceCreate(WorkspaceBase):
    pass

class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    playground_workspace_id: Optional[str] = None
    playground_url: Optional[str] = None
    add_data_url: Optional[str] = None
    embedding_model: Optional[str] = None
    data_languages: Optional[str] = None
    status: Optional[str] = None

class WorkspaceInDB(WorkspaceBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
