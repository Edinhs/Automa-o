from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from datetime import datetime
from app.db.session import Base

class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=True, index=True)
    name = Column(String, index=True)
    frequency_type = Column(String) # daily/weekly/monthly/once
    time_of_day = Column(String, nullable=True)
    days_of_week = Column(String, nullable=True)
    day_of_month = Column(Integer, nullable=True)
    run_date = Column(DateTime, nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    interval_minutes = Column(Integer, nullable=True)
    next_run_at = Column(DateTime, nullable=True, index=True)
    last_run_at = Column(DateTime, nullable=True)
    last_task_id = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    status = Column(String, default="active", index=True) # active/paused/inactive
    report_type = Column(String, nullable=True)
    report_format = Column(String, nullable=True)
    # Quando True, o relatorio gerado por este agendamento tambem e copiado para a pasta de entrega
    # (REPORT_DELIVERY_PATH do .env / Power Automate). Default False: relatorio fica so em REPORTS_PATH.
    deliver_to_folder = Column(Boolean, default=False)

    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
