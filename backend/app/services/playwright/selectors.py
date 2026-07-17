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

# Botao "Refresh" da aba Files. O proprio Playground avisa: "Please expect a delay for your
# changes to be reflected. Press the refresh button to see the latest changes." Clicar nele
# (em vez de so um F5) traz o status mais recente. E um botao de icone (seta circular), entao
# casamos por nome acessivel / aria-label / title em PT e EN. Se nao achar, cai no F5.
FILES_REFRESH_TEXTS = [
    "Refresh",
    "Reload",
    "Refresh files",
    "Refresh list",
    "Refresh table",
    "Atualizar",
    "Recarregar",
    "Atualizar lista",
    "Atualizar arquivos",
    "Atualizar tabela",
]

# Campo de busca/filtro DENTRO da aba Files de um workspace (PT/EN). Usado para
# localizar uma linha pelo nome quando a leitura por paginacao retorna NotFound.
# Lista multilingue e generica (extensivel); se nenhum campo existir, a busca e ignorada.
FILES_SEARCH_FIELDS = [
    "Search files",
    "Search file",
    "Filter files",
    "Filter file",
    "Search by name",
    "Search documents",
    "Buscar arquivos",
    "Buscar arquivo",
    "Filtrar arquivos",
    "Filtrar arquivo",
    "Pesquisar arquivos",
    "Pesquisar arquivo",
    "Buscar por nome",
    "Search",
    "Buscar",
    "Pesquisar",
    "Filter",
    "Filtrar",
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

# Link/botao que o Playground (AWS Cloudscape) usa para expandir a lista de arquivos
# ja anexados quando ha mais itens do que cabe na area visivel (ex.: "Show more files
# (+1)"). Sem expandir, os nomes dos arquivos ocultos nao aparecem no texto da pagina
# (page_text) e o botao final "Upload files" pode nao habilitar -- ver
# wait_for_selected_files em playground_upload.py.
SHOW_MORE_FILES_TEXTS = [
    "Show more files",
    "Show more file",
    "Show more",
    "Mostrar mais arquivos",
    "Mostrar mais",
    "Ver mais arquivos",
]

# Usado APENAS para detectar que a area de upload ja carregou (gate de prontidao),
# nao para clicar. E proposital que seja mais amplo que UPLOAD_FILES_TEXTS: o clique
# de upload continua usando UPLOAD_FILES_TEXTS (preciso), enquanto a deteccao tolera
# variacoes de rotulo / textos de drag-and-drop do Playground.
UPLOAD_AREA_TEXTS = UPLOAD_FILES_TEXTS + CHOOSE_FILES_TEXTS + [
    "Add files",
    "Add file",
    "Add data",
    "Upload Documents",
    "Upload documents",
    "Carregar arquivos",
    "Adicionar arquivos",
    "Adicionar arquivo",
    "Drag and drop",
    "Drag & drop",
    "Drop files here",
    "Arraste e solte",
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

# Rotulo acessivel (aria-label / titulo) do botao de fechar/dispensar do flashbar/notificacao
# do Cloudscape (AWS) que permanece na tela apos a conclusao de um lote. Usado exclusivamente
# para dispensar o banner de "Upload complete" entre lotes — nunca durante um upload ativo.
# Lista multilingue: estenda, nao substitua.
DISMISS_BANNER_TEXTS = [
    "Dismiss",
    "dismiss",
    "Close",
    "close",
    "Fechar",
    "fechar",
    "Dispensar",
    "dispensar",
    "Fechar notificacao",
    "Fechar notificação",
    "Close notification",
    "Dismiss notification",
]

# Mensagem de erro (vermelho) exibida quando um arquivo corrompido nao pode ser enviado.
# Centralizado aqui para o fluxo de upload detectar e isolar o arquivo culpado.
UPLOAD_ERROR_TEXTS = [
    "Upload Error",
    "Uploading Error",
    "Upload error",
    "Uploading error",
    "Upload failed",
    "Erro no upload",
    "Erro ao enviar",
    "Falha no upload",
]

# Backward-compat alias used by other modules
UPLOAD_PROGRESS_TEXTS = UPLOAD_ACTIVE_TEXTS + UPLOAD_COMPLETE_TEXTS

FILES_TAB_TEXTS = [
    "Files",
    "Arquivos",
    "Status",
]

# Controle de "proxima pagina" da tabela de arquivos (paginacao "< 1 ... >").
NEXT_PAGE_TEXTS = [
    ">",
    "Next",
    "Next page",
    "Proxima",
    "Proxima pagina",
    "Próxima",
    "Próxima página",
]

# Controle de deletar arquivo na coluna "Actions" (icone folha + x, azul).
# A busca e SEMPRE feita dentro da linha do arquivo alvo (row-scoped) e a delecao so e
# considerada efetiva apos a linha sumir no F5 seguinte. AJUSTE/COMPLEMENTE com o
# aria-label/title/classe exatos do icone quando disponivel para deixar o clique cirurgico.
DELETE_FILE_CONTROL_TEXTS = [
    "Delete",
    "Delete file",
    "Remove",
    "Remove file",
    "Excluir",
    "Remover",
    "Apagar",
    "Trash",
    "Lixeira",
]

# Botoes de confirmacao caso a delecao abra um modal de confirmacao.
DELETE_CONFIRM_TEXTS = [
    "Confirm",
    "Confirmar",
    "Yes",
    "Sim",
    "Delete",
    "Excluir",
    "Remove",
    "Remover",
    "OK",
]

READY_STATUS_TEXTS = ["Ready", "Pronto", "Finalizado"]
ERROR_STATUS_TEXTS = ["Error", "Erro", "Failed", "Falha"]
PENDING_STATUS_TEXTS = ["Pending", "Pendente", "Aguardando"]
PROCESSING_STATUS_TEXTS = ["Processing", "Processando", "In progress"]


def text_pattern(values: list[str]) -> re.Pattern[str]:
    escaped = [re.escape(value) for value in values if value]
    return re.compile("|".join(escaped), re.IGNORECASE)
