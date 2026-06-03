from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from datetime import datetime
from app.db.session import Base

class TeamsChannel(Base):
    __tablename__ = "teams_channels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    webhook_url = Column(Text, nullable=False)
    status = Column(String, default="active")
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class TeamsReportSchedule(Base):
    __tablename__ = "teams_report_schedules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    report_type = Column(String, nullable=False)  # ex: "Relatório Geral", "Relatório Arquivos", etc.
    file_format = Column(String, nullable=False)  # "xlsx", "pdf", "csv"
    channel_id = Column(Integer, ForeignKey("teams_channels.id"), nullable=False)
    frequency_type = Column(String, nullable=False)  # "once", "daily", "weekly", "monthly"
    run_date = Column(DateTime, nullable=True)  # data e hora específicas para execução única
    time_of_day = Column(String, nullable=True)  # ex: "08:00"
    days_of_week = Column(String, nullable=True)  # ex: "[0, 2]" (Seg, Qua)
    day_of_month = Column(Integer, nullable=True)  # ex: 15 (dia do mês)
    next_run_at = Column(DateTime, nullable=True, index=True)
    last_run_at = Column(DateTime, nullable=True)
    status = Column(String, default="active")  # "active", "paused", "completed"
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
