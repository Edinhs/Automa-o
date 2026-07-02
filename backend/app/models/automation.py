from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from datetime import datetime
from app.db.session import Base

class Automation(Base):
    __tablename__ = "automations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    type = Column(String)
    status = Column(String, default="active", index=True)
    folder_path = Column(String, nullable=True)
    temp_folder_path = Column(String, nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True, index=True)
    batch_size = Column(Integer, nullable=True)
    batch_interval_seconds = Column(Integer, nullable=True)
    monitoring_timeout_minutes = Column(Integer, nullable=True)
    monitor_interval_seconds = Column(Integer, nullable=True)
    max_retries = Column(Integer, nullable=True)
    keep_temp_on_error = Column(Boolean, default=True)
    convert_to_pdf_on_error = Column(Boolean, default=True)
    full_execution = Column(Boolean, default=False, nullable=False)
    config_json = Column(Text, nullable=True)

    archived_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
