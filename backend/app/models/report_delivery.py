from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from datetime import datetime
from app.db.session import Base


class ReportDelivery(Base):
    """Agendamento de envio de um relatorio (resumo) para o Microsoft Teams.

    Os campos de agendamento usam os MESMOS nomes do modelo Schedule para reaproveitar
    `compute_next_run` e os helpers de `schedule_runner` sem duplicar a logica de frequencia.
    """

    __tablename__ = "report_deliveries"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=True)
    provider = Column(String, default="Teams", index=True)
    # Conteudo do envio
    report_type = Column(String)            # ex.: "Relatório Geral"
    file_format = Column(String, default="xlsx")
    message = Column(Text, nullable=True)   # mensagem personalizada
    target = Column(String, nullable=True)  # "team_id/channel_id" (override do canal); vazio = config padrao
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    period_days = Column(Integer, nullable=True)  # janela rolante do relatorio; nulo = sem filtro de periodo

    # Agendamento (mesmos nomes do Schedule)
    frequency_type = Column(String)         # once/interval/daily/weekly/monthly
    time_of_day = Column(String, nullable=True)
    days_of_week = Column(String, nullable=True)
    day_of_month = Column(Integer, nullable=True)
    run_date = Column(DateTime, nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    interval_minutes = Column(Integer, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    last_delivery_id = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    status = Column(String, default="active")  # active/paused/completed/error/expired

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
