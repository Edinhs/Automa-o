from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from datetime import datetime
from app.db.session import Base

class IntegrationConnection(Base):
    __tablename__ = "integration_connections"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, index=True)
    account_label = Column(String, nullable=True)
    status = Column(String, default="active")
    linked_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    linked_at = Column(DateTime, nullable=True)
    unlinked_at = Column(DateTime, nullable=True)
    config_json = Column(Text, nullable=True)

    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IntegrationDelivery(Base):
    __tablename__ = "integration_deliveries"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, index=True)
    delivery_type = Column(String, index=True)
    target = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    status = Column(String, default="pending", index=True)
    request_json = Column(Text, nullable=True)
    response_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sent_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
