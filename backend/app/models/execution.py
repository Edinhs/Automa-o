from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from datetime import datetime
from app.db.session import Base

class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String, index=True)
    message = Column(Text)
    entity_type = Column(String, nullable=True)
    entity_id = Column(Integer, nullable=True)
    automation_id = Column(Integer, nullable=True, index=True)
    file_id = Column(Integer, nullable=True)
    task_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ExecutionReport(Base):
    __tablename__ = "execution_reports"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    type = Column(String)
    status = Column(String, default="pending", index=True)
    file_path = Column(String, nullable=True)
    source_scope = Column(String, nullable=True)
    generation_trigger = Column(String, nullable=True)
    source_task_id = Column(Integer, nullable=True, index=True)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    generated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Idioma em que o conteudo do relatorio foi gerado ("pt" padrao ou "en"). Persistido para que
    # o re-download/fallback (fallback_content/filters_for_report) regenere no MESMO idioma.
    language = Column(String, default="pt", server_default="pt", nullable=False)

    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
