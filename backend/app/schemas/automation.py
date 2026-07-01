from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class AutomationBase(BaseModel):
    name: str
    description: Optional[str] = None
    type: str
    status: Optional[str] = "active"
    folder_path: Optional[str] = None
    temp_folder_path: Optional[str] = None
    workspace_id: Optional[int] = None
    batch_size: Optional[int] = None
    batch_interval_seconds: Optional[int] = None
    monitoring_timeout_minutes: Optional[int] = None
    monitor_interval_seconds: Optional[int] = None
    max_retries: Optional[int] = None
    keep_temp_on_error: Optional[bool] = True
    convert_to_pdf_on_error: Optional[bool] = True
    full_execution: Optional[bool] = False
    config_json: Optional[str] = None

class AutomationCreate(AutomationBase):
    pass

class AutomationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    folder_path: Optional[str] = None
    temp_folder_path: Optional[str] = None
    workspace_id: Optional[int] = None
    batch_size: Optional[int] = None
    batch_interval_seconds: Optional[int] = None
    monitoring_timeout_minutes: Optional[int] = None
    monitor_interval_seconds: Optional[int] = None
    max_retries: Optional[int] = None
    keep_temp_on_error: Optional[bool] = None
    convert_to_pdf_on_error: Optional[bool] = None
    full_execution: Optional[bool] = None
    config_json: Optional[str] = None

class AutomationInDB(AutomationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
