from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class AgentTaskBase(BaseModel):
    task_type: str
    status: Optional[str] = "pending"
    payload_json: Optional[str] = None
    error_message: Optional[str] = None
    assigned_agent_id: Optional[int] = None
    max_attempts: Optional[int] = 3

class AgentTaskCreate(AgentTaskBase):
    pass

class AgentTaskInDB(AgentTaskBase):
    id: int
    result_json: Optional[str] = None
    attempts: int
    max_attempts: Optional[int] = 3
    created_by_id: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PollResponse(BaseModel):
    tasks: List[AgentTaskInDB]

class TaskCompleteRequest(BaseModel):
    result_json: Optional[str] = None

class TaskFailRequest(BaseModel):
    error_message: str

class HeartbeatRequest(BaseModel):
    name: str
    machine_name: Optional[str] = None
    version: Optional[str] = None
