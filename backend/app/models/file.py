from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from datetime import datetime
from app.db.session import Base

class WorkspaceFile(Base):
    __tablename__ = "workspace_files"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String, index=True)
    original_path = Column(String, nullable=True)
    temp_path = Column(String, nullable=True)
    pdf_path = Column(String, nullable=True)
    extension = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    content_sha256 = Column(String, nullable=True)
    detection_source = Column(String, nullable=True)
    detection_task_id = Column(Integer, nullable=True)
    detection_classification = Column(String, nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=True)
    status = Column(String, default="pending")
    playground_status = Column(String, nullable=True)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    converted_to_pdf = Column(Boolean, default=False)
    last_error = Column(Text, nullable=True)

    detected_at = Column(DateTime, nullable=True)
    uploaded_at = Column(DateTime, nullable=True)
    ready_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    manual_review_at = Column(DateTime, nullable=True)

    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
