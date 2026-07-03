from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Optional

from app.core.config import settings
from app.services.playwright.browser import click_first, open_persistent_chromium, page_text, safe_error_screenshot, wait_for_text
from app.services.playwright.errors import PlaywrightAutomationError
from app.services.playwright.playground_login import configured_playground_url, ensure_logged_in
from app.services.playwright.playground_workspace import open_workspace, wait_for_workspace_area
from app.services.playwright.selectors import (
    DELETE_CONFIRM_TEXTS,
    DELETE_FILE_CONTROL_TEXTS,
    ERROR_STATUS_TEXTS,
    FILES_REFRESH_TEXTS,
    FILES_SEARCH_FIELDS,
    FILES_TAB_TEXTS,
    NEXT_PAGE_TEXTS,
    PENDING_STATUS_TEXTS,
    PROCESSING_STATUS_TEXTS,
    READY_STATUS_TEXTS,
)


NAME_HEADERS = ["name", "nome"]
STATUS_HEADERS = ["status"]
FILES_TABLE_TEXTS = ["Name", "Status", "Upload date", "Size", "Actions"]
FOUND_STATUSES = {"Ready", "Error", "Processing", "Pending"}

# Textos que indicam que a tabela ainda esta carregando ou esta vazia (PT/EN).
# Linhas cujo nome case um desses textos sao IGNORADAS — nunca tratadas como arquivo real.
# Adione variacoes; nao substitua.
LOADING_ROW_TEXTS = [
    "loading files",
    "loading",
    "carregando",
    "carregando arquivos",
    "loading files...",
    "no items",
    "sem itens",
    "nenhum arquivo",
    "no files",
    "no files found",
    "nenhum arquivo encontrado",
]

# "NotFound" NAO e um status real do Playground (essa frase nao existe na coluna Status): e o
# marcador interno para "a linha do arquivo nao foi lida nesta passagem" (timing/paginacao).
# Quando aparece, reiniciamos a leitura COMPLETA do monitoramento ate este numero de tentativas
# (F5 + nova varredura de todas as paginas) antes de tratar o arquivo como revisao manual. Assim
# uma leitura falha nunca e confundida com "arquivo ausente" (o que dispararia reenvio/duplicacao).
MONITOR_NOTFOUND_READ_ATTEMPTS = 3
MONITOR_NOTFOUND_READ_PAUSE_SECONDS = 5


def check_continue(should_continue: Callable[[], bool] | None) -> None:
    if should_continue:
        should_continue()


def clean_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _norm(value: str) -> str:
    """Normaliza para comparacao: NFC (acentos com mesma codificacao) + espacos + minusculas."""
    return unicodedata.normalize("NFC", clean_text(value)).lower()


def _truncation_match(norm_name: str, stem: str, norm_row: str) -> bool:
    """Cobre nomes exibidos truncados com reticencias ('relatorio_muito_long…').

    Pega o fragmento antes das reticencias e confirma se ele aparece no nome esperado.
    Exige um trecho significativo (>=8 chars) para nao casar fragmentos genericos.
    """
    if "…" not in norm_row and "..." not in norm_row:
        return False
    for marker in ("…", "..."):
        if marker not in norm_row:
            continue
        frag = norm_row.split(marker, 1)[0].strip()
        if len(frag) < 8:
            continue
        tail = frag[-40:]  # parte final do fragmento (mais especifica do nome)
        if tail and (tail in norm_name or (stem and tail in stem)):
            return True
    return False


def _row_name_from_structured(row: dict[str, Any]) -> str:
    """Extrai o nome de arquivo da linha estruturada usando alinhamento por cabecalho."""
    cells = [clean_text(c) for c in (row.get("cells") or [])]
    headers = [clean_text(h) for h in (row.get("headers") or [])]
    return _name_from_aligned(headers, cells)


def match_name_in_rows(
    name: str,
    structured_rows: list[dict[str, Any]],
    row_texts: list[str],
) -> tuple[str, str]:
    """Localiza a linha do arquivo de forma tolerante e retorna (match_text, status_text).

    Casamento em camadas, da mais forte para a mais fraca.
    IMPORTANTE: usa _row_identity_matches (igualdade de nome ou stem) em vez de substring
    para evitar que 'data.csv' case 'metadata.csv' — causa historica do delete da 1a linha.

      1. IDENTIDADE por nome completo ou stem — linhas estruturadas (nome extraido do campo
         Name pelo indice de coluna), depois texto bruto (word-boundary aproximado);
      2. TRUNCAMENTO por reticencias — nomes longos cortados pela UI (fallback seguro).
    Retorna ("", "") se nada casar (vira NotFound a montante).
    """
    norm_name = _norm(name)
    stem = _norm(Path(name).stem)

    def row_text_of(row: dict[str, Any]) -> str:
        return clean_text(row.get("text") or " ".join(row.get("cells") or []))

    # Camada 1a: identidade via nome extraido da coluna Name (mais cirurgico).
    for row in structured_rows:
        row_name = _row_name_from_structured(row)
        if row_name and _row_identity_matches(row_name, name):
            return row_text_of(row), status_text_from_row(row, name)

    # Camada 1b: identidade via texto bruto da linha.
    # Usamos word-boundary aproximado: o nome deve aparecer como token delimitado por
    # espaco/inicio/fim de string, evitando casamento como substring de outro nome.
    if norm_name:
        for rt in row_texts:
            rt_norm = _norm(rt)
            # Verifica se norm_name aparece como "palavra" no texto (delimitado por espacos ou bordas)
            if rt_norm == norm_name or rt_norm.startswith(norm_name + " ") or (" " + norm_name) in rt_norm:
                return clean_text(rt), clean_text(rt)
        # Fallback de stem para texto bruto (cobre conversao .docx->.pdf)
        if len(stem) >= 4:
            for rt in row_texts:
                rt_norm = _norm(rt)
                if rt_norm == stem or rt_norm.startswith(stem + " ") or (" " + stem) in rt_norm:
                    return clean_text(rt), clean_text(rt)

    # Camada 2: truncamento por reticencias (nomes longos cortados pela UI).
    for row in structured_rows:
        text = row_text_of(row)
        if _truncation_match(norm_name, stem, _norm(text)):
            return text, status_text_from_row(row, name)
    for rt in row_texts:
        if _truncation_match(norm_name, stem, _norm(rt)):
            return clean_text(rt), clean_text(rt)

    return "", ""


def normalize_status(text: str) -> str:
    lower = (text or "").lower()
    if any(value.lower() in lower for value in READY_STATUS_TEXTS):
        return "Ready"
    if any(value.lower() in lower for value in ERROR_STATUS_TEXTS):
        return "Error"
    if any(value.lower() in lower for value in PROCESSING_STATUS_TEXTS):
        return "Processing"
    if any(value.lower() in lower for value in PENDING_STATUS_TEXTS):
        return "Pending"
    return "Unknown"


def open_files_tab(page, log: Callable) -> None:
    clicked = click_first(
        [lambda text=text: page.get_by_role("tab", name=text) for text in FILES_TAB_TEXTS]
        + [lambda text=text: page.get_by_role("button", name=text) for text in FILES_TAB_TEXTS]
        + [lambda text=text: page.get_by_text(text, exact=True) for text in FILES_TAB_TEXTS],
        timeout_ms=5000,
    )
    if clicked:
        log("info", "Aba Files aberta.")
    elif "files" in page_text(page).lower() or "arquivos" in page_text(page).lower():
        log("info", "Aba Files ja estava visivel.")
    else:
        raise PlaywrightAutomationError("Aba Files nao encontrada.")
    wait_for_text(page, FILES_TABLE_TEXTS, timeout_ms=10000)


def refresh_files_list(page, log: Callable, settle_seconds: float = 1.5) -> bool:
    """Clica no botao Refresh da aba Files para trazer o status mais recente.

    O Playground avisa que ha atraso ate a mudanca refletir e pede para clicar em Refresh.
    No DOM ao vivo o Refresh e um botao de ICONE sem texto/aria (Cloudscape, variant-normal +
    button-no-text). Tentamos, em ordem: (1) nome acessivel/aria/title (UIs rotuladas), (2) icone
    Cloudscape 'refresh' nomeado, (3) o UNICO botao de icone normal sem texto da tela (guarda
    count()==1 para nunca clicar no botao errado). Best-effort: se nada casar, retorna False e o
    chamador segue com F5 (que ja traz dados frescos do servidor).
    """

    def _try_click(loc) -> bool:
        try:
            if loc.count() and loc.first.is_visible(timeout=400):
                loc.first.click(timeout=1500)
                return True
        except Exception:
            return False
        return False

    clicked = False
    # 1) Por nome acessivel / aria-label / title (UIs que rotulam o botao).
    for text in FILES_REFRESH_TEXTS:
        if (
            _try_click(page.get_by_role("button", name=text))
            or _try_click(page.locator(f"button[aria-label*='{text}' i]"))
            or _try_click(page.locator(f"button[title*='{text}' i]"))
        ):
            clicked = True
            break
    # 2) Icone Cloudscape 'refresh' nomeado (deployments que usam iconName="refresh").
    if not clicked:
        clicked = _try_click(page.locator('button:has([class*="awsui_name-refresh"])'))
    # 3) Cloudscape sem nome: o unico botao de icone normal sem texto da tela e o Refresh.
    #    Guarda count()==1 para nunca clicar em outro botao por engano.
    if not clicked:
        loc = page.locator('button[class*="awsui_button-no-text"][class*="awsui_variant-normal"]')
        try:
            if loc.count() == 1 and loc.first.is_visible(timeout=400):
                loc.first.click(timeout=1500)
                clicked = True
        except Exception:
            pass

    if clicked:
        log("info", "Lista de arquivos atualizada (botao Refresh da aba Files).")
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        try:
            wait_for_text(page, FILES_TABLE_TEXTS, timeout_ms=8000)
        except Exception:
            pass
        return True
    return False


def expected_file_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("file_name") or item.get("name") or Path(str(item.get("path") or item.get("temp_path") or "")).name)
    return Path(str(item)).name


def read_structured_file_rows(page) -> list[dict[str, Any]]:
    try:
        rows = page.evaluate(
            """
            () => {
              const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
              const textOf = (element) => {
                if (!element) return '';
                const parts = [
                  element.innerText || element.textContent || '',
                  element.getAttribute('aria-label') || '',
                  element.getAttribute('title') || '',
                ];
                element.querySelectorAll('[aria-label], [title]').forEach((child) => {
                  parts.push(child.getAttribute('aria-label') || '');
                  parts.push(child.getAttribute('title') || '');
                });
                return clean(parts.filter(Boolean).join(' '));
              };
              const result = [];
              document.querySelectorAll('table').forEach((table) => {
                const headers = Array.from(table.querySelectorAll('thead th, thead [role="columnheader"]'))
                  .map(textOf)
                  .filter(Boolean);
                table.querySelectorAll('tbody tr').forEach((row) => {
                  const cells = Array.from(row.querySelectorAll('td, th, [role="cell"], [role="gridcell"]'))
                    .map(textOf)
                    .filter(Boolean);
                  const text = textOf(row);
                  if (cells.length || text) result.push({ source: 'table', headers, cells, text });
                });
              });
              document.querySelectorAll('[role="row"]').forEach((row) => {
                if (row.closest('table')) return;
                const cells = Array.from(row.querySelectorAll('[role="cell"], [role="gridcell"], td, th'))
                  .map(textOf)
                  .filter(Boolean);
                const text = textOf(row);
                if (cells.length || text) result.push({ source: 'role-row', headers: [], cells, text });
              });
              return result;
            }
            """
        )
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def header_index(headers: list[str], aliases: list[str]) -> int | None:
    normalized = [clean_text(header).lower() for header in headers]
    for index, header in enumerate(normalized):
        if any(alias in header for alias in aliases):
            return index
    return None


def status_text_from_row(row: dict[str, Any], expected_name: str) -> str:
    cells = [clean_text(cell) for cell in row.get("cells") or [] if clean_text(cell)]
    headers = [clean_text(header) for header in row.get("headers") or [] if clean_text(header)]
    status_index = header_index(headers, STATUS_HEADERS)
    if status_index is not None and status_index < len(cells):
        return cells[status_index]

    name_index = header_index(headers, NAME_HEADERS)
    for index, cell in enumerate(cells):
        if name_index is not None and index == name_index:
            continue
        if expected_name.lower() in cell.lower():
            continue
        if normalize_status(cell) != "Unknown":
            return cell
    return clean_text(row.get("text") or "")


def read_file_statuses(page, expected_names: list[str]) -> dict[str, dict[str, str]]:
    statuses: dict[str, dict[str, str]] = {}
    structured_rows = read_structured_file_rows(page)
    row_selectors = ["table tbody tr", "[role='row']"]
    row_texts: list[str] = []
    for selector in row_selectors:
        try:
            rows = page.locator(selector)
            count = min(rows.count(), 300)
            for index in range(count):
                text = rows.nth(index).inner_text(timeout=1000)
                if text:
                    row_texts.append(text)
        except Exception:
            continue
    if not row_texts:
        row_texts = [page_text(page)]

    for name in expected_names:
        match_text, status_text = match_name_in_rows(name, structured_rows, row_texts)
        if match_text:
            statuses[name] = {
                "status": normalize_status(status_text or match_text),
                "raw": match_text,
                "status_text": status_text or match_text,
            }
        else:
            statuses[name] = {"status": "NotFound", "raw": "", "status_text": ""}
    return statuses


def statuses_have_expected_rows(statuses: dict[str, dict[str, str]]) -> bool:
    return any(data.get("status") in FOUND_STATUSES for data in statuses.values())


def wait_for_expected_rows(
    page,
    expected_names: list[str],
    timeout_seconds: int,
    should_continue: Callable[[], bool] | None = None,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + max(1, timeout_seconds)
    statuses: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        check_continue(should_continue)
        statuses = read_file_statuses(page, expected_names)
        if statuses_have_expected_rows(statuses):
            return statuses
        time.sleep(1)
    return statuses or read_file_statuses(page, expected_names)


def wait_for_files_table_ready(
    page,
    should_continue: Callable[[], bool] | None = None,
    timeout_seconds: int = 15,
) -> bool:
    """Aguarda ate que a tabela de arquivos tenha ao menos UMA linha real (nao de carregamento).

    Necessario apos F5/reopen para evitar que locate_target_paginated leia a tabela
    antes de ela terminar de carregar — o que causaria "absent" falso num arquivo existente.

    Considera "pronta" quando iter_page_file_rows retorna ao menos uma linha cujo nome
    NAO e um placeholder de carregamento (LOADING_ROW_TEXTS). Retorna True se a tabela
    ficou pronta dentro do prazo; False se o timeout expirou (o chamador segue assim mesmo,
    pois pode ser um workspace realmente vazio).

    NOTA: prefira wait_for_files_table_stable sempre que possivel — ela garante tambem que
    a contagem de linhas PAROU DE CRESCER, evitando leituras de tabelas renderizadas
    parcialmente (race condition de incremental rendering apos F5/delete).
    """
    deadline = time.monotonic() + max(1, timeout_seconds)
    while time.monotonic() < deadline:
        check_continue(should_continue)
        for _row, row_name, _status in iter_page_file_rows(page):
            if row_name:
                # iter_page_file_rows ja filtra LOADING_ROW_TEXTS; qualquer nome que chegue
                # aqui e um nome de arquivo real.
                return True
        time.sleep(0.8)
    return False


def _count_real_file_rows(page) -> int:
    """Conta quantas linhas reais (nao de carregamento) a tabela tem na pagina atual.

    Usado por wait_for_files_table_stable para detectar estabilizacao do rendering
    incremental apos F5 ou delecao. Retorna 0 enquanto a tabela ainda esta carregando
    ou completamente vazia.
    """
    count = 0
    for _row, row_name, _status in iter_page_file_rows(page):
        if row_name:
            count += 1
    return count


def wait_for_files_table_stable(
    page,
    should_continue: Callable[[], bool] | None = None,
    timeout_seconds: int = 15,
    poll_interval: float = 0.35,
    stable_polls: int = 3,
) -> bool:
    """Aguarda ate que a contagem de linhas reais da tabela ESTABILIZE por N polls consecutivos.

    O Cloudscape renderiza linhas de forma INCREMENTAL apos um F5 ou uma delecao: a condicao
    '>= 1 linha real' (wait_for_files_table_ready) e satisfeita assim que a PRIMEIRA linha
    aparece, mas linhas posteriores (ex.: PRESENT SIMPLES HOMEWORK.docx) ainda nao existem
    no DOM. Isso causava leituras parciais da tabela com arquivos 'ausentes' na realidade.

    Esta funcao aguarda ate que o numero de linhas reais nao mude por `stable_polls`
    verificacoes consecutivas (a cada ~poll_interval segundos) OU ate o timeout estourar.
    Linhas de placeholder (LOADING_ROW_TEXTS) NAO contam.

    Retorna True se a tabela estabilizou (ou ficou vazia de forma estavel — workspace
    realmente vazio); False se o timeout expirou sem estabilizacao (o chamador segue
    assim mesmo para nao bloquear indefinidamente).

    Nao aumenta nenhum timeout de negocio; e apenas a espera de assentamento da UI.
    """
    deadline = time.monotonic() + max(1, timeout_seconds)
    last_count = -1
    consecutive = 0
    while time.monotonic() < deadline:
        check_continue(should_continue)
        current_count = _count_real_file_rows(page)
        if current_count == last_count:
            consecutive += 1
            if consecutive >= stable_polls:
                # Contagem estavel por N polls: tabela assentou.
                return True
        else:
            consecutive = 0
            last_count = current_count
        time.sleep(poll_interval)
    # Timeout: retorna True se ha ao menos UMA linha (workspace nao vazio) para nao
    # bloquear execucoes em workspaces grandes que demoram mais que o timeout.
    # Retorna False somente se nunca vimos nenhuma linha (workspace vazio ou falha).
    return last_count > 0


def wait_monitor_delay(
    timeout_minutes: int,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
    task_created_at: Optional[str] = None,
) -> None:
    """Espera o tempo determinado pela automacao SEM abrir o navegador (sem polling continuo).

    O monitoramento e feito uma unica vez, depois desse tempo. Desconta o tempo decorrido na fila.
    """
    from datetime import datetime, timezone
    import math

    total_seconds = max(0, int(timeout_minutes) * 60)
    elapsed_seconds = 0
    if task_created_at:
        try:
            created_str = str(task_created_at)
            if created_str.endswith("Z"):
                created_str = created_str[:-1] + "+00:00"
            created_dt = datetime.fromisoformat(created_str)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            
            now_utc = datetime.now(timezone.utc)
            elapsed_seconds = max(0, int((now_utc - created_dt).total_seconds()))
        except Exception as exc:
            log("warning", f"Nao foi possivel calcular o tempo decorrido na fila: {exc}")

    seconds = max(0, total_seconds - elapsed_seconds)
    if seconds <= 0:
        if elapsed_seconds > 0:
            log("info", f"Tempo de espera decorrido na fila ({elapsed_seconds // 60} min passados). Seguindo para leitura de status.")
        return

    minutes_left = int(math.ceil(seconds / 60))
    log("info", f"Aguardando {minutes_left} min antes do monitoramento unico (sem navegador aberto).")
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        check_continue(should_continue)
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    log("info", "Tempo de espera concluido; abrindo o Chromium para o monitoramento.")


def open_workspace_for_monitor(page, payload: dict[str, Any], workspace_name: str, log: Callable) -> None:
    """Abre o workspace direto pela Playground URL salva; cai para busca por nome se faltar."""
    direct_url = str(payload.get("workspace_playground_url") or "").strip()
    if direct_url:
        page.goto(direct_url, wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
        ensure_logged_in(page, payload, log)
        if wait_for_workspace_area(page, "files", timeout_ms=settings.WORKSPACE_AREA_TIMEOUT_MS):
            log("info", "Workspace aberto direto pela Playground URL (monitoramento).", metadata={"workspace_playground_url": direct_url})
            return
        log("warning", "Playground URL direta nao carregou a area de arquivos; caindo para busca por nome.")
    else:
        page.goto(configured_playground_url(payload), wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
        ensure_logged_in(page, payload, log)
    open_workspace(page, workspace_name, log, expected_area="files")


def page_rows_signature(page) -> str:
    parts: list[str] = []
    try:
        rows = page.locator("table tbody tr")
        count = min(rows.count(), 60)
        for index in range(count):
            try:
                parts.append(clean_text(rows.nth(index).inner_text(timeout=500)))
            except Exception:
                continue
    except Exception:
        pass
    if not parts:
        return clean_text(page_text(page))[:2000]
    return "||".join(parts)


def goto_next_files_page(page) -> bool:
    """Clica na "proxima pagina". Retorna True se a tabela mudou (havia outra pagina).

    O Playground usa AWS Cloudscape: a seta "proxima" e um <button class="awsui_arrow...">
    com **aria-label VAZIO** e icone "angle-right" (confirmado no DOM ao vivo) — por isso o
    casamento por texto/aria NAO a encontra. Miramos primeiro pelo icone/classe Cloudscape:
      - ':has([class*="awsui_name-angle-right"])' garante que e a seta "proxima" (nao a "anterior");
      - ':not([disabled])' evita clicar quando ja e a ultima pagina (a seta fica desabilitada).
    O casamento por NEXT_PAGE_TEXTS (">", "Next"...) fica como fallback para outras UIs.
    """
    signature_before = page_rows_signature(page)
    # try/except: no padrao "openEnd" do Cloudscape a seta ">" fica SEMPRE habilitada (mesmo sem
    # proxima pagina) e o clique pode estourar timeout/instabilidade enquanto a tabela re-renderiza.
    # Tratamos qualquer falha de clique como "sem proxima pagina" (False) — nunca deixar crashar o
    # monitor. A guarda de assinatura abaixo confirma se a pagina realmente mudou.
    try:
        clicked = click_first(
            [
                lambda: page.locator('button[class*="awsui_arrow"]:not([disabled]):has([class*="awsui_name-angle-right"])'),
                lambda: page.locator('[class*="awsui_pagination"] button:not([disabled]):has([class*="awsui_name-angle-right"])'),
            ]
            + [lambda text=text: page.get_by_role("button", name=text, exact=True) for text in NEXT_PAGE_TEXTS]
            + [lambda text=text: page.get_by_role("link", name=text, exact=True) for text in NEXT_PAGE_TEXTS]
            + [lambda text=text: page.locator(f"[aria-label*='{text}' i]") for text in NEXT_PAGE_TEXTS]
            + [lambda text=text: page.locator(f"[title*='{text}' i]") for text in NEXT_PAGE_TEXTS],
            timeout_ms=1500,
        )
    except Exception:
        return False
    if not clicked:
        return False
    for _ in range(12):
        time.sleep(0.3)
        if page_rows_signature(page) != signature_before:
            return True
    return False


def best_status(current: dict[str, str], candidate: dict[str, str]) -> dict[str, str]:
    order = {"Ready": 4, "Error": 3, "Processing": 2, "Pending": 1}
    cur = current.get("status")
    cand = candidate.get("status")
    if cand == "Ready":
        return candidate
    if cur not in FOUND_STATUSES and cand in FOUND_STATUSES:
        return candidate
    if order.get(cand, 0) > order.get(cur, 0):
        return candidate
    return current


def _scroll_files_step(page) -> int:
    """Rola um passo (uma altura visivel) o maior container rolavel da area de arquivos.

    Retorna o novo scrollTop, ou -1 se nao houver nada rolavel (tabela paginada/curta).
    Necessario para tabelas virtualizadas que so renderizam as linhas visiveis.
    """
    try:
        return page.evaluate(
            """
            () => {
              const scrollers = [];
              document.querySelectorAll('table, [role="grid"], [role="table"]').forEach((t) => {
                let el = t.parentElement;
                while (el) {
                  const s = getComputedStyle(el);
                  if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 4) {
                    scrollers.push(el);
                  }
                  el = el.parentElement;
                }
              });
              const se = document.scrollingElement || document.documentElement;
              if (se && se.scrollHeight > se.clientHeight + 4) scrollers.push(se);
              if (!scrollers.length) return -1;
              scrollers.sort((a, b) => b.scrollHeight - a.scrollHeight);
              const el = scrollers[0];
              el.scrollTop = Math.min(el.scrollTop + Math.max(1, el.clientHeight - 40), el.scrollHeight);
              return Math.round(el.scrollTop);
            }
            """
        )
    except Exception:
        return -1


def read_visible_statuses_scrolling(
    page,
    expected_names: list[str],
    should_continue: Callable[[], bool] | None = None,
    max_steps: int = 40,
) -> dict[str, dict[str, str]]:
    """Le os status rolando a tabela do topo ao fim, mesclando a cada passo.

    Em tabelas VIRTUALIZADAS as linhas fora da tela nao existem no DOM; ler so o que esta
    visivel perde linhas. Aqui lemos a cada rolagem, ANTES de a linha ser desmontada, e
    mantemos o melhor status por arquivo. Em tabelas comuns (sem rolagem) faz uma leitura.
    """
    merged: dict[str, dict[str, str]] = {
        name: {"status": "NotFound", "raw": "", "status_text": ""} for name in expected_names
    }
    last_pos = -2
    stable = 0
    for _ in range(max_steps):
        check_continue(should_continue)
        statuses = read_file_statuses(page, expected_names)
        for name, data in statuses.items():
            if data.get("status") in FOUND_STATUSES:
                merged[name] = best_status(merged[name], data)
        if all(merged[name]["status"] == "Ready" for name in expected_names):
            break
        pos = _scroll_files_step(page)
        if pos < 0:
            break  # nada rolavel: ja lemos tudo que ha
        if pos == last_pos:
            stable += 1
            if stable >= 2:
                break  # chegou ao fim (scrollTop nao avança mais)
        else:
            stable = 0
        last_pos = pos
        time.sleep(0.3)
    return merged


def find_files_search_field(page):
    """Localiza um campo de busca/filtro na aba Files. Retorna o locator ou None (no-op)."""
    for text in FILES_SEARCH_FIELDS:
        for lookup in (
            lambda t=text: page.get_by_placeholder(t, exact=False),
            lambda t=text: page.get_by_role("searchbox", name=t),
            lambda t=text: page.get_by_role("textbox", name=t),
        ):
            try:
                loc = lookup()
                if loc.count() and loc.first.is_visible(timeout=400):
                    return loc.first
            except Exception:
                continue
    try:
        loc = page.locator('input[type="search"]')
        if loc.count() and loc.first.is_visible(timeout=400):
            return loc.first
    except Exception:
        pass
    return None


def resolve_not_found_by_search(
    page,
    names: list[str],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> dict[str, dict[str, str]]:
    """Recupera o status dos arquivos NotFound via campo de busca da aba Files.

    Busca pelo STEM (sem extensao) para tolerar conversao p/ PDF; le a linha filtrada.
    Se nao houver campo de busca, retorna {} (cai no fallback de releitura por F5).
    """
    field = find_files_search_field(page)
    if field is None:
        return {}
    resolved: dict[str, dict[str, str]] = {}
    for name in names:
        check_continue(should_continue)
        query = (Path(name).stem or name)[:60]
        try:
            field.fill("")
            field.fill(query)
            time.sleep(0.7)
            statuses = read_visible_statuses_scrolling(page, [name], should_continue=should_continue, max_steps=8)
            data = statuses.get(name)
            if data and data.get("status") in FOUND_STATUSES:
                resolved[name] = data
                log("info", f"Status recuperado via busca na aba Files: {name} = {data.get('status')}", metadata={"query": query})
        except Exception as exc:
            log("warning", f"Busca de arquivo falhou para '{name}': {exc}", metadata={"query": query})
    try:
        field.fill("")  # limpa o filtro para nao afetar leituras seguintes
        time.sleep(0.4)
    except Exception:
        pass
    return resolved


def read_all_pages_statuses(
    page,
    expected_names: list[str],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> dict[str, dict[str, str]]:
    """Le o status de cada arquivo percorrendo TODAS as paginas (clicando em ">").

    Em cada pagina, faz uma leitura COM ROLAGEM (read_visible_statuses_scrolling) para
    cobrir tabelas virtualizadas/lazy antes de avancar com ">".
    """
    merged: dict[str, dict[str, str]] = {
        name: {"status": "NotFound", "raw": "", "status_text": ""} for name in expected_names
    }
    page_index = 0
    max_pages = 200
    while page_index < max_pages:
        check_continue(should_continue)
        page_index += 1
        # Aguarda a tabela ESTABILIZAR antes de ler/rolar: o rendering incremental do
        # Cloudscape pode ter linhas ainda por aparecer quando chegamos aqui (especialmente
        # apos o F5 da validacao final). Sem essa espera, um arquivo Ready pode ser lido
        # como NotFound simplesmente por nao ter renderizado ainda.
        wait_for_files_table_stable(page, should_continue=should_continue, timeout_seconds=12)
        wait_for_expected_rows(page, expected_names, timeout_seconds=8, should_continue=should_continue)
        statuses = read_visible_statuses_scrolling(page, expected_names, should_continue=should_continue)
        found_here: list[str] = []
        for name, data in statuses.items():
            if data.get("status") in FOUND_STATUSES:
                merged[name] = best_status(merged[name], data)
                found_here.append(name)
        log("info", f"Pagina {page_index} de Status lida.", metadata={"found": found_here})
        if all(merged[name]["status"] == "Ready" for name in expected_names):
            break
        if not goto_next_files_page(page):
            break
    return merged


# --- Leitura POSICIONAL da linha (para a guarda de status no momento da delecao) ---------------
# Diferente de read_structured_file_rows (que filtra celulas vazias e agrega varias tabelas), aqui
# lemos as celulas DIRETAS da linha SEM filtrar vazios, preservando o alinhamento por indice com os
# cabecalhos. Isso evita o desalinhamento que fazia o status de uma coluna ser lido de outra.
_ROW_CELLS_JS = """
(rowEl) => {
  const clean = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
  const textOf = (el) => {
    if (!el) return '';
    const parts = [el.innerText || el.textContent || ''];
    if (el.getAttribute) { parts.push(el.getAttribute('aria-label') || ''); parts.push(el.getAttribute('title') || ''); }
    if (el.querySelectorAll) {
      el.querySelectorAll('[aria-label], [title]').forEach((c) => {
        parts.push(c.getAttribute('aria-label') || '');
        parts.push(c.getAttribute('title') || '');
      });
    }
    return clean(parts.filter(Boolean).join(' '));
  };
  const table = rowEl.closest('table');
  let headers = [];
  if (table) {
    headers = Array.from(table.querySelectorAll('thead th, thead [role="columnheader"]')).map(textOf);
  }
  const cells = Array.from(rowEl.querySelectorAll(
    ':scope > td, :scope > th, :scope > [role="cell"], :scope > [role="gridcell"]'
  )).map(textOf);
  return { headers, cells, text: textOf(rowEl) };
}
"""


def _read_row_cells(row) -> tuple[list[str], list[str], str]:
    try:
        data = row.evaluate(_ROW_CELLS_JS)
    except Exception:
        return [], [], ""
    headers = [str(h) for h in (data.get("headers") or [])]
    cells = [str(c) for c in (data.get("cells") or [])]
    return headers, cells, str(data.get("text") or "")


def _name_from_aligned(headers: list[str], cells: list[str]) -> str:
    """Nome do arquivo na linha: pela coluna Name (alinhada por indice) ou a 1a celula util."""
    name_index = header_index(headers, NAME_HEADERS)
    if name_index is not None and name_index < len(cells) and clean_text(cells[name_index]):
        return clean_text(cells[name_index])
    for cell in cells:
        if clean_text(cell):
            return clean_text(cell)
    return ""


def _status_from_aligned(headers: list[str], cells: list[str], name_text: str, row_text: str) -> str:
    """Status normalizado da linha, alinhado pela coluna Status (sem filtrar celulas vazias)."""
    status_index = header_index(headers, STATUS_HEADERS)
    if status_index is not None and status_index < len(cells):
        normalized = normalize_status(cells[status_index])
        if normalized != "Unknown":
            return normalized
    name_index = header_index(headers, NAME_HEADERS)
    for index, cell in enumerate(cells):
        if name_index is not None and index == name_index:
            continue
        if name_text and name_text.lower() in cell.lower():
            continue
        normalized = normalize_status(cell)
        if normalized != "Unknown":
            return normalized
    return normalize_status(row_text)


def _row_identity_matches(row_name: str, target_name: str) -> bool:
    """Casa a linha ao alvo por IDENTIDADE (igualdade), nunca por 'contem'.

    Igualdade evita a colisao de substring que deletava a primeira linha por engano
    (ex.: alvo 'data.csv' casava a linha 'metadata.csv'). Cobre conversao para PDF
    comparando o STEM (nome sem extensao) por igualdade (.docx == .pdf -> mesmo stem).
    """
    rn, tn = _norm(row_name), _norm(target_name)
    if not rn or not tn:
        return False
    if rn == tn:
        return True
    rs, ts = _norm(Path(row_name).stem), _norm(Path(target_name).stem)
    return bool(rs and ts and rs == ts)


def _row_matches_target(row_name: str, row_text: str, target_name: str, *, allow_truncation: bool = True) -> bool:
    if _row_identity_matches(row_name, target_name):
        return True
    if not allow_truncation:
        return False
    # Nome exibido truncado pela UI (reticencias): tolera, mas exige fragmento significativo.
    return _truncation_match(_norm(target_name), _norm(Path(target_name).stem), _norm(row_name or row_text))


def _match_row_to_expected(row_name: str, remaining: set[str]) -> "str | None":
    """Associa o nome lido na linha a um arquivo esperado, SOMENTE por identidade.

    Usado exclusivamente no caminho de delete (leitura linha a linha): nunca usa truncamento
    nem substring para evitar que 'data.csv' case 'metadata.csv' ou que nomes com prefixo
    compartilhado se colidam. Retorna o nome esperado correspondente, ou None se a linha nao
    corresponder a nenhum arquivo esperado ainda nao processado.
    """
    if not row_name:
        return None
    for target in remaining:
        if _row_identity_matches(row_name, target):
            return target
    return None


def _is_loading_row(name: str) -> bool:
    """Retorna True se o nome da linha e um placeholder de carregamento (nao um arquivo real).

    Comparacao case-insensitive e sem espacos extras. Garante que pseudo-linhas como
    "Loading Files" nunca sejam tratadas como nome de arquivo nem como ausencia de arquivo.
    """
    return _norm(name) in LOADING_ROW_TEXTS


def iter_page_file_rows(page):
    """Itera as linhas da tabela de arquivos da pagina ATUAL, lendo (locator, nome, status).

    Le linha a linha pelo proprio elemento (sem decidir por posicao): cada (nome, status) vem da
    MESMA linha que sera deletada. O locator posicional .nth(i) so e usado imediatamente apos esta
    leitura (a tabela e relida apos cada delecao via F5), entao o indice e estavel para a acao.

    Linhas cujo nome case LOADING_ROW_TEXTS sao IGNORADAS (a tabela ainda esta carregando).
    """
    rows = page.locator("table tbody tr")
    try:
        count = min(rows.count(), 300)
    except Exception:
        count = 0
    for index in range(count):
        row = rows.nth(index)
        headers, cells, text = _read_row_cells(row)
        name = _name_from_aligned(headers, cells) or clean_text(text)
        if _is_loading_row(name):
            # Linha de placeholder de carregamento: a tabela ainda nao populou. Ignorar.
            continue
        status = _status_from_aligned(headers, cells, name, text)
        yield row, name, status


def find_target_rows_on_page(page, target: str) -> list[tuple[Any, str, str]]:
    """Retorna TODAS as linhas da pagina atual que casam o alvo SOMENTE por identidade (sem truncamento).

    O caminho de delete exige identidade exata: nunca toleramos truncamento para nao deletar
    a linha errada. allow_truncation=False garante isso.
    """
    matches: list[tuple[Any, str, str]] = []
    for row, name, status in iter_page_file_rows(page):
        if _row_matches_target(name, "", target, allow_truncation=False):
            matches.append((row, name, status))
    return matches


def click_delete_confirm(page) -> bool:
    """Confirma a delecao SOMENTE dentro de um modal/dialog real.

    SEGURANCA CRITICA: NUNCA clicar 'Delete'/'Excluir'/'Remove' no escopo da PAGINA inteira.
    DELETE_CONFIRM_TEXTS contem "Delete"/"Excluir"/"Remove"/"Remover" — os MESMOS textos que
    aparecem no aria-label do botao de deletar de CADA LINHA ('Delete "<arquivo>"'). Se
    cairmos no escopo da pagina, page.get_by_role("button", name="Delete") casa TODOS os
    botoes de linha e o .first deleta um arquivo INOCENTE (foi esse o bug que deletou
    CONTRATO/PRESENT SIMPLES quando o alvo era DiagramaDeClasses).

    Por isso atuamos APENAS dentro de role=dialog/alertdialog visivel. Se o Playground
    deletar sem modal (delecao imediata), nao ha nada a confirmar: retornamos False e a
    delecao ja realizada sera verificada por F5 pelo chamador. Esperamos ate ~2.5s pelo
    surgimento do modal (ele pode renderizar logo apos o clique no controle da linha).
    """
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline:
        for role in ("dialog", "alertdialog"):
            try:
                dialog = page.get_by_role(role)
                if not dialog.count():
                    continue
                scope = dialog.first
                if not scope.is_visible(timeout=300):
                    continue
                if click_first(
                    [lambda text=text: scope.get_by_role("button", name=text) for text in DELETE_CONFIRM_TEXTS]
                    + [lambda text=text: scope.get_by_text(text, exact=True) for text in DELETE_CONFIRM_TEXTS],
                    timeout_ms=1200,
                ):
                    return True
            except Exception:
                continue
        time.sleep(0.3)
    return False


def actions_cell(row):
    """Ultima celula da linha (coluna Actions), onde fica o icone de deletar."""
    for cell_selector in ("td:last-child", "[role='gridcell']:last-child", "[role='cell']:last-child"):
        try:
            cell = row.locator(cell_selector).last
            if cell.count():
                return cell
        except Exception:
            continue
    return None


def dump_actions_cell_html(row, log: Callable, file_name: str) -> None:
    """Loga o HTML da celula Actions para mapearmos o seletor exato do icone de delete.

    Acionado quando nao achamos/confirmamos o controle: o aria-label/title/classe reais do
    icone ficam no log para deixarmos o clique cirurgico na proxima execucao.
    """
    target = actions_cell(row) or row
    try:
        html = target.evaluate("el => el.outerHTML")
    except Exception:
        return
    if html:
        log(
            "warning",
            f"HTML da area Actions de '{file_name}' (para mapear o icone de delete): {clean_text(html)[:1500]}",
            metadata={"actions_html": html},
        )


def click_row_delete_control(page, file_name: str, log: Callable) -> bool:
    """Clica no controle de deletar identificado EXCLUSIVAMENTE pelo nome exato do arquivo.

    SEGURANCA CRITICA: esta funcao NAO aceita mais um locator de linha ('row') pois locators
    posicionais .nth(i) sao lazy/live e re-resolvem para uma linha diferente se o DOM mudar
    entre a leitura e o clique (rendering incremental apos F5 = bug historico que deletou
    PRESENT SIMPLES HOMEWORK.docx quando o alvo era DiagramaDeClasses.docx).

    Agora o controle e localizado diretamente no ESCOPO DA PAGINA pelo aria-label/title exato
    'Delete "<file_name>"'. O Cloudscape garante que esse aria-label e unico por arquivo. Se
    mais de um controle casar (ambiguo) ou nenhum casar, retorna False sem clicar nada.

    JAMAIS usa fallback por posicao de linha (actions_cell / first button em celula desconhecida).
    Qualquer ambiguidade ou ausencia e tratada como falha segura pelo chamador.
    """
    # Construcao dos padroes exatos para o aria-label/title do botao de delete do Cloudscape.
    # Formato confirmado no DOM ao vivo: aria-label='Delete "<NOME_EXATO_DO_ARQUIVO>"'
    # Usamos re.escape para nao interpretar caracteres especiais do nome do arquivo como regex.
    exact_label_pattern = re.compile(
        r'^Delete\s+"?' + re.escape(file_name) + r'"?$',
        re.IGNORECASE,
    )

    # --- Passo 1: localizacao por aria-label exato no escopo da PAGINA (nao de linha). -------
    # Isso e position-independent: o botao e identificado pelo nome do ARQUIVO que ele deleta,
    # nao pela posicao da linha. Se a tabela re-renderizou, o aria-label ainda aponta o mesmo.
    for lookup in (
        # a) get_by_role com nome exato: mais semantico, mais robusto.
        lambda: page.get_by_role("button", name=exact_label_pattern),
        # b) CSS por aria-label exato (caso o role nao seja 'button' no deployment).
        lambda: page.locator(f"[aria-label='Delete \"{file_name}\"']"),
        lambda: page.locator(f"[title='Delete \"{file_name}\"']"),
        # c) CSS por aria-label com aspas simples (variacao de delimitador no DOM).
        lambda: page.locator(f"[aria-label=\"Delete '{file_name}'\"]"),
        lambda: page.locator(f"[title=\"Delete '{file_name}'\"]"),
        # d) CSS por aria-label contendo o nome exato precedido de 'Delete ' (case-insensitive).
        lambda: page.locator(f"button[aria-label*='{file_name}'][aria-label*='Delete' i]"),
        lambda: page.locator(f"button[title*='{file_name}'][title*='Delete' i]"),
    ):
        try:
            control = lookup()
            count = control.count()
            if count == 0:
                continue
            if count > 1:
                # Mais de um controle com o mesmo nome de arquivo: ambiguidade -> falha segura.
                log(
                    "warning",
                    f"Controle de deletar ambiguo: {count} elementos encontrados para '{file_name}'; nao clicar.",
                )
                return False
            if control.first.is_visible(timeout=400):
                control.first.click(timeout=4000)
                log("info", f"Controle de deletar clicado (ancora por nome de arquivo): '{file_name}'.")
                return True
        except Exception:
            continue

    # --- Passo 2: fallback por textos conhecidos de delete, MAS so se o aria-label/title
    #              do controle contiver o NOME EXATO do arquivo alvo. Nunca clicamos um
    #              controle cujo rotulo nao mencione o arquivo que queremos deletar. --------
    for text in DELETE_FILE_CONTROL_TEXTS:
        for lookup in (
            lambda t=text: page.get_by_role("button", name=t),
            lambda t=text: page.locator(f"button[aria-label*='{t}' i]"),
            lambda t=text: page.locator(f"button[title*='{t}' i]"),
        ):
            try:
                control = lookup()
                count = control.count()
                for idx in range(min(count, 20)):
                    candidate = control.nth(idx)
                    try:
                        if not candidate.is_visible(timeout=300):
                            continue
                        # Verificacao de identidade: o aria-label ou title do candidato
                        # DEVE conter o nome exato do arquivo alvo. Sem isso, nao clicamos.
                        aria = candidate.get_attribute("aria-label") or ""
                        title = candidate.get_attribute("title") or ""
                        combined = (aria + " " + title).lower()
                        if file_name.lower() not in combined:
                            continue
                        candidate.click(timeout=4000)
                        log("info", f"Controle de deletar clicado (fallback texto+nome): '{file_name}'.")
                        return True
                    except Exception:
                        continue
            except Exception:
                continue

    log("warning", f"Controle de deletar nao encontrado para '{file_name}' (nenhum elemento com aria-label/title contendo o nome do arquivo).")
    return False


def f5_reopen_files(page, payload: dict[str, Any], workspace_name: str, log: Callable, should_continue: Callable[[], bool] | None = None) -> None:
    """Recarrega com F5 e reabre a aba Files (a delecao pode demorar para refletir).

    Apos reabrir a aba, aguarda que a tabela de arquivos esteja populada com ao menos
    uma linha real (wait_for_files_table_ready) antes de retornar. Isso evita que
    qualquer chamador (especialmente delete_one_with_verify) leia a tabela antes de ela
    terminar de carregar e declare um arquivo existente como "absent" por corrida de tempo.
    """
    check_continue(should_continue)
    try:
        page.reload(wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
    except Exception as exc:
        log("warning", f"Falha no F5 da aba Files: {exc}")
    ensure_logged_in(page, payload, log)
    try:
        if not wait_for_workspace_area(page, "files", timeout_ms=8000):
            open_workspace_for_monitor(page, payload, workspace_name, log)
    except Exception:
        open_workspace_for_monitor(page, payload, workspace_name, log)
    try:
        open_files_tab(page, log)
    except Exception as exc:
        log("warning", f"Nao foi possivel reabrir a aba Files apos o F5: {exc}")
    # Aguarda a tabela ESTABILIZAR antes de retornar ao chamador.
    # O Cloudscape renderiza linhas de forma incremental apos F5/delete; esperar apenas
    # '>=1 linha' (wait_for_files_table_ready) deixava leituras parciais onde arquivos
    # como PRESENT SIMPLES HOMEWORK.docx nao haviam renderizado ainda. A espera por
    # estabilizacao da contagem de linhas elimina essa race condition.
    stable = wait_for_files_table_stable(page, should_continue=should_continue, timeout_seconds=15)
    if not stable:
        log("warning", "Tabela de arquivos nao estabilizou dentro do prazo apos F5 (workspace possivelmente vazio ou muito lento).")


def locate_target_paginated(
    page, target: str, should_continue: Callable[[], bool] | None = None
) -> tuple[str, Optional[tuple[Any, str, str]]]:
    """Percorre as paginas e localiza a linha do alvo por IDENTIDADE (nunca por posicao).

    Retorna (outcome, found):
      - ("found", (row, name, status)) — exatamente UMA linha casou o identificador.
      - ("ambiguous", None) — mais de uma linha casou: NAO deletamos por posicao (revisao manual).
      - ("absent", None) — nenhuma linha em nenhuma pagina casou (arquivo nao esta na tabela).
    """
    visited = 0
    max_pages = 200
    while visited < max_pages:
        visited += 1
        check_continue(should_continue)
        matches = find_target_rows_on_page(page, target)
        if len(matches) == 1:
            return "found", matches[0]
        if len(matches) > 1:
            return "ambiguous", None
        if not goto_next_files_page(page):
            return "absent", None
    return "absent", None


# Resultados possiveis de uma tentativa de delecao guardada por status.
DELETE_DELETED = "deleted"            # linha Error/Processing removida e confirmada por F5
DELETE_WOULD_DELETE = "would_delete"  # dry-run: deletaria, mas nao clicou
DELETE_SKIPPED_READY = "skipped_ready"  # GUARDA: a linha estava Ready -> nunca deletar
DELETE_SKIPPED_STATUS = "skipped_status"  # status nao e Error/Processing (Unknown/Pending) -> manual
DELETE_ABSENT = "absent"              # arquivo nao esta na tabela
DELETE_AMBIGUOUS = "ambiguous"        # identificador casou >1 linha -> manual (nao deletar por posicao)
DELETE_FAILED = "failed"             # tentou deletar mas a linha nao sumiu / controle nao encontrado


def delete_one_with_verify(
    page,
    target: str,
    payload: dict[str, Any],
    workspace_name: str,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
    attempts: int = 2,
    dry_run: bool = False,
) -> str:
    """Deleta UMA linha, mas SOMENTE se o status lido NA PROPRIA linha for Error/Processing.

    Fluxo exigido: ler a linha pelo identificador -> Ready: pula (GUARDA, jamais deleta) ->
    Error/Processing: deleta -> F5 + reler para confirmar que a linha sumiu. A decisao nunca usa
    posicao de linha; o status vem da MESMA linha que sera clicada. Retorna um dos DELETE_*.

    SEGURANCA: click_row_delete_control agora recebe 'page' (nao 'row') e ancora o clique
    diretamente pelo aria-label/title exato do botao de delete, que contem o nome do arquivo.
    Nenhum fallback posicional e permitido: ambiguidade ou ausencia resultam em DELETE_FAILED.
    """
    # F5 antes da primeira busca: a leitura de status percorre TODAS as paginas e deixa o cursor
    # na ultima; como locate_target_paginated so avanca, sem este reset um alvo numa pagina anterior
    # nao seria encontrado e viraria "absent" por engano.
    f5_reopen_files(page, payload, workspace_name, log, should_continue)
    for attempt in range(1, attempts + 1):
        check_continue(should_continue)
        # Aguarda a tabela ESTABILIZAR antes de localizar o alvo (rendering incremental apos F5).
        # Esta espera reduz a janela de risco onde iter_page_file_rows le linhas parciais e
        # locate_target_paginated capturas um locator posicional que poderia estar desatualizado.
        wait_for_files_table_stable(page, should_continue=should_continue, timeout_seconds=15)
        outcome, found = locate_target_paginated(page, target, should_continue)
        if outcome == "absent":
            log("info", f"'{target}' nao esta na tabela (nada para deletar).")
            return DELETE_ABSENT
        if outcome == "ambiguous":
            log("warning", f"'{target}': mais de uma linha casou o identificador; nao deletar -> revisao manual.")
            return DELETE_AMBIGUOUS
        _row, name, status = found  # type: ignore[misc]
        # GUARDA central: nunca deletar uma linha Ready, aconteca o que acontecer.
        if status == "Ready":
            log("info", f"GUARDA: '{target}' esta Ready na tabela (linha '{name}'); delete ABORTADO (nunca deletar Ready).")
            return DELETE_SKIPPED_READY
        if status not in ("Error", "Processing"):
            log("warning", f"'{target}' status='{status}' (nao Error/Processing) na linha '{name}'; nao deletar -> revisao manual.")
            return DELETE_SKIPPED_STATUS
        if dry_run:
            log("info", f"[DRY-RUN] Deletaria '{target}' (linha '{name}', status={status}); clique NAO efetuado.")
            return DELETE_WOULD_DELETE
        # Clique ancorado ao NOME DO ARQUIVO (via aria-label/title exato), nao a posicao de linha.
        # Aguarda a tabela estabilizar imediatamente antes do clique para maximizar a chance de
        # que o botao identificado por aria-label="Delete \"<target>\"" esteja estavel no DOM.
        wait_for_files_table_stable(page, should_continue=should_continue, timeout_seconds=10)
        if not click_row_delete_control(page, target, log):
            log("warning", f"Controle de deletar nao encontrado ou ambiguo para '{target}'; DELETE_FAILED.")
            return DELETE_FAILED
        click_delete_confirm(page)  # melhor esforco: algumas UIs deletam sem modal de confirmacao
        f5_reopen_files(page, payload, workspace_name, log, should_continue)
        recheck, _ = locate_target_paginated(page, target, should_continue)
        if recheck == "absent":
            log("info", f"Delete confirmado (linha sumiu) para: {target} (status era {status}).")
            return DELETE_DELETED
        log("warning", f"'{target}' continua na tabela apos o delete (tentativa {attempt}/{attempts}).")
    # Falhou apos as tentativas: registra o HTML da area de acoes via dump no scope de pagina.
    log("warning", f"Delete de '{target}' nao confirmado apos {attempts} tentativa(s): DELETE_FAILED.")
    return DELETE_FAILED


def _stream_read_and_delete(
    page,
    expected_names: list[str],
    payload: dict[str, Any],
    workspace_name: str,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
    dry_run: bool = False,
) -> tuple[dict[str, dict[str, str]], dict[str, list[str]], set[str]]:
    """Leitura e delecao VERDADEIRAMENTE linha a linha (row-by-row), em ciclos com reinicio.

    Algoritmo:
      - Ciclo externo reinicia da pagina 1 sempre que uma delecao ocorre (paginacao muda).
      - Para cada linha da pagina: check_continue() PRIMEIRO (cancelamento por linha).
      - Identidade via _match_row_to_expected (somente identidade exata, sem truncamento).
      - Se linha nao corresponde a nenhum arquivo esperado: ignora e continua.
      - Ready   -> marca como Ready, adiciona a ready_confirmed, descarta do remaining, loga.
      - Pending -> revisao manual, descarta do remaining, loga warning.
      - Error/Processing -> deleta IMEDIATAMENTE com delete_one_with_verify (guarda F5
        integrada — Ready nunca deletado). Em dry-run, loga 'would delete' sem clicar.
        Apos delete (ou dry-run), reinicia o ciclo desde a pagina 1.
      - Outro status (Unknown) -> skipped_status, revisao manual, descarta do remaining.

    Retorna (statuses, outcomes, ready_confirmed):
      statuses:       dict[name -> {"status", "raw", "status_text"}]
      outcomes:       dict DELETE_* -> [nomes]
      ready_confirmed: set[str] -- arquivos confirmados Ready nesta passagem (para detectar
                      lost_ready na validacao final: um Ready que sumiu e enviado novamente).
    """
    # Inicializa status de todos como NotFound (sera preenchido conforme lemos)
    statuses: dict[str, dict[str, str]] = {
        name: {"status": "NotFound", "raw": "", "status_text": ""}
        for name in expected_names
    }
    outcomes: dict[str, list[str]] = {
        DELETE_DELETED: [], DELETE_WOULD_DELETE: [], DELETE_SKIPPED_READY: [],
        DELETE_SKIPPED_STATUS: [], DELETE_ABSENT: [], DELETE_AMBIGUOUS: [], DELETE_FAILED: [],
    }
    # Conjunto dos nomes que ainda precisam ser encontrados (ou confirmados como ausentes)
    remaining = set(expected_names)
    # Arquivos confirmados como Ready nesta passagem (para deteccao de lost_ready)
    ready_confirmed: set[str] = set()

    # O loop externo reinicia desde a pagina 1 sempre que uma delecao ocorre (a paginacao muda).
    max_restart_cycles = max(10, len(expected_names) * 3)
    restart_cycles = 0

    while remaining and restart_cycles < max_restart_cycles:
        restart_cycles += 1
        check_continue(should_continue)

        # F5 + reabrir aba Files para resetar a paginacao para pagina 1 antes de cada varredura.
        f5_reopen_files(page, payload, workspace_name, log, should_continue)

        deleted_this_cycle = False
        page_index = 0
        max_pages = 200

        while page_index < max_pages:
            page_index += 1

            # Aguarda a tabela ESTABILIZAR antes de ler as linhas desta pagina.
            # O Cloudscape renderiza linhas de forma incremental; a estabilizacao garante
            # que nao leremos a tabela com linhas ainda por renderizar (race condition).
            # Em seguida, wait_for_expected_rows faz a guarda adicional de '>=1 status real'.
            wait_for_files_table_stable(page, should_continue=should_continue, timeout_seconds=12)
            wait_for_expected_rows(page, list(remaining), timeout_seconds=8, should_continue=should_continue)

            restart_from_page1 = False

            # Itera as linhas individualmente — row-by-row TRUE.
            for _row, row_name, row_status in iter_page_file_rows(page):
                # Cancelamento por linha: verificado ANTES de qualquer outra logica.
                check_continue(should_continue)

                # Identidade exata apenas (sem truncamento): caminho de delete.
                target = _match_row_to_expected(row_name, remaining)
                if target is None:
                    log(
                        "info",
                        f"Linha ignorada (nao e arquivo esperado): '{row_name}'",
                    )
                    continue

                if row_status == "Ready":
                    # Arquivo pronto: confirma e remove do remaining.
                    statuses[target] = {"status": "Ready", "raw": row_name, "status_text": "Ready"}
                    ready_confirmed.add(target)
                    remaining.discard(target)
                    log(
                        "info",
                        f"Status linha a linha: {target} = Ready",
                        file_id=_file_id_for_name(list(payload.get("files") or []), target),
                        metadata=statuses[target],
                    )
                    continue

                if row_status == "Pending":
                    statuses[target] = {"status": "Pending", "raw": row_name, "status_text": "Pending"}
                    remaining.discard(target)
                    log(
                        "warning",
                        f"Status linha a linha: {target} = Pending (revisao manual).",
                        file_id=_file_id_for_name(list(payload.get("files") or []), target),
                    )
                    continue

                if row_status not in ("Error", "Processing"):
                    # Status desconhecido: nao deletar, enviar para revisao manual.
                    statuses[target] = {"status": row_status, "raw": row_name, "status_text": row_status}
                    log(
                        "warning",
                        f"'{target}' status='{row_status}' (nao Error/Processing); nao deletar -> revisao manual.",
                    )
                    outcomes[DELETE_SKIPPED_STATUS].append(target)
                    remaining.discard(target)
                    continue

                # Status Error ou Processing: deleta com confirmacao por F5.
                statuses[target] = {"status": row_status, "raw": row_name, "status_text": row_status}
                log(
                    "info",
                    f"Status linha a linha: {target} = {row_status}; iniciando delete.",
                    file_id=_file_id_for_name(list(payload.get("files") or []), target),
                )
                result = delete_one_with_verify(
                    page, target, payload, workspace_name, log,
                    should_continue=should_continue,
                    dry_run=dry_run,
                )
                outcomes.setdefault(result, []).append(target)
                remaining.discard(target)

                if result == DELETE_DELETED:
                    log("info", f"Delete confirmado por F5: {target}.")
                elif result == DELETE_WOULD_DELETE:
                    log("info", f"[DRY-RUN] Deletaria: {target}.")
                elif result == DELETE_SKIPPED_READY:
                    # Guarda bloqueou: a linha estava Ready no momento do clique (status mudou).
                    statuses[target] = {"status": "Ready", "raw": target, "status_text": "Ready (guarda)"}
                    ready_confirmed.add(target)
                    log("info", f"GUARDA: '{target}' estava Ready na hora do delete; mantido como Ready.")

                deleted_this_cycle = True
                restart_from_page1 = True
                break  # reinicia a varredura da pagina 1 apos cada delete

            if restart_from_page1:
                # Reinicia ciclo completo: F5 + pagina 1.
                break
            if not goto_next_files_page(page):
                break  # ultima pagina desta varredura

        if not deleted_this_cycle:
            # Nenhuma delecao neste ciclo: terminamos (nao ha mais acoes a tomar).
            break

    # Arquivos que nunca foram lidos apos todos os ciclos ficam como NotFound.
    for name in remaining:
        if statuses[name]["status"] == "NotFound":
            log(
                "warning",
                f"'{name}' nao encontrado na tabela apos {restart_cycles} varredura(s).",
                file_id=_file_id_for_name(list(payload.get("files") or []), name),
            )
        else:
            # Foi lido mas nao foi tratado (ex: reiniciamos o ciclo antes de chegar nele).
            log(
                "info",
                f"Status lido (streaming final): {name} = {statuses[name]['status']}",
                file_id=_file_id_for_name(list(payload.get("files") or []), name),
            )

    return statuses, outcomes, ready_confirmed


def monitor_workspace_files_status(
    task_id: int,
    user_id: int | None,
    payload: dict[str, Any],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    workspace_name = str(payload.get("workspace_name") or "").strip()
    if not workspace_name:
        raise PlaywrightAutomationError("Payload sem workspace_name.")
    files = payload.get("files") or []
    expected_names = [name for name in [expected_file_name(item) for item in files] if name]
    if not expected_names:
        raise PlaywrightAutomationError("Payload sem arquivos para monitorar.")

    timeout_minutes = int(payload.get("monitoring_timeout_minutes") or settings.DEFAULT_MONITORING_TIMEOUT_MINUTES)
    task_created_at = payload.get("task_created_at")
    # Dry-run: le e classifica cada linha e LOGA a decisao por arquivo, mas NAO clica em deletar
    # nem reenvia. Ligado por tarefa (payload {"monitor_dry_run": true}) ou globalmente (setting).
    dry_run = bool(payload.get("monitor_dry_run")) or bool(settings.MONITOR_DELETE_DRY_RUN)

    # 1) Espera o tempo determinado pela automacao, SEM navegador aberto (monitoramento unico).
    wait_monitor_delay(timeout_minutes, log, should_continue=should_continue, task_created_at=task_created_at)

    browser = None
    try:
        check_continue(should_continue)
        browser = open_persistent_chromium(
            user_id,
            headless=payload.get("headless"),
            browser_channel=payload.get("browser_channel"),
        )
        page = browser.page
        log("info", "Chromium iniciado (monitoramento unico apos o tempo determinado).")
        check_continue(should_continue)
        open_workspace_for_monitor(page, payload, workspace_name, log)
        check_continue(should_continue)
        open_files_tab(page, log)
        # A UI avisa que ha atraso ate o status refletir e pede para clicar em Refresh: fazemos
        # isso antes da primeira leitura (estamos na pagina 1) para ler o status mais recente.
        refresh_files_list(page, log)

        if dry_run:
            log("warning", "MODO DRY-RUN ativo: as decisoes de delecao serao apenas registradas (nenhum clique de delete, nenhum reenvio).")

        # 2) Leitura e delecao VERDADEIRAMENTE linha a linha (row-by-row).
        #    Para cada linha: check_continue() -> identidade exata -> Ready / Pending / delete.
        #    Apos cada delete, reinicia a varredura da pagina 1 (paginacao mudou).
        #    NotFound apos todos os ciclos = leitura falha -> revisao manual (nao reenvio).
        #    ready_confirmed: conjunto de arquivos vistos como Ready nesta passagem, para
        #    detectar lost_ready (Ready que sumiu na validacao final -> reenviado).
        statuses, outcomes, ready_confirmed = _stream_read_and_delete(
            page, expected_names, payload, workspace_name, log,
            should_continue=should_continue, dry_run=dry_run,
        )

        deleted = outcomes.get(DELETE_DELETED, [])
        would_delete = outcomes.get(DELETE_WOULD_DELETE, [])
        skipped_ready = outcomes.get(DELETE_SKIPPED_READY, [])
        skipped_status = outcomes.get(DELETE_SKIPPED_STATUS, [])
        absent = outcomes.get(DELETE_ABSENT, [])
        ambiguous = outcomes.get(DELETE_AMBIGUOUS, [])
        delete_failed = outcomes.get(DELETE_FAILED, [])

        # Classifica os resultados por categoria.
        ready = [
            name for name in expected_names
            if statuses.get(name, {}).get("status") == "Ready"
        ]
        # Guarda de status que bloqueou delete por Ready: arquivo ja esta Ready, nao precisa reenviar.
        if skipped_ready:
            log("info", "GUARDA de status: arquivos estavam Ready na tabela e NAO foram deletados.", metadata={"files": skipped_ready})
            ready = list(dict.fromkeys(ready + skipped_ready))
        pending = [name for name in expected_names if statuses.get(name, {}).get("status") == "Pending"]
        not_found = [name for name in expected_names if statuses.get(name, {}).get("status") == "NotFound"]
        if not_found:
            log(
                "warning",
                f"{len(not_found)} arquivo(s) permaneceram NotFound apos todas as varreduras; enviados para revisao manual (sem reenvio, para nao duplicar).",
                metadata={"files": not_found},
            )

        # 3) Validacao final: F5 + releitura completa para confirmar estado pos-delecao.
        #    (a) todos os remanescentes esperados estao Ready?
        #    (b) algum arquivo que estava Ready desapareceu?
        # Nota: nao fazemos reconfirmacao por busca para lost_ready — a regra simplificada e
        # reenviar diretamente se o arquivo Ready sumiu na varredura final (item 6 do requisito).
        f5_reopen_files(page, payload, workspace_name, log, should_continue)
        final_statuses = read_all_pages_statuses(page, expected_names, log, should_continue=should_continue)
        final_ready = [name for name in expected_names if final_statuses.get(name, {}).get("status") == "Ready"]
        leftover_non_ready = [
            name for name in expected_names
            if name not in pending and name not in not_found
            and final_statuses.get(name, {}).get("status") in ("Error", "Processing")
        ]
        # Arquivos que estavam Ready mas sumiram na varredura final -> reenviar do source.
        # Usa ready_confirmed (conjunto preciso da passagem row-by-row) para identificar quais
        # arquivos foram vistos como Ready com certeza. Se o status final for NotFound = sumiu
        # (delecao acidental). Regra simplificada: sem reconfirmacao por busca, reenviar direto.
        # NUNCA reenviar um NotFound sem ter estado Ready antes (evita duplicata).
        lost_ready = [
            name for name in ready_confirmed
            if final_statuses.get(name, {}).get("status") == "NotFound"
        ]
        if lost_ready:
            log(
                "warning",
                "Arquivo(s) Ready ausente(s) na validacao final: reenviados a partir do source local.",
                metadata={"files": lost_ready},
            )

        log(
            "info",
            f"Validacao final: {len(final_ready)} Ready; {len(lost_ready)} Ready perdido(s); "
            f"{len(leftover_non_ready)} ainda Error/Processing.",
            metadata={
                "ready": final_ready, "lost_ready": lost_ready,
                "leftover_non_ready": leftover_non_ready, "dry_run": dry_run,
            },
        )
        # Aviso explicito para os arquivos que ainda aparecem Error/Processing na validacao final
        # e nao estao no conjunto de deletados (delete nao confirmado ou delete nao tentado).
        leftover_not_deleted = [
            name for name in leftover_non_ready
            if name not in deleted
        ]
        if leftover_not_deleted:
            log(
                "warning",
                f"{len(leftover_not_deleted)} arquivo(s) ainda em Error/Processing na validacao final e nao confirmados como deletados; serao enviados para revisao manual.",
                metadata={"files": leftover_not_deleted},
            )

        if dry_run:
            # Sem efeitos colaterais: nada de reenvio nem revisao manual. So o relatorio de decisoes.
            log(
                "warning",
                "DRY-RUN concluido: nenhuma delecao/realocacao efetuada.",
                metadata={"would_delete": would_delete, "skipped_ready": skipped_ready, "skipped_status": skipped_status, "ambiguous": ambiguous, "absent": absent},
            )
            return {
                "status": "completed",
                "dry_run": True,
                "ready": ready,
                "manual_review": [],
                "to_resend": [],
                "would_delete": would_delete,
                "skipped_ready": skipped_ready,
                "skipped_status": skipped_status,
                "ambiguous": ambiguous,
                "absent": absent,
                "statuses": statuses,
                "final_statuses": final_statuses,
            }

        # So reenviamos como PDF o que foi REALMENTE removido da web (delete confirmado por F5),
        # ausente (arquivo nunca estava na tabela) ou Ready que desapareceu na varredura final.
        # Delete nao confirmado, ambiguo, status nao-acionavel e NotFound-puro NAO sao reenviados:
        # viram revisao manual para nunca duplicar o arquivo no workspace.
        to_resend = list(dict.fromkeys(deleted + absent + lost_ready))
        manual_review = list(dict.fromkeys(
            pending + delete_failed + ambiguous + skipped_status + not_found
        ))
        if delete_failed:
            log(
                "warning",
                "Delete nao confirmado: enviados para revisao manual (sem reenvio, para nao duplicar).",
                metadata={"files": delete_failed},
            )
        if ambiguous:
            log(
                "warning",
                "Identificador ambiguo (varias linhas): revisao manual (nao deletamos por posicao).",
                metadata={"files": ambiguous},
            )
        lost_any = set(lost_ready)
        return {
            "status": "completed",
            "ready": [name for name in ready if name not in lost_any],
            "manual_review": manual_review,
            "to_resend": to_resend,
            "deleted": deleted,
            "delete_failed": delete_failed,
            "ambiguous": ambiguous,
            "skipped_status": skipped_status,
            "not_found": not_found,
            "lost_ready": lost_ready,
            "statuses": statuses,
            "final_statuses": final_statuses,
        }
    except Exception:
        if browser and browser.page:
            safe_error_screenshot(browser.page, task_id, log)
        raise
    finally:
        if browser:
            browser.close()
            log("info", "Navegador fechado.")


def _file_id_for_name(files: list[Any], name: str) -> int | None:
    for item in files:
        if isinstance(item, dict) and expected_file_name(item) == name:
            value = item.get("file_id") or item.get("id")
            try:
                return int(value) if value is not None else None
            except (TypeError, ValueError):
                return None
    return None
