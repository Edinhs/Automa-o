from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from datetime import datetime
from app.db.session import Base

class WorkspaceExternalUser(Base):
    __tablename__ = "workspace_external_users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, index=True)
    user_identifier = Column(String, index=True)
    area = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String, default="active")
    
    archived_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
