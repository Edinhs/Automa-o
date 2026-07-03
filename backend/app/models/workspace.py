from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from datetime import datetime
from app.db.session import Base

class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    playground_workspace_id = Column(String, nullable=True)
    playground_url = Column(String, nullable=True)
    add_data_url = Column(String, nullable=True)
    embedding_model = Column(String, nullable=True)
    data_languages = Column(String, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    status = Column(String, default="active")
    created_via = Column(String, nullable=True)

    archived_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
