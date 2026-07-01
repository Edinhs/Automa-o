from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ExecutionLogBase(BaseModel):
    level: str
    message: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    automation_id: Optional[int] = None
    file_id: Optional[int] = None
    task_id: Optional[int] = None
    user_id: Optional[int] = None
    metadata_json: Optional[str] = None

class ExecutionLogCreate(ExecutionLogBase):
    pass

class ExecutionLogInDB(ExecutionLogBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
