from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class WorkspaceFileBase(BaseModel):
    file_name: str
    original_path: Optional[str] = None
    temp_path: Optional[str] = None
    pdf_path: Optional[str] = None
    extension: Optional[str] = None
    size_bytes: Optional[int] = None
    content_sha256: Optional[str] = None
    detection_source: Optional[str] = None
    detection_task_id: Optional[int] = None
    detection_classification: Optional[str] = None
    workspace_id: Optional[int] = None
    automation_id: Optional[int] = None
    status: Optional[str] = "pending"
    playground_status: Optional[str] = None
    attempts: Optional[int] = 0
    max_attempts: Optional[int] = 3
    converted_to_pdf: Optional[bool] = False

class WorkspaceFileCreate(WorkspaceFileBase):
    pass

class WorkspaceFileInDB(WorkspaceFileBase):
    id: int
    last_error: Optional[str] = None
    detected_at: Optional[datetime] = None
    uploaded_at: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    manual_review_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
