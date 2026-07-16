"""Traducoes centralizadas (PT/EN) do conteudo dos relatorios e do card semanal do Teams.

Fonte UNICA das strings legiveis do relatorio: titulos de secao, cabecalhos de coluna, rotulos de
status, textos do resumo, PDF e do Adaptive Card / poster-imagem. `language` so pode ser "pt"
(padrao, comportamento historico intacto) ou "en". As strings PT sao byte-identicas ao codigo
anterior -> quando o idioma e omitido/"pt", a saida nao muda (zero regressao).

Uso tipico:
    from app.core.report_i18n import normalize_language, tr
    lang = normalize_language(value)     # "pt" | "en"
    blocks = tr(lang, "blocks")          # dict key->titulo localizado
    headers = tr(lang, "headers")["files"]
"""
from __future__ import annotations

import unicodedata
from typing import Any

DEFAULT_LANGUAGE = "pt"
SUPPORTED_LANGUAGES = ("pt", "en")

_EN_ALIASES = {"en", "eng", "english", "ingles", "en-us", "en_us", "en-gb", "en_gb"}


def normalize_language(value: Any) -> str:
    """Devolve "en" para variacoes de ingles; qualquer outra coisa (inclusive None) -> "pt"."""
    text = str(value or "").strip().lower()
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return "en" if text in _EN_ALIASES else DEFAULT_LANGUAGE


# --- Dicionario de traducoes: TR[idioma][secao]. As entradas PT sao verbatim do codigo atual. ---
TR: dict[str, dict[str, Any]] = {
    "pt": {
        "blocks": {
            "files": "Arquivos Detectados",
            "local_errors": "Erros Locais",
            "automations": "Automações",
            "updated_files": "Arquivos Atualizados",
            "workspaces": "Workspaces",
            "schedules": "Agendamentos",
            "executions": "Execuções",
            "simplificado": "Relatório Simplificado",
        },
        "headers": {
            "files": ["ID", "Nome", "Automacao", "Workspace", "Classificacao", "Extensao", "Tamanho", "Caminho original", "Detectado em", "Ciclo"],
            "local_errors": ["ID", "Evento", "Automacao", "Ciclo", "Mensagem", "Data", "Detalhes"],
            "automations": ["ID", "Nome", "Descrição", "Tipo", "Status", "Pasta Monitorada", "Pasta Temporária", "Criada em"],
            "updated_files": ["ID", "Nome", "Automação", "Workspace", "Classificação", "Extensão", "Tamanho", "Caminho original", "Detectado em", "Ciclo"],
            "workspaces": ["ID", "Nome", "Descrição", "Playground ID", "Playground URL", "Embedding Model", "Data Languages", "Status", "Criado Via", "Criado em"],
            "schedules": ["ID", "Nome", "Automação", "Frequência", "Hora", "Dias da Semana", "Dia do Mês", "Próxima Execução", "Última Execução", "Status", "Criado em"],
            "executions": ["ID", "Tipo de Tarefa", "Automação", "Workspace", "Início", "Fim", "Duração (s)", "Total de Arquivos", "Sucessos", "Erros", "Status"],
            "simplificado": ["SPEC", "PORCENTAGEM", "STATUS", "OBSERVAÇÃO", "ULTIMA ATUALIZAÇÃO", "ARQUIVOS"],
        },
        "status_labels": {
            "pending": "Pendente",
            "running": "Em execução",
            "completed": "Finalizada com sucesso",
            "failed": "Finalizada com erro",
            "manual_review": "Ação manual",
            "cancelled": "Cancelada",
        },
        # STATUS do bloco Simplificado. As CHAVES sao canonicas (usadas pela regra de negocio do
        # card em pt) -> em pt o valor exibido == chave.
        "simplificado_status": {"COMPLETO": "COMPLETO", "PROGRESSO": "PROGRESSO", "ERRO": "ERRO"},
        "simplificado_obs": {
            "created": "WORKSPACE CRIADO",
            "error_handling": "Tratamento de erros",
            "available": "Disponivel no Playground",
            "files_sent": "Arquivos enviados",
            "sending": "Enviando para Playground",
        },
        "report_types": {
            "Relatório Geral": "Relatório Geral",
            "Relatório Arquivos": "Relatório Arquivos",
            "Relatório Erros Locais": "Relatório Erros Locais",
            "Relatório Automação": "Relatório Automação",
            "Relatório Atualizados": "Relatório Atualizados",
            "Relatório Workspace": "Relatório Workspace",
            "Relatório Agendamento": "Relatório Agendamento",
            "Relatório Execuções": "Relatório Execuções",
            "Relatório Simplificado": "Relatório Simplificado",
        },
        "summary": {
            "title": "Resumo",
            "headers": ["Campo", "Valor"],
            "type": "Tipo",
            "format": "Formato",
            "source": "Fonte exclusiva",
            "source_value": "Monitoramento local da pasta antes da automacao WEB",
            "date_start": "Data inicial",
            "date_end": "Data final",
            "automation": "Automacao",
            "workspace": "Workspace",
            "classification": "Classificacao",
            "cycle": "Ciclo",
            "generated_at": "Gerado em",
            "all": "Todos",
        },
        "misc": {
            "no_records": "Sem registros para os filtros selecionados.",
            "pdf_report_heading": "Relatorio: {type}",
            "pdf_showing": "Exibindo 80 de {n} registros nesta secao.",
        },
        "card": {
            "headline": "🚀 Seu ambiente já está pronto — entre e crie seu agente",
            "invite_body": (
                "Esqueça baixar a SPEC, subir no workspace seguro e montar o ambiente: a automação já fez tudo "
                "isso. Entre no Playground e vá direto ao que importa — criar o agente no workspace do seu projeto."
            ),
            "access_line": '→ Não tem acesso ao workspace? Toque em "Solicitar acesso" abaixo e preencha o formulário.',
            "health_eta": "em até 1 dia útil",
            "brand": "Stellantis Automation HUB",
            "hours_title": "⏱️ Tempo devolvido ao time",
            "this_week": "Esta semana",
            "total": "Acumulado",
            "hours_note": "Cada arquivo preparado é setup que ninguém precisou fazer à mão ({mpf:g} min/arquivo).",
            "adoption_title": "📈 Quem já está usando",
            "engineers": "Engenheiros usando",
            "specs_ready": "SPECs prontas",
            "health_warn": "⚠️ {items} item(ns) em tratamento{eta}. Já estamos resolvendo.",
            "health_eta_prefix": " — previsão de correção {eta}",
            "health_ok": "✅ Tudo certo — sem itens em tratamento.",
            "period": "Período: {v}",
            "generated": "Gerado em: {v}",
            "view_details_pdf": "Ver detalhes (PDF)",
            "request_access": "Solicitar Acesso",
            "open_playground": "Abrir Playground",
            "download_pdf": "Baixar Relatório (PDF)",
            "download_pdf_short": "Baixar PDF",
            "period_classic": "Periodo: {v}",
            "generated_classic": "Gerado em: {v}",
            "preview": "Previa - {type}",
            "overflow": "... e mais {n} workspace(s) - ver PDF anexo.",
            "m_workspaces": "Workspaces",
            "m_complete": "Completos",
            "m_inprogress": "Em progresso",
            "m_error": "Com erro",
            "m_files": "Arquivos",
            "sc_title": "Solicitação de acesso a workspace",
            "sc_subtitle": "Preencha os campos abaixo. Seu nome e e-mail são capturados automaticamente.",
            "sc_idrede_label": "ID de rede",
            "sc_idrede_ph": "Ex.: AB12345",
            "sc_idrede_err": "Informe o seu ID de rede.",
            "sc_spec_label": "SPEC / Workspace desejado",
            "sc_spec_ph": "Nome da SPEC ou do workspace",
            "sc_spec_err": "Informe a SPEC ou o workspace.",
            "sc_just_label": "Justificativa (opcional)",
            "sc_just_ph": "Por que você precisa do acesso?",
            "sc_submit": "Enviar solicitação",
        },
        "poster": {
            "title": "CONVITE — AUTOMATION HUB",
            "brand": "STELLANTIS AUTOMATION HUB",
            "period_sep": "{a} a {b}",
            "lang_attr": "pt-br",
            "labels": {
                "lang": "pt-br",
                "gen_prefix": "Relatório gerado em",
                "badge": "Convite",
                "cta_playground": "🌐 Abrir Playground",
                "cta_download": "📄 Baixar Relatório (PDF)",
                "proof_title": "Tempo devolvido ao time",
                "this_week": "Esta semana",
                "total": "Acumulado",
                "proof_note": "Cada arquivo preparado é setup que ninguém precisou fazer à mão — baixar a SPEC, subir no workspace seguro e montar o ambiente. Isso já vem pronto.",
                "chart_title": "Evolução do tempo devolvido",
                "chart_sub": "Horas economizadas (acumulado, últimos 7 dias)",
                "engineers": "Engenheiros já usando",
                "specs": "SPECs prontas no ambiente",
                "health_warn": "⚠️ {items} item(ns) em tratamento{eta}. Já estamos resolvendo.",
                "health_eta_prefix": " — previsão de correção {eta}",
                "health_ok": "✅ Tudo certo — nenhum item em tratamento nesta semana.",
                "footer": "Stellantis GenAI Playground — mais produtividade, menos retrabalho.<br>Entre e crie seu agente direto no workspace do seu projeto.",
            },
        },
    },
    "en": {
        "blocks": {
            "files": "Detected Files",
            "local_errors": "Local Errors",
            "automations": "Automations",
            "updated_files": "Updated Files",
            "workspaces": "Workspaces",
            "schedules": "Schedules",
            "executions": "Executions",
            "simplificado": "Simplified Report",
        },
        "headers": {
            "files": ["ID", "Name", "Automation", "Workspace", "Classification", "Extension", "Size", "Original Path", "Detected At", "Cycle"],
            "local_errors": ["ID", "Event", "Automation", "Cycle", "Message", "Date", "Details"],
            "automations": ["ID", "Name", "Description", "Type", "Status", "Monitored Folder", "Temporary Folder", "Created At"],
            "updated_files": ["ID", "Name", "Automation", "Workspace", "Classification", "Extension", "Size", "Original Path", "Detected At", "Cycle"],
            "workspaces": ["ID", "Name", "Description", "Playground ID", "Playground URL", "Embedding Model", "Data Languages", "Status", "Created Via", "Created At"],
            "schedules": ["ID", "Name", "Automation", "Frequency", "Time", "Days of Week", "Day of Month", "Next Run", "Last Run", "Status", "Created At"],
            "executions": ["ID", "Task Type", "Automation", "Workspace", "Start", "End", "Duration (s)", "Total Files", "Successes", "Errors", "Status"],
            "simplificado": ["SPEC", "PERCENTAGE", "STATUS", "OBSERVATION", "LAST UPDATE", "FILES"],
        },
        "status_labels": {
            "pending": "Pending",
            "running": "Running",
            "completed": "Completed successfully",
            "failed": "Finished with error",
            "manual_review": "Manual action",
            "cancelled": "Cancelled",
        },
        "simplificado_status": {"COMPLETO": "COMPLETE", "PROGRESSO": "IN PROGRESS", "ERRO": "ERROR"},
        "simplificado_obs": {
            "created": "WORKSPACE CREATED",
            "error_handling": "Error handling",
            "available": "Available on Playground",
            "files_sent": "Files sent",
            "sending": "Sending to Playground",
        },
        "report_types": {
            "Relatório Geral": "General Report",
            "Relatório Arquivos": "Files Report",
            "Relatório Erros Locais": "Local Errors Report",
            "Relatório Automação": "Automation Report",
            "Relatório Atualizados": "Updated Files Report",
            "Relatório Workspace": "Workspace Report",
            "Relatório Agendamento": "Schedules Report",
            "Relatório Execuções": "Executions Report",
            "Relatório Simplificado": "Simplified Report",
        },
        "summary": {
            "title": "Summary",
            "headers": ["Field", "Value"],
            "type": "Type",
            "format": "Format",
            "source": "Exclusive source",
            "source_value": "Local folder monitoring before WEB automation",
            "date_start": "Start date",
            "date_end": "End date",
            "automation": "Automation",
            "workspace": "Workspace",
            "classification": "Classification",
            "cycle": "Cycle",
            "generated_at": "Generated at",
            "all": "All",
        },
        "misc": {
            "no_records": "No records for the selected filters.",
            "pdf_report_heading": "Report: {type}",
            "pdf_showing": "Showing 80 of {n} records in this section.",
        },
        "card": {
            "headline": "🚀 Your environment is ready — sign in and create your agent",
            "invite_body": (
                "Forget downloading the SPEC, uploading it to the secure workspace and setting up the "
                "environment: the automation already did all of that. Sign in to Playground and go straight to "
                "what matters — creating the agent in your project's workspace."
            ),
            "access_line": '→ No access to the workspace? Tap "Request access" below and fill out the form.',
            "health_eta": "within 1 business day",
            "brand": "Stellantis Automation HUB",
            "hours_title": "⏱️ Time returned to the team",
            "this_week": "This week",
            "total": "Total",
            "hours_note": "Each prepared file is setup nobody had to do by hand ({mpf:g} min/file).",
            "adoption_title": "📈 Who's already using it",
            "engineers": "Engineers using",
            "specs_ready": "SPECs ready",
            "health_warn": "⚠️ {items} item(s) being handled{eta}. We're already on it.",
            "health_eta_prefix": " — expected fix {eta}",
            "health_ok": "✅ All good — no items being handled.",
            "period": "Period: {v}",
            "generated": "Generated at: {v}",
            "view_details_pdf": "View details (PDF)",
            "request_access": "Request Access",
            "open_playground": "Open Playground",
            "download_pdf": "Download Report (PDF)",
            "download_pdf_short": "Download PDF",
            "period_classic": "Period: {v}",
            "generated_classic": "Generated at: {v}",
            "preview": "Preview - {type}",
            "overflow": "... and {n} more workspace(s) - see attached PDF.",
            "m_workspaces": "Workspaces",
            "m_complete": "Complete",
            "m_inprogress": "In progress",
            "m_error": "With error",
            "m_files": "Files",
            "sc_title": "Workspace access request",
            "sc_subtitle": "Fill in the fields below. Your name and email are captured automatically.",
            "sc_idrede_label": "Network ID",
            "sc_idrede_ph": "e.g. AB12345",
            "sc_idrede_err": "Enter your network ID.",
            "sc_spec_label": "Desired SPEC / Workspace",
            "sc_spec_ph": "SPEC or workspace name",
            "sc_spec_err": "Enter the SPEC or workspace.",
            "sc_just_label": "Justification (optional)",
            "sc_just_ph": "Why do you need access?",
            "sc_submit": "Send request",
        },
        "poster": {
            "title": "INVITATION — AUTOMATION HUB",
            "brand": "STELLANTIS AUTOMATION HUB",
            "period_sep": "{a} to {b}",
            "lang_attr": "en",
            "labels": {
                "lang": "en",
                "gen_prefix": "Report generated on",
                "badge": "Invitation",
                "cta_playground": "🌐 Open Playground",
                "cta_download": "📄 Download Report (PDF)",
                "proof_title": "Time returned to the team",
                "this_week": "This week",
                "total": "Total",
                "proof_note": "Each prepared file is setup nobody had to do by hand — downloading the SPEC, uploading it to the secure workspace and setting up the environment. It comes ready.",
                "chart_title": "Returned-time trend",
                "chart_sub": "Hours saved (cumulative, last 7 days)",
                "engineers": "Engineers already using",
                "specs": "SPECs ready in the environment",
                "health_warn": "⚠️ {items} item(s) being handled{eta}. We're already on it.",
                "health_eta_prefix": " — expected fix {eta}",
                "health_ok": "✅ All good — no items being handled this week.",
                "footer": "Stellantis GenAI Playground — more productivity, less rework.<br>Sign in and create your agent right in your project's workspace.",
            },
        },
    },
}


def tr(language: str | None, section: str) -> Any:
    """Bloco de traducoes `section` para o idioma (fallback: pt)."""
    lang = normalize_language(language)
    return TR.get(lang, TR[DEFAULT_LANGUAGE]).get(section, TR[DEFAULT_LANGUAGE].get(section))


def report_block_title(key: str, language: str | None) -> str:
    return tr(language, "blocks").get(key, key)


def report_headers(key: str, language: str | None) -> list[str]:
    return list(tr(language, "headers").get(key, []))


def status_label(status_key: str, language: str | None) -> str:
    return tr(language, "status_labels").get(status_key, status_key)


def simplificado_status(canonical: str, language: str | None) -> str:
    return tr(language, "simplificado_status").get(canonical, canonical)


def simplificado_observation(obs_key: str, language: str | None) -> str:
    return tr(language, "simplificado_obs").get(obs_key, obs_key)


def report_type_label(canonical_pt: str, language: str | None) -> str:
    return tr(language, "report_types").get(canonical_pt, canonical_pt)


def summary_labels(language: str | None) -> dict[str, Any]:
    return tr(language, "summary")


def misc_string(key: str, language: str | None) -> str:
    return tr(language, "misc").get(key, key)


def card_strings(language: str | None) -> dict[str, Any]:
    return tr(language, "card")


def poster_strings(language: str | None) -> dict[str, Any]:
    return tr(language, "poster")


def poster_labels(language: str | None) -> dict[str, Any]:
    return dict(tr(language, "poster").get("labels", {}))
