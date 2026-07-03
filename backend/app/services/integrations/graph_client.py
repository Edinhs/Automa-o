from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import requests

from app.core.config import settings


GRAPH_BASE_URL = "https://graph.microsoft.com"
SENSITIVE_KEYS = {"access_token", "authorization", "client_secret", "password", "secret", "token"}


class GraphIntegrationError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        code: str = "graph_error",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details


class GraphConfigurationError(GraphIntegrationError):
    def __init__(self, missing: Iterable[str] | None = None, message: str | None = None) -> None:
        missing_list = list(missing or [])
        detail = message or "Microsoft Graph nao configurado. Preencha as variaveis de ambiente obrigatorias."
        if missing_list:
            detail = f"{detail} Campos ausentes: {', '.join(missing_list)}."
        super().__init__(detail, status_code=503, code="not_configured", details={"missing": missing_list})
        self.missing = missing_list


@dataclass
class GraphResult:
    status_code: int
    data: Any
    request_id: str | None = None


def sanitize_for_storage(value: Any, max_text_length: int = 3000) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SENSITIVE_KEYS:
                sanitized[key] = "***"
            else:
                sanitized[key] = sanitize_for_storage(item, max_text_length=max_text_length)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_storage(item, max_text_length=max_text_length) for item in value[:50]]
    if isinstance(value, str) and len(value) > max_text_length:
        return f"{value[:max_text_length]}..."
    return value


def missing_base_graph_settings(config=settings) -> list[str]:
    required = [
        "MS_GRAPH_TENANT_ID",
        "MS_GRAPH_CLIENT_ID",
        "MS_GRAPH_CLIENT_SECRET",
        "MS_GRAPH_SENDER_USER",
    ]
    return [name for name in required if not str(getattr(config, name, "") or "").strip()]


def build_graph_status(config=settings) -> dict[str, Any]:
    missing = missing_base_graph_settings(config)
    configured = not missing
    webhook_configured = bool(str(getattr(config, "MS_GRAPH_TEAMS_WEBHOOK_URL", "") or "").strip())
    graph_teams_configured = configured and bool(
        str(getattr(config, "MS_GRAPH_TEAMS_TEAM_ID", "") or "").strip()
        and str(getattr(config, "MS_GRAPH_TEAMS_CHANNEL_ID", "") or "").strip()
    )
    if webhook_configured:
        teams_message_mode = "webhook"
    elif graph_teams_configured:
        teams_message_mode = "graph_beta"
    else:
        teams_message_mode = "not_configured"

    return {
        "provider": "Microsoft Graph",
        "status": "configured" if configured else "not_configured",
        "configured": configured,
        "mode": "app_only",
        "missing": missing,
        "outlook": {"configured": configured},
        "teams": {
            "calendar_configured": configured,
            "messages_configured": webhook_configured or graph_teams_configured,
            "message_mode": teams_message_mode,
            "missing": [
                name
                for name in ["MS_GRAPH_TEAMS_TEAM_ID", "MS_GRAPH_TEAMS_CHANNEL_ID", "MS_GRAPH_TEAMS_WEBHOOK_URL"]
                if not str(getattr(config, name, "") or "").strip()
            ],
        },
    }


class GraphClient:
    def __init__(self, config=settings) -> None:
        self.config = config
        self.scopes = [str(getattr(config, "MS_GRAPH_SCOPE", "") or "https://graph.microsoft.com/.default")]

    @property
    def sender_user(self) -> str:
        return str(getattr(self.config, "MS_GRAPH_SENDER_USER", "") or "").strip()

    def ensure_configured(self) -> None:
        missing = missing_base_graph_settings(self.config)
        if missing:
            raise GraphConfigurationError(missing)

    def acquire_token(self) -> str:
        self.ensure_configured()
        try:
            import msal
        except ImportError as exc:
            raise GraphConfigurationError(
                message="Dependencia msal nao instalada. Execute setup_backend.bat ou python -m pip install -r requirements.txt."
            ) from exc

        authority = f"https://login.microsoftonline.com/{self.config.MS_GRAPH_TENANT_ID}"
        app = msal.ConfidentialClientApplication(
            self.config.MS_GRAPH_CLIENT_ID,
            authority=authority,
            client_credential=self.config.MS_GRAPH_CLIENT_SECRET,
        )
        result = app.acquire_token_silent(self.scopes, account=None)
        if not result:
            result = app.acquire_token_for_client(scopes=self.scopes)
        token = result.get("access_token")
        if token:
            return token

        error = result.get("error_description") or result.get("error") or "Falha ao obter token Microsoft Graph."
        raise GraphIntegrationError(
            error,
            status_code=502,
            code="token_error",
            details=sanitize_for_storage(result),
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        expected_status: tuple[int, ...] = (200,),
        api_version: str = "v1.0",
    ) -> GraphResult:
        token = self.acquire_token()
        url = path if path.startswith("http") else f"{GRAPH_BASE_URL}/{api_version}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=json_payload,
                timeout=int(getattr(self.config, "MS_GRAPH_TIMEOUT_SECONDS", 20) or 20),
            )
        except requests.Timeout as exc:
            raise GraphIntegrationError("Timeout ao chamar Microsoft Graph.", status_code=504, code="timeout") from exc
        except requests.RequestException as exc:
            raise GraphIntegrationError(f"Falha HTTP ao chamar Microsoft Graph: {exc}", status_code=502, code="request_error") from exc

        data: Any
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = response.text

        if response.status_code not in expected_status:
            error_message = _extract_graph_error(data) or f"Microsoft Graph retornou HTTP {response.status_code}."
            raise GraphIntegrationError(
                error_message,
                status_code=502 if response.status_code >= 500 else response.status_code,
                code="graph_response_error",
                details=sanitize_for_storage(data),
            )

        return GraphResult(
            status_code=response.status_code,
            data=sanitize_for_storage(data),
            request_id=response.headers.get("request-id") or response.headers.get("client-request-id"),
        )

    def test_connection(self) -> GraphResult:
        return self.request(
            "GET",
            f"users/{self.sender_user}?$select=id,displayName,userPrincipalName,mail",
            expected_status=(200,),
        )

    def send_mail(
        self,
        *,
        to_recipients: list[dict[str, Any]],
        subject: str,
        body: str,
        body_content_type: str = "HTML",
        attachments: list[dict[str, Any]] | None = None,
    ) -> GraphResult:
        message: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": body_content_type or "HTML", "content": body or ""},
            "toRecipients": [_recipient(address) for address in to_recipients],
        }
        if attachments:
            message["attachments"] = [_file_attachment(attachment) for attachment in attachments]
        payload = {
            "message": message,
            "saveToSentItems": True,
        }
        return self.request("POST", f"users/{self.sender_user}/sendMail", json_payload=payload, expected_status=(202,))

    def create_calendar_event(self, payload: dict[str, Any], *, online_meeting: bool = False) -> GraphResult:
        event_payload = _event_payload(payload, online_meeting=online_meeting)
        return self.request(
            "POST",
            f"users/{self.sender_user}/calendar/events",
            json_payload=event_payload,
            expected_status=(201,),
        )

    def send_channel_message(self, payload: dict[str, Any]) -> GraphResult:
        team_id = str(payload.get("team_id") or getattr(self.config, "MS_GRAPH_TEAMS_TEAM_ID", "") or "").strip()
        channel_id = str(payload.get("channel_id") or getattr(self.config, "MS_GRAPH_TEAMS_CHANNEL_ID", "") or "").strip()
        if not team_id or not channel_id:
            raise GraphConfigurationError(
                ["MS_GRAPH_TEAMS_TEAM_ID", "MS_GRAPH_TEAMS_CHANNEL_ID"],
                "Mensagem Teams via Graph exige team_id e channel_id.",
            )
        content = str(payload.get("content") or "").strip()
        graph_payload = {
            "body": {
                "contentType": str(payload.get("content_type") or "html").lower(),
                "content": content,
            }
        }
        return self.request(
            "POST",
            f"teams/{team_id}/channels/{channel_id}/messages",
            json_payload=graph_payload,
            expected_status=(201,),
            api_version="beta",
        )


def send_teams_webhook(payload: dict[str, Any], config=settings) -> GraphResult:
    webhook_url = str(getattr(config, "MS_GRAPH_TEAMS_WEBHOOK_URL", "") or "").strip()
    if not webhook_url:
        raise GraphConfigurationError(["MS_GRAPH_TEAMS_WEBHOOK_URL"], "Webhook Teams nao configurado.")
    content = str(payload.get("content") or "").strip()
    if not content:
        raise GraphIntegrationError("Mensagem Teams vazia.", status_code=422, code="validation_error")
    try:
        response = requests.post(
            webhook_url,
            json={"text": content},
            timeout=int(getattr(config, "MS_GRAPH_TIMEOUT_SECONDS", 20) or 20),
        )
    except requests.Timeout as exc:
        raise GraphIntegrationError("Timeout ao chamar webhook Teams.", status_code=504, code="timeout") from exc
    except requests.RequestException as exc:
        raise GraphIntegrationError(f"Falha HTTP ao chamar webhook Teams: {exc}", status_code=502, code="request_error") from exc

    if response.status_code not in (200, 202):
        raise GraphIntegrationError(
            f"Webhook Teams retornou HTTP {response.status_code}.",
            status_code=502 if response.status_code >= 500 else response.status_code,
            details=sanitize_for_storage(response.text),
        )
    return GraphResult(status_code=response.status_code, data={"webhook": "accepted"})


def _extract_graph_error(data: Any) -> str | None:
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return error.get("message") or error.get("code")
        if isinstance(error, str):
            return error
    if isinstance(data, str):
        return data[:500]
    return None


def _file_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": str(attachment.get("name") or "attachment"),
        "contentType": str(attachment.get("content_type") or "application/octet-stream"),
        "contentBytes": attachment.get("content_bytes") or "",
    }


def _recipient(item: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(item, str):
        address = item
        name = ""
    else:
        address = str(item.get("address") or item.get("email") or "").strip()
        name = str(item.get("name") or "").strip()
    email_address: dict[str, Any] = {"address": address}
    if name:
        email_address["name"] = name
    return {"emailAddress": email_address}


def _graph_datetime(value: str, default: str) -> dict[str, str]:
    text = str(value or default).strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text:
        text = text.split("+", 1)[0]
    return {"dateTime": text, "timeZone": "UTC"}


def _event_payload(payload: dict[str, Any], *, online_meeting: bool = False) -> dict[str, Any]:
    attendees = payload.get("attendees") or payload.get("to_recipients") or []
    event_payload: dict[str, Any] = {
        "subject": str(payload.get("subject") or payload.get("title") or "Automation HUB").strip(),
        "body": {
            "contentType": str(payload.get("body_content_type") or "HTML"),
            "content": str(payload.get("body") or ""),
        },
        "start": _graph_datetime(str(payload.get("start_datetime") or payload.get("start") or ""), "2026-01-01T09:00:00"),
        "end": _graph_datetime(str(payload.get("end_datetime") or payload.get("end") or ""), "2026-01-01T10:00:00"),
        "attendees": [
            {**_recipient(attendee), "type": "required"}
            for attendee in attendees
            if (isinstance(attendee, str) and attendee.strip()) or (isinstance(attendee, dict) and (attendee.get("address") or attendee.get("email")))
        ],
    }
    if online_meeting:
        event_payload["isOnlineMeeting"] = True
        event_payload["onlineMeetingProvider"] = "teamsForBusiness"
    return event_payload
