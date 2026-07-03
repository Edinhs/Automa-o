from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from pydantic_settings import BaseSettings


BACKEND_DIR = Path(__file__).resolve().parents[2]
SUPPORTED_ENVIRONMENTS = ("operational", "developer")
RUNTIME_PATH_NAMES = (
    "BROWSER_SESSION_PATH",
    "SCREENSHOTS_ERROR_PATH",
    "TEMP_PATH",
    "REPORTS_PATH",
    "LOGS_PATH",
    "PROFILE_PHOTOS_PATH",
)
_environment_context: ContextVar[str] = ContextVar("automation_hub_environment", default="operational")


def resolve_backend_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return BACKEND_DIR / path


def normalize_environment(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return "developer" if normalized in {"developer", "development", "dev", "desenvolvedor"} else "operational"


def normalize_url(value: str) -> str:
    normalized = (value or "").strip()
    while normalized.startswith("https://https://"):
        normalized = normalized.replace("https://https://", "https://", 1)
    while normalized.startswith("https://https//"):
        normalized = normalized.replace("https://https//", "https://", 1)
    while normalized.startswith("http://http://"):
        normalized = normalized.replace("http://http://", "http://", 1)
    while normalized.startswith("http://http//"):
        normalized = normalized.replace("http://http//", "http://", 1)
    return normalized


class Settings(BaseSettings):
    APP_NAME: str = "Stellantis Automation HUB"
    APP_ENV: str = "operational"
    APP_TIMEZONE: str = "America/Sao_Paulo"
    AUTH_DISABLED: bool = True
    DATABASE_URL: str = "sqlite:///./data/automation_hub_dev.db"
    OPERATIONAL_DATABASE_URL: str = ""
    DEVELOPER_DATABASE_URL: str = "sqlite:///./data/developer/automation_hub_dev.db"
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    LOCAL_ADMIN_NETWORK_ID: str = "TA25413"
    LOCAL_ADMIN_EMAIL: str = "TA25413@stellantis.com"
    LOCAL_ADMIN_NAME: str = "Ederson Siqueira dos Santos"
    LOCAL_ADMIN_PASSWORD_HASH: str = ""
    PLAYGROUND_URL: str = "https://genai.stellantis.com/"
    PLAYGROUND_BROWSER_CHANNEL: str = "chromium"
    BROWSER_SESSION_PATH: str = "./data/browser_session"
    OPERATIONAL_BROWSER_SESSION_PATH: str = ""
    DEVELOPER_BROWSER_SESSION_PATH: str = "./data/developer/browser_session"
    AGENT_SHARED_TOKEN: str = "local-dev-agent-token"
    AGENT_POLL_INTERVAL_SECONDS: int = 5
    PLAYWRIGHT_HEADLESS: bool = False
    MANUAL_LOGIN_TIMEOUT_MINUTES: int = 10
    PLAYWRIGHT_DEFAULT_TIMEOUT: int = 30000
    WORKSPACE_AREA_TIMEOUT_MS: int = 30000
    SCREENSHOTS_ERROR_PATH: str = "./data/screenshots/errors"
    OPERATIONAL_SCREENSHOTS_ERROR_PATH: str = ""
    DEVELOPER_SCREENSHOTS_ERROR_PATH: str = "./data/developer/screenshots/errors"
    UPLOAD_BATCH_SIZE: int = 5
    # SLAs de confirmacao de upload (segundos) -- externalizados para permitir ajuste operacional
    # via .env sem rebuild. NAO enfraquecer a heuristica de confirmacao ao mexer nesses valores.
    UPLOAD_COMPLETE_STABLE_SECONDS: int = 3
    BATCH_SENT_TIMEOUT_SECONDS: int = 30
    POST_SENT_ERROR_WATCH_SECONDS: int = 5
    FINAL_BATCH_COMPLETE_TIMEOUT_SECONDS: int = 180
    DEFAULT_BATCH_INTERVAL_SECONDS: int = 8
    DEFAULT_MONITORING_TIMEOUT_MINUTES: int = 30
    DEFAULT_MONITOR_INTERVAL_SECONDS: int = 30
    # Quando True, o monitor LE e CLASSIFICA cada linha (Ready/Processing/Error) e LOGA a decisao
    # de delecao por arquivo, mas NAO clica em deletar nem reenvia (verificacao segura sem efeitos
    # colaterais na web). Pode tambem ser ligado por tarefa via payload {"monitor_dry_run": true}.
    MONITOR_DELETE_DRY_RUN: bool = False
    SCHEDULE_POLL_INTERVAL_SECONDS: int = 5
    TEMP_PATH: str = "./data/temp"
    REPORTS_PATH: str = "./data/reports"
    LOGS_PATH: str = "./data/logs"
    PROFILE_PHOTOS_PATH: str = "./data/profile_photos"
    OPERATIONAL_TEMP_PATH: str = ""
    OPERATIONAL_REPORTS_PATH: str = ""
    OPERATIONAL_LOGS_PATH: str = ""
    OPERATIONAL_PROFILE_PHOTOS_PATH: str = ""
    DEVELOPER_TEMP_PATH: str = "./data/developer/temp"
    DEVELOPER_REPORTS_PATH: str = "./data/developer/reports"
    DEVELOPER_LOGS_PATH: str = "./data/developer/logs"
    DEVELOPER_PROFILE_PHOTOS_PATH: str = "./data/developer/profile_photos"
    PROFILE_PHOTO_MAX_BYTES: int = 2 * 1024 * 1024
    MS_GRAPH_TENANT_ID: str = ""
    MS_GRAPH_CLIENT_ID: str = ""
    MS_GRAPH_CLIENT_SECRET: str = ""
    MS_GRAPH_SCOPE: str = "https://graph.microsoft.com/.default"
    MS_GRAPH_SENDER_USER: str = ""
    MS_GRAPH_TEAMS_TEAM_ID: str = ""
    MS_GRAPH_TEAMS_CHANNEL_ID: str = ""
    MS_GRAPH_TEAMS_WEBHOOK_URL: str = ""
    MS_GRAPH_TIMEOUT_SECONDS: int = 20
    REPORT_DELIVERY_PATH: str = ""
    OPERATIONAL_REPORT_DELIVERY_PATH: str = ""
    DEVELOPER_REPORT_DELIVERY_PATH: str = ""
    # URL HTTPS publica da logo exibida no topo do Adaptive Card do Teams (vazio = sem imagem).
    REPORT_CARD_LOGO_URL: str = ""
    # Minutos de setup manual poupados por arquivo enviado ao workspace (encontrar + subir).
    # Vira "horas economizadas" no card semanal (semana + acumulado). Ajuste se incluir controle de erro.
    REPORT_MINUTES_PER_FILE: float = 4.0
    # URL do botao "Solicitar acesso" no Adaptive Card (link da app Workflows do Teams). Vazio = sem botao.
    REPORT_CARD_ACCESS_URL: str = ""
    # URL do botao "Abrir Playground" no Adaptive Card semanal. Vazio = usa PLAYGROUND_URL.
    REPORT_CARD_PLAYGROUND_URL: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
settings.PLAYGROUND_URL = normalize_url(settings.PLAYGROUND_URL)


def current_environment() -> str:
    return _environment_context.get()


def set_current_environment(value: str | None) -> Token:
    return _environment_context.set(normalize_environment(value))


def reset_current_environment(token: Token) -> None:
    _environment_context.reset(token)


@contextmanager
def environment_scope(value: str | None):
    token = set_current_environment(value)
    try:
        yield current_environment()
    finally:
        reset_current_environment(token)


def database_url_for_environment(environment: str | None = None) -> str:
    selected = normalize_environment(environment or current_environment())
    if selected == "developer":
        return settings.DEVELOPER_DATABASE_URL or settings.DATABASE_URL
    return settings.OPERATIONAL_DATABASE_URL or settings.DATABASE_URL


def runtime_setting(name: str, environment: str | None = None) -> str:
    selected = normalize_environment(environment or current_environment())
    prefix = "DEVELOPER" if selected == "developer" else "OPERATIONAL"
    environment_value = str(getattr(settings, f"{prefix}_{name}", "") or "").strip()
    return environment_value or str(getattr(settings, name))


def runtime_path(name: str, environment: str | None = None) -> Path:
    return resolve_backend_path(runtime_setting(name, environment))


def report_delivery_dir(environment: str | None = None) -> Path | None:
    value = str(runtime_setting("REPORT_DELIVERY_PATH", environment) or "").strip()
    return resolve_backend_path(value) if value else None


def ensure_data_directories(environment: str | None = None) -> None:
    for name in RUNTIME_PATH_NAMES:
        runtime_path(name, environment).mkdir(parents=True, exist_ok=True)


for configured_environment in SUPPORTED_ENVIRONMENTS:
    ensure_data_directories(configured_environment)
