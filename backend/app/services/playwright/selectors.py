from __future__ import annotations

import re


LOGGED_IN_TEXTS = [
    "Workspaces",
    "All my Workspaces",
    "All Workspaces",
    "All Workspace",
    "New Workspace",
    "Create Workspace",
    "Creat Workspace",
    "Upload files",
    "Upload Files",
    "My Workspaces",
]

LOGIN_TEXTS = [
    "Stellantis Login",
    "Sign in",
    "Sign In",
    "Login",
    "Log in",
    "Entrar",
    "Microsoft",
    "Use your account",
    "Email",
    "E-mail",
    "Password",
    "Senha",
]

LOGIN_URL_MARKERS = [
    "login",
    "signin",
    "sign-in",
    "saml",
    "oauth",
    "authorize",
    "microsoftonline",
    "adfs",
]

STELLANTIS_LOGIN_TEXTS = [
    "Stellantis Login",
    "Login Stellantis",
    "Sign in with Stellantis",
    "Entrar com Stellantis",
]

NETWORK_ID_FIELDS = [
    "ID de rede",
    "Network ID",
    "User ID",
    "Username",
    "Email",
    "E-mail",
]

ALL_WORKSPACE_TEXTS = [
    "All my Workspaces",
    "All Workspace",
    "All Workspaces",
    "Workspaces",
    "My Workspaces",
]

WORKSPACE_FILTER_FIELDS = [
    "Filter Workspace",
    "Filter Workspaces",
    "Filter workspace",
    "Filter workspaces",
    "Search Workspace",
    "Search Workspaces",
    "Search",
    "Buscar",
    "Pesquisar",
    "Workspace",
]

CREATE_WORKSPACE_TEXTS = [
    "Create Workspace",
    "Creat Workspace",
    "New Workspace",
]

WORKSPACE_NAME_FIELDS = [
    "Workspace Name",
    "Workspace name",
    "Name",
    "Nome do Workspace",
]

WORKSPACE_DESCRIPTION_FIELDS = [
    "Description",
    "Descricao",
    "Descrição",
]

EMBEDDING_MODEL_FIELDS = [
    "Embeddings Model",
    "Embedding Model",
    "Model",
    "Modelo de embeddings",
]

DATA_LANGUAGE_FIELDS = [
    "Data Languages",
    "Data Language",
    "Data languages",
    "Data language",
    "Data language(s)",
    "Languages",
    "Language",
    "Idiomas dos dados",
]

USER_MANAGEMENT_TEXTS = [
    "User Management",
    "Users Management",
    "Manage Users",
    "Users",
    "Gerenciar usuarios",
    "Gerenciar usuários",
]

ADD_USER_TEXTS = [
    "Add User",
    "Add user",
    "Adicionar usuario",
    "Adicionar usuário",
]

USER_IDENTIFIER_FIELDS = [
    "ID de rede",
    "Network ID",
    "User",
    "User ID",
    "Email",
    "E-mail",
]

ROLE_TEXTS = {
    "reader": ["Reader", "Leitor"],
    "coowner": ["Coowner", "Co-owner", "Co Owner", "Proprietario", "Proprietário"],
}

UPLOAD_FILES_TEXTS = [
    "Upload Files",
    "Upload files",
    "Upload file",
    "Enviar arquivos",
]

CHOOSE_FILES_TEXTS = [
    "Choose Files",
    "Choose files",
    "Choose File",
    "Browse files",
    "Selecionar arquivos",
]

UPLOAD_ACTIVE_TEXTS = [
    "Uploading Files",
    "Uploading files",
    "Enviando arquivos",
]

UPLOAD_COMPLETE_TEXTS = [
    "Upload complete",
    "Uploaded",
    "Concluido",
    "Concluído",
]

# Backward-compat alias used by other modules
UPLOAD_PROGRESS_TEXTS = UPLOAD_ACTIVE_TEXTS + UPLOAD_COMPLETE_TEXTS

FILES_TAB_TEXTS = [
    "Files",
    "Arquivos",
]

READY_STATUS_TEXTS = ["Ready", "Pronto", "Finalizado"]
ERROR_STATUS_TEXTS = ["Error", "Erro", "Failed", "Falha"]
PENDING_STATUS_TEXTS = ["Pending", "Pendente", "Aguardando"]
PROCESSING_STATUS_TEXTS = ["Processing", "Processando", "In progress"]


def text_pattern(values: list[str]) -> re.Pattern[str]:
    escaped = [re.escape(value) for value in values if value]
    return re.compile("|".join(escaped), re.IGNORECASE)
