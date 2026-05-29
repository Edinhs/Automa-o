from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from datetime import datetime
from app.db.session import Base

DEFAULT_THEME_PREFERENCE = "light"
VALID_THEME_PREFERENCES = {"light", "dark"}


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    network_id = Column(String, unique=True, index=True)
    role = Column(String, default="viewer") # admin/user/viewer
    status = Column(String, default="active") # active/inactive/archived
    password_hash = Column(String)
    last_login_at = Column(DateTime, nullable=True)
    playground_connected = Column(Boolean, default=False)
    playground_connected_at = Column(DateTime, nullable=True)
    playground_session_path = Column(String, nullable=True)
    profile_photo_path = Column(String, nullable=True)
    profile_photo_mime_type = Column(String, nullable=True)
    profile_photo_updated_at = Column(DateTime, nullable=True)
    theme_preference = Column(String, default=DEFAULT_THEME_PREFERENCE, nullable=False)
    
    archived_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
