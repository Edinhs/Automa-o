from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ExecutionReportBase(BaseModel):
    name: str
    type: str
    status: Optional[str] = "pending"
    file_path: Optional[str] = None
    source_scope: Optional[str] = None
    generation_trigger: Optional[str] = None
    source_task_id: Optional[int] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    generated_by_id: Optional[int] = None

class ExecutionReportCreate(ExecutionReportBase):
    pass

class ExecutionReportInDB(ExecutionReportBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
