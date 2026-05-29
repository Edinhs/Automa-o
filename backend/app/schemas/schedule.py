from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date, time

class ScheduleBase(BaseModel):
    automation_id: Optional[int] = None
    name: str
    frequency_type: str
    time_of_day: Optional[time] = None
    days_of_week: Optional[str] = None
    day_of_month: Optional[int] = None
    run_date: Optional[date] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    interval_minutes: Optional[int] = None
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_task_id: Optional[int] = None
    last_error: Optional[str] = None
    status: Optional[str] = "active"

class ScheduleCreate(ScheduleBase):
    pass

class ScheduleUpdate(BaseModel):
    name: Optional[str] = None
    frequency_type: Optional[str] = None
    time_of_day: Optional[time] = None
    days_of_week: Optional[str] = None
    day_of_month: Optional[int] = None
    run_date: Optional[date] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    interval_minutes: Optional[int] = None
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_task_id: Optional[int] = None
    last_error: Optional[str] = None
    status: Optional[str] = None

class ScheduleInDB(ScheduleBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
