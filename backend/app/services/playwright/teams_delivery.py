from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Optional

from app.core.config import runtime_path, settings
from app.services.playwright.browser import open_persistent_chromium, safe_error_screenshot
from app.services.playwright.errors import PlaywrightAutomationError

class TeamsLoginRequired(PlaywrightAutomationError):
    """Lançada quando a sessão do Teams expirou ou necessita de login manual."""
    pass

class TeamsDeliveryError(PlaywrightAutomationError):
    """Lançada quando ocorre uma falha na automação do Teams Web."""
    pass


def is_teams_logged_in(page) -> bool:
    """Verifica se o Teams Web esta logado avaliando a URL e a presenca de elementos do chat.
    
    Seletores calibrados em 2026-07-17 via inspecao ao vivo do Teams Web PT-BR v2.
    """
    current_url = (page.url or "").lower()
    # Se a URL contiver dominios de login, nao esta logado
    if any(marker in current_url for marker in ["login.microsoftonline.com", "signin", "login.live.com"]):
        return False
    try:
        # Seletor primario calibrado: input[type="search"] e o unico encontrado na inspecao 2026-07-17
        if page.locator('input[type="search"]').count() > 0:
            return True
        # Fallbacks adicionais
        if page.locator('[data-tid="chat-list"], [data-tid="app-layout"]').count() > 0:
            return True
        # Se URL e teams.microsoft.com sem redirect de auth, assume logado
        if "teams.microsoft.com" in current_url and "auth" not in current_url:
            return True
    except Exception:
        pass
    return False



def wait_for_teams_login(page, log: Callable, timeout_minutes: int = 5) -> None:
    """Aguardará o login manual do usuário na janela do Teams Web."""
    log("info", "Aguardando login interativo no Teams Web. Por favor, realize o login SSO na janela do navegador.")
    deadline = time.monotonic() + (timeout_minutes * 60)
    while time.monotonic() < deadline:
        if is_teams_logged_in(page):
            log("info", "Login no Teams detectado com sucesso!")
            time.sleep(5)  # Espera estabilizar
            return
        time.sleep(2)
    raise TeamsLoginRequired("Timeout ao aguardar login manual no Teams Web.")


def navigate_to_chat(page, chat_name: str, log: Callable) -> None:
    """Navega até o chat especificado procurando nos chats recentes ou usando a barra de busca.
    
    Seletores calibrados em 2026-07-17 via inspecao ao vivo do Teams Web PT-BR v2.
    """
    log("info", f"Procurando pelo chat '{chat_name}'...")

    # 1) Tenta encontrar diretamente na lista lateral de chats recentes por texto
    sidebar_selectors = [
        f'span:has-text("{chat_name}")',
        f'div:has-text("{chat_name}")',
    ]
    for sel in sidebar_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                # Filtra para elemento visivel e clicavel
                for i in range(min(loc.count(), 5)):
                    item = loc.nth(i)
                    try:
                        if item.is_visible() and item.bounding_box():
                            item.click(timeout=3000)
                            log("info", f"Chat '{chat_name}' selecionado via lista recente.")
                            time.sleep(2)
                            return
                    except Exception:
                        continue
        except Exception:
            continue

    # 2) Fallback: barra de busca global (Ctrl+Alt+G no Teams v2 abre a barra)
    # Seletor calibrado: input[type="search"] é o unico encontrado na inspecao de 2026-07-17
    search_inputs = [
        'input[type="search"]',
        'input[placeholder*="Ctrl"]',
        '[data-tid="search-box"] input',
        'input[aria-label*="Buscar"]',
        'input[aria-label*="Search"]',
    ]
    search_input = None
    for sel in search_inputs:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                search_input = loc.first
                log("info", f"Barra de busca localizada: {sel!r}")
                break
        except Exception:
            continue

    if not search_input:
        # Tenta pressionar Ctrl+Alt+G para abrir a caixa de busca do Teams
        page.keyboard.press("Control+Alt+g")
        time.sleep(2)
        for sel in search_inputs:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    search_input = loc.first
                    log("info", f"Barra de busca aberta via Ctrl+Alt+G: {sel!r}")
                    break
            except Exception:
                continue

    if not search_input:
        raise TeamsDeliveryError("Nao foi possivel localizar a barra de pesquisa do Teams Web.")

    search_input.click(timeout=5000)
    time.sleep(1)
    search_input.fill("")
    search_input.type(chat_name, delay=80)
    log("info", f"Texto '{chat_name}' digitado na barra de busca.")
    time.sleep(3)  # Aguarda resultados da busca aparecerem

    # Clica no primeiro resultado que corresponde ao nome
    result_selectors = [
        f'[role="option"]:has-text("{chat_name}")',
        f'[role="listitem"]:has-text("{chat_name}")',
        f'li:has-text("{chat_name}")',
        '[role="option"]',
        '[role="listitem"]',
    ]
    clicked = False
    for sel in result_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=4000)
                clicked = True
                log("info", f"Chat '{chat_name}' selecionado via resultado da busca.")
                break
        except Exception:
            continue

    if not clicked:
        page.keyboard.press("Enter")
        time.sleep(2)
        log("info", "Pressionado Enter para selecionar o primeiro resultado (fallback).")

    time.sleep(3)


def attach_files_via_picker(page, attachment_paths: list[str], log: Callable) -> None:
    """Anexa arquivos locais a mensagem usando o botao real 'Anexar arquivos' do Teams Web.

    Calibrado ao vivo em 2026-07-20: NAO existe `input[type="file"]` no DOM ate o usuario
    interagir com o menu de anexo. O fluxo real e:
      1. Clicar no botao `[data-tid="sendMessageCommands-FilePicker"]` (aria-label
         "Anexar arquivos") -- abre um menu com "Anexar arquivos da nuvem" e
         "Carregar deste dispositivo".
      2. Clicar em "Carregar deste dispositivo" -- isso dispara o dialogo NATIVO do
         Windows, interceptado aqui via `page.expect_file_chooser()` (sem abrir UI real).
      3. `file_chooser.set_files(...)` injeta os caminhos locais no dialogo interceptado.
      4. Aguarda o nome do arquivo aparecer como preview na caixa de composicao antes de
         prosseguir -- so assim o anexo e considerado confirmado (evita "sucesso" falso
         quando o Teams silenciosamente ignora o anexo).

    Lanca TeamsDeliveryError se o botao/menu nao forem encontrados ou se o preview do
    anexo nao aparecer -- APOS uma falha aqui, o chamador NAO deve reportar a task como
    bem-sucedida so com o texto (isso mascarava o problema antes desta calibracao).
    """
    attach_button = page.locator('[data-tid="sendMessageCommands-FilePicker"]')
    if attach_button.count() == 0:
        attach_button = page.locator('button[aria-label="Anexar arquivos"], button[aria-label="Attach files"]')
    if attach_button.count() == 0:
        raise TeamsDeliveryError("Botao 'Anexar arquivos' nao encontrado no Teams Web.")

    try:
        with page.expect_file_chooser(timeout=10000) as fc_info:
            attach_button.first.click(timeout=5000)
            time.sleep(1)
            upload_item = page.get_by_text("Carregar deste dispositivo", exact=False)
            if upload_item.count() == 0:
                upload_item = page.get_by_text("Upload from this device", exact=False)
            upload_item.first.click(timeout=5000)
        file_chooser = fc_info.value
    except Exception as exc:
        raise TeamsDeliveryError(f"Nao foi possivel abrir o seletor de arquivos do Teams: {exc}") from exc

    file_chooser.set_files(attachment_paths)
    log("info", f"Arquivo(s) enviado(s) ao seletor nativo: {[Path(p).name for p in attachment_paths]}")

    # Confirma que o anexo realmente apareceu no preview da composicao (nao so que o
    # dialogo foi aceito) antes de considerar o anexo bem-sucedido.
    for file_path in attachment_paths:
        file_name = Path(file_path).name
        try:
            page.get_by_text(file_name, exact=False).first.wait_for(state="visible", timeout=20000)
            log("info", f"Anexo confirmado no preview da composicao: {file_name}")
        except Exception as exc:
            raise TeamsDeliveryError(
                f"Anexo '{file_name}' nao apareceu no preview da composicao apos o upload."
            ) from exc


def send_message_with_attachments(
    page,
    text_message: str,
    attachment_paths: list[str],
    log: Callable
) -> None:
    """Preenche o campo de mensagem, faz upload dos anexos e envia.

    Seletores calibrados em 2026-07-17 via inspecao ao vivo Teams Web PT-BR v2:
      - div[role="textbox"]          => count=1, aria-label='Digite uma mensagem'
      - div[contenteditable="true"]  => count=1, aria-label='Digite uma mensagem'
    ATENCAO: '[aria-label*="mensagem"]' retorna 13 elementos — NAO usar como primario.
    """
    log("info", "Preparando para redigir a mensagem no Teams...")

    # Aguarda o chat carregar o textbox (maximo 15s)
    try:
        page.wait_for_selector('div[role="textbox"]', timeout=15000)
        log("info", "Textbox detectado pelo wait_for_selector.")
    except Exception:
        log("warning", "wait_for_selector para textbox nao respondeu em 15s. Tentando mesmo assim...")

    # Seletores calibrados — do mais especifico para o mais generico
    # ORDEM IMPORTA: evitar seletores com count > 1 no inicio
    textbox_selectors = [
        'div[role="textbox"]',                            # count=1  OK
        'div[contenteditable="true"]',                    # count=1  OK
        'div[class*="ck-content"]',                       # count=1  OK
        '[aria-label="Digite uma mensagem"]',             # count=1  OK (exact match)
        '[aria-label="Type a message"]',                  # count=1  OK (exact match en)
        '[aria-label*="Digite"]',                         # count=1  OK
    ]
    textbox = None
    for sel in textbox_selectors:
        try:
            loc = page.locator(sel)
            cnt = loc.count()
            if cnt > 0:
                candidate = loc.first
                if candidate.is_visible():
                    textbox = candidate
                    log("info", f"Textbox localizado: {sel!r} (count={cnt})")
                    break
        except Exception:
            continue

    if not textbox:
        raise TeamsDeliveryError("Nao foi possivel localizar a caixa de texto da mensagem no Teams.")

    textbox.click()
    time.sleep(1)
    # Limpa e digita
    try:
        textbox.fill(text_message)
    except Exception:
        textbox.type(text_message, delay=10)
    time.sleep(2)

    # Upload de anexos — usa o fluxo real do botao "Anexar arquivos" (ver
    # attach_files_via_picker). Se algum anexo for solicitado e falhar, a task FALHA
    # (nao envia so o texto silenciosamente) para nao mascarar o problema.
    valid_attachments = [p for p in attachment_paths if p and Path(p).exists()]
    if valid_attachments:
        log("info", f"Fazendo upload de {len(valid_attachments)} arquivo(s).")
        attach_files_via_picker(page, valid_attachments, log)
        time.sleep(3)

    # Botao Enviar — calibrado para Teams PT-BR 2026-07-17
    send_selectors = [
        'button[data-tid="send-message-button"]',
        'button[aria-label="Enviar"]',
        'button[aria-label="Send"]',
        'button[title="Enviar"]',
        'button[title="Send"]',
        'button:has(svg[data-tid="send-icon"])',
    ]
    sent = False
    for sel in send_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_enabled():
                loc.first.click(timeout=5000)
                log("info", f"Botao Enviar clicado: {sel!r}")
                sent = True
                break
        except Exception:
            continue

    if not sent:
        textbox.focus()
        page.keyboard.press("Enter")
        log("info", "Mensagem enviada via tecla Enter (fallback).")

    time.sleep(4)



def _deliver_via_teams_web(
    chat_name: str,
    teams_url: str,
    text_message: str,
    attachment_paths: list[str],
    headless: bool,
    user_id: int,
    task_id: int,
    log: Callable,
) -> dict[str, Any]:
    """Nucleo compartilhado do envio via Teams Web (login/sessao/navegacao/anexos).

    Extraido de deliver_report_teams_playwright para ser reaproveitado tambem por
    deliver_file_teams_playwright (envio de um arquivo avulso, ex.: PNG de pasta monitorada,
    sem vinculo com um report_id do HUB). Nenhum comportamento de login/anexo foi alterado.
    """
    session_dir = runtime_path("TEAMS_BROWSER_SESSION_PATH")

    log("info", f"Iniciando sessao do Teams Web. Headless={headless}, Chat={chat_name}, URL={teams_url}")

    browser = None
    try:
        browser = open_persistent_chromium(
            user_id=user_id,
            headless=headless,
            session_dir=session_dir
        )
        page = browser.page
        
        # Acessa o Teams Web
        page.goto(teams_url, wait_until="domcontentloaded")
        time.sleep(5)  # Espera carregamento básico

        # Checa se precisa de login
        if not is_teams_logged_in(page):
            # Se for headless e precisa de login, lança erro para forçar o retry headed
            if headless:
                log("warning", "Sessao expirada ou login necessario no Teams. Lancando sinal de login interativo.")
                raise TeamsLoginRequired("Login interativo necessario no Teams Web.")
            
            # Se for headed (visível), aguarda o usuário logar
            wait_for_teams_login(page, log, timeout_minutes=settings.MANUAL_LOGIN_TIMEOUT_MINUTES)

        # Navega para o chat
        navigate_to_chat(page, chat_name, log)
        
        # Envia a mensagem e os anexos
        send_message_with_attachments(page, text_message, attachment_paths, log)
        
        log("info", "Mensagem enviada com sucesso ao Teams Web!")
        
        return {
            "status": "success",
            "chat_name": chat_name,
            "attachments_sent": [Path(p).name for p in attachment_paths]
        }

    except TeamsLoginRequired:
        raise
    except Exception as exc:
        safe_error_screenshot(browser.page if browser else None, task_id, log)
        raise TeamsDeliveryError(f"Falha na automacao do Teams Web: {exc}") from exc
    finally:
        if browser:
            browser.close()


def deliver_report_teams_playwright(
    report_id: int,
    payload: dict[str, Any],
    log: Callable,
    task_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Orquestra o fluxo de entrega do relatorio via Teams Web usando Playwright."""
    chat_name = str(payload.get("chat_name") or settings.TEAMS_DELIVERY_CHAT_NAME or "1:1 Ederson").strip()
    teams_url = str(payload.get("teams_url") or settings.TEAMS_WEB_URL or "https://teams.microsoft.com/v2/").strip()
    
    # Resolve caminhos físicos locais
    image_file = payload.get("image_file")
    pdf_file = payload.get("pdf_file")
    text_message = str(payload.get("text_message") or "").strip()

    attachment_paths: list[str] = []
    if image_file and Path(image_file).exists():
        attachment_paths.append(str(image_file))
    if pdf_file and Path(pdf_file).exists():
        attachment_paths.append(str(pdf_file))

    if not text_message:
        text_message = f"Segue o Relatorio Semanal de Adocao (ID: {report_id})."

    headless = payload.get("headless")
    if headless is None:
        headless = settings.PLAYWRIGHT_HEADLESS

    return _deliver_via_teams_web(
        chat_name, teams_url, text_message, attachment_paths, headless, user_id, task_id, log
    )


def deliver_file_teams_playwright(
    payload: dict[str, Any],
    log: Callable,
    task_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Envia um ARQUIVO AVULSO (ex.: PNG gerado por processo externo em uma pasta monitorada)
    diretamente para um chat/canal do Teams, sem vinculo com um report_id do HUB.

    Usado pela automacao 'PNG -> Teams' (ver app/services/teams_png_watch.py): a pasta
    configurada em TEAMS_PNG_WATCH_FOLDER e vigiada por agendamento/monitoramento continuo;
    quando um arquivo novo (por hash) aparece, esta funcao envia SO esse arquivo.
    """
    file_path = str(payload.get("file_path") or "").strip()
    if not file_path or not Path(file_path).exists():
        raise TeamsDeliveryError(f"Arquivo nao encontrado para envio ao Teams: {file_path or '(vazio)'}")

    chat_name = str(payload.get("chat_name") or settings.TEAMS_DELIVERY_CHAT_NAME or "1:1 Ederson").strip()
    teams_url = str(payload.get("teams_url") or settings.TEAMS_WEB_URL or "https://teams.microsoft.com/v2/").strip()
    text_message = str(payload.get("text_message") or "").strip() or f"Novo arquivo disponivel: {Path(file_path).name}"

    headless = payload.get("headless")
    if headless is None:
        headless = settings.PLAYWRIGHT_HEADLESS

    result = _deliver_via_teams_web(
        chat_name, teams_url, text_message, [file_path], headless, user_id, task_id, log
    )
    result["file_path"] = file_path
    return result
