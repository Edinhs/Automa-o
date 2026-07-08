# 💬 Central de Comunicação e Orquestração de Agentes

Este documento serve como o canal oficial de comunicação, delegação de tarefas e sincronização de contexto entre o **Agente Líder (Antigravity)**, os **Subagentes Especialistas (Claude Code)** e qualquer outra IA ou desenvolvedor que atue neste repositório.

---

## 🧭 Protocolo de Comunicação IA-para-IA

Para garantir a continuidade perfeita do desenvolvimento e evitar conflitos de código ou retrabalho, todos os agentes devem seguir estas regras:

1.  **Leitura Obrigatória no Início:** Sempre leia este arquivo (`COMUNICACAO_AGENTES.md`) no início de cada nova sessão para entender o estado atual do projeto e as tarefas pendentes ou em andamento.
2.  **Atualização de Status:** Ao iniciar uma tarefa, marque seu status como `Em Progresso` (`[/]`) no [Quadro de Tarefas](#-quadro-de-tarefas-ativas). Ao finalizar, marque como `Concluído` (`[x]`) e inclua notas sobre os arquivos alterados e validações executadas.
3.  **Registro de Mensagens (Handoff):** Use a seção de [Histórico de Mensagens e Handoff](#-historico-de-mensagens-e-handoff) para descrever decisões de arquitetura não óbvias, avisos de breaking changes ou impedimentos encontrados.
4.  **Respeito aos Territórios:** Consulte o [Catálogo de Agentes](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/AGENTES_E_SKILLS.md) antes de editar código nas pastas protegidas de cada especialista.

---

## 📋 Quadro de Tarefas Ativas

| ID | Especialista | Descrição da Tarefa | Status | Arquivos Alvos | Notas / Entregáveis Esperados |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `T-001` | **Líder (Antigravity)** | Criação da Central de Comunicação e alinhamento do protocolo | `Concluído` | [COMUNICACAO_AGENTES.md](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/COMUNICACAO_AGENTES.md) | Central criada e pronta para uso. |
| `T-002` | **Líder (Antigravity)** | Identificar pendências atuais de Git (health.py e index.js) | `Concluído` | [health.py](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/backend/app/routers/health.py), [index-BBcj3Zw-.js](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/dist/assets/index-BBcj3Zw-.js) | Feito o push das pendências anteriores para origin/claude/session-improvements. |
| `T-003` | **Líder (Antigravity)** | Implementar a ação "Excluir definitivamente" e esvaziar lixeira | `Concluído` | [trash.py](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/backend/app/routers/trash.py), [index-BBcj3Zw-.js](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/dist/assets/index-BBcj3Zw-.js) | Adicionado botão individual e esvaziador no frontend + rota DELETE no backend. |
| `T-004` | **Líder (Antigravity)** | Mudar cor do botão de conexão no perfil para Vermelho se desconectado | `Concluído` | [index-BBcj3Zw-.js](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/dist/assets/index-BBcj3Zw-.js) | Cor alterada no componente do perfil para vermelho (rose) quando desconectado e verde quando conectado. |
| `T-005` | **Claude Code (Opus 4.8)** | Card semanal do Teams: de data dump para **convite de adoção** (horas + adoção + saúde) + fix do "Período" em branco | `Concluído` | [reports.py](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/backend/app/routers/reports.py), [config.py](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/backend/app/core/config.py), `.env.example`, `test_report_teams_card.py` | `compute_card_business` + `build_adoption_card`; settings `REPORT_MINUTES_PER_FILE` / `REPORT_CARD_ACCESS_URL`; 8/8 testes. Commit `f3eb3b4` (**sem push**). |
| `T-006` | **Claude Code (Opus 4.8)** | Solução self-service "Solicitar acesso" no Teams (Adaptive Card → Lista do SharePoint + aviso ao aprovador) + 2ª mensagem no card | `Concluído` | [GUIA_POWER_AUTOMATE.md](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/GUIA_POWER_AUTOMATE.md) | Documentação/fluxo Power Automate (sem código backend). Consolidada no guia unificado (Parte II/III). |
| `T-007` | **Claude Code (Opus 4.8)** | Unificar TODOS os guias do Power Automate em um único arquivo | `Concluído` | [GUIA_POWER_AUTOMATE.md](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/GUIA_POWER_AUTOMATE.md) | ⚠️ Removeu `POWER_AUTOMATE.md` / `GUIA_FLUXO_POWER_AUTOMATE.md` / `GUIA_TEAMS_CARD_POWER_AUTOMATE.md` / `GUIA_TEAMS_SOLICITACAO_ACESSO.md`; repontou `CLAUDE.md`, `BACKEND_START.md`, `DOC_FILES`. Commit `b7960bd` (**sem push**). |
| `T-008` | **Claude Code (Opus 4.8)** | Status da automação preso em `manual_review` após resolver erros + ação "Resolvido" dentro da automação + ocultar card "Erros resolvidos" da Home | `Concluído` | [agent_tasks.py](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/backend/app/services/agent_tasks.py), [agents.py](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/backend/app/routers/agents.py), [automations.py](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/backend/app/routers/automations.py), [files.py](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/backend/app/routers/files.py), [index-BBcj3Zw-.js](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/dist/assets/index-BBcj3Zw-.js) | `recalculate_automation_status` (fonte única, trata `resolved` como sucesso) chamado no ciclo do agente e em `PUT /api/files/{id}`; novos endpoints `POST /api/files/{id}/resolve` e `POST /api/automations/{id}/resolve-errors`; botão **Resolvido** na automação (só em erro) + card pizza oculto da Home. `compileall`/import/rotas/`node --check` OK. |
| `T-009` | **Claude Code (Opus 4.8)** | Card semanal do Teams como **IMAGEM fiel** do mockup (PNG via Chromium offline) + botões Abrir Playground / Solicitar Acesso / Baixar PDF | `Concluído` | `backend/app/services/report_image.py` (novo), `reports.py`, `config.py`, `GUIA_POWER_AUTOMATE.md`, `test_report_teams_card.py`, `scripts/render_report_image_preview.py` | HTML+SVG 100% offline → PNG (Chromium 1217, render em thread); sidecar `image_file`/`image_url_placeholder`; **fallback** card-texto de adoção se o PNG não gerar; setting `REPORT_CARD_PLAYGROUND_URL`; guia Parte I reescrita (share-link direto do PNG). 12/12 testes + render real validado. Commit `203c0ac`. |
| `T-010` | **Claude Code (Opus 4.8)** | Agendamento: botão **"Enviar para a pasta de entrega"** (`deliver_to_folder`) opt-in + `REPORTS_PATH` → `backend/data/reports` | `Concluído` | `models/schedule.py`, migration `0011`, `routers/schedules.py`, `reports.py` (`persist_report`), `schedule_runner.py`, `config.py`, `index-BBcj3Zw-.js` | A cópia p/ `REPORT_DELIVERY_PATH` deixou de ser automática (era em TODO relatório) → virou opt-in por agendamento. Migration `0011` aplicada nos 2 ambientes. Commit `203c0ac`. |
| `T-011` | **Claude Code (Opus 4.8)** | Seletor de **Workspace inicia vazio** na automação + ação **"Resolvido"** seta status `active` | `Concluído` | `dist/assets/index-BBcj3Zw-.js`, `routers/automations.py` | Placeholder "Selecione um Workspace" (novo/personalizado); `resolve-errors` devolve a automação para ativa. Commit `203c0ac`. |
| `T-012` | **Claude Code (Opus 4.8)** | Fix contagem de execuções no relatório: **1 run = 1 execução** | `Concluído` | `routers/reports.py` (`block_executions`) | Auditoria pedida pelo usuário: Histórico ao vivo (`list_executions`) conta 1x, mas o relatório (`block_executions`) contava cada `agent_task` do run. Corrigido: filtra só `upload_files_to_workspace`. |
| `T-013` | **Usuário (Ederson)** | **Automações Personalizadas / IPC Workspace Updater** (feature nova, em andamento) | `Removido` | `routers/custom_automations.py`, `custom_automations/ipc_workspace_updater/*`, `main.py`, `dist/assets/custom_automation.js`, `run_ipc_updater.bat` | Router `/api/custom-automations` + updater IPC (parser de documentos, db_helper, cr_processor) + launcher. **REMOVIDO em 2026-07-07 a pedido do dono (não será mais produzido):** apagados o pacote `custom_automations/`, o router, a aba `custom_automation.js`, o `run_ipc_updater.bat`, deps `python-docx`/`pyyaml`, e desregistrado de `main.py`/`index.html`/scripts de build. Backup: `scratchpad/ipc_backup_20260707.zip`. |
| `T-014` | **Claude Code (Opus 4.8)** | Fix: conversão PDF deixava **instâncias órfãs do Office (Word/Excel) abertas** travando o PC | `Concluído` | [playground_upload.py](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/backend/app/services/playwright/playground_upload.py) | O Office aberto via COM não é filho do PowerShell → sobrevivia ao timeout do subprocess e virava órfão invisível, acumulando. Correção **rastreia só o PID que a conversão criou** (`HUB_PIDFILE` + snapshot `$before`/`Save-NewOfficePid`) e mata **apenas ele** (`_kill_tracked_office_process`, verificado via `tasklist`); **nunca** encerra o Word/Excel que o usuário abriu. Commit `fe47310`. |
| `T-015` | **Claude Code (Opus 4.8)** | Builders de release **auto-suficientes** (incluem feature IPC) e **limpos** (sem `.bak`) + release completa do zero | `Concluído` | [scripts/build_update_package.py](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/scripts/build_update_package.py), [scripts/build_release_empty_db.py](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/scripts/build_release_empty_db.py) | Ambos os builders passaram a incluir `custom_automations/` + `run_ipc_updater.bat` (senão o backend quebra no startup por ImportError) e a filtrar backups `.bak`/`.bak-*` (`".bak" in name`). Commits `ebee533` (update) e `b6f64e8` (full). Release completa offline validada (`forbidden_entries=0`, Chromium 1217, DB vazio, fix do Office incluído). |

*Legenda de Status: `Pendente` | `Em Progresso` | `Revisão` | `Concluído`*

---

## 💬 Histórico de Mensagens e Handoff

### 📅 22/06/2026 — Sincronização Inicial (Antigravity)
*   **Autor:** Antigravity (Líder)
*   **Mensagem:** 
    Olá, Claude e subagentes! Criei este arquivo para gerenciar as tarefas do **Stellantis Automation HUB**. 
    Atualmente, temos modificações no diretório de trabalho que ainda não foram integradas:
    1.  `backend/app/routers/health.py` possui a implementação do endpoint de diagnóstico `/api/diagnostics`.
    2.  `dist/assets/index-BBcj3Zw-.js` possui a substituição de chamadas diretas de `fetch("/api/health")` para a função helper `Oe("/api/health")` que propaga os headers de ambiente corretamente.
    
    Vou alinhar com o usuário para validar e commitar essas mudanças no branch atual e iniciar as próximas delegações.

### 📅 22/06/2026 — Implementações e Testes de Lixeira & Status (Antigravity)
*   **Autor:** Antigravity (Líder)
*   **Mensagem:**
    Finalizei a implementação de duas importantes solicitações de modificação:
    1. **Exclusão Definitiva na Lixeira (T-003):** O backend agora possui um endpoint `DELETE /api/trash` e o frontend possui um botão vermelho "Esvaziar Lixeira" no rodapé do modal, além dos botões individuais estarem devidamente renomeados para "Excluir definitivamente" para explicitar sua natureza permanente.
    2. **Cor do Botão de Conexão no Perfil (T-004):** A cor do botão no modal "Meu perfil" do Playground foi ajustada. Se o playground estiver conectado, o botão é verde (`bg-emerald-600`); se precisar de login, agora ele exibe um tom vermelho (`bg-rose-600 text-white`) de aviso em vez de amarelo.
    
    Realizamos testes funcionais e de navegação ponta a ponta com o subagente de navegador e registramos o screenshot de validação com sucesso.

### 📅 25/06/2026 — Card de adoção + unificação dos guias do Power Automate (Claude Code)
*   **Autor:** Claude Code (Opus 4.8)
*   **Mensagem:**
    Concluí duas frentes nesta sessão (2 commits no `main`, **ainda sem push** — aguardando o usuário):

    1.  **Card semanal do Teams (T-005, commit `f3eb3b4`):** o Relatório Simplificado entregue no Teams deixou de ser um dump de dados e virou uma **mensagem de adoção** — manchete-convite ("setup pronto, crie seu agente") + botão **Solicitar acesso**, **horas economizadas** (semana/acumulado, 4 min/arquivo via `REPORT_MINUTES_PER_FILE`), **adoção** (engenheiros por `network_id` em `add_playground_user_to_workspace` + SPECs prontas) e **saúde em 1 linha**. A tabela por SPEC, contagem de arquivos e status cru **saíram do card** e ficaram no PDF ("Ver detalhes (PDF)"). Corrigi o **"Período" em branco** (fallback de 7 dias). A lógica nova está em `compute_card_business` / `build_card_summary` (ramo `kind=adoption`) / `build_adoption_card` em `backend/app/routers/reports.py`. Novos settings: `REPORT_MINUTES_PER_FILE` e `REPORT_CARD_ACCESS_URL`.

    2.  **Guias do Power Automate (T-006/T-007, commit `b7960bd`):** unifiquei TODOS os guias num único **`GUIA_POWER_AUTOMATE.md`** (do zero: relatório-card + convite "Solicitar acesso" + formulário de acesso self-service → Lista do SharePoint + alternativas + troubleshooting + apêndices).
        > ⚠️ **Breaking de documentação:** `POWER_AUTOMATE.md`, `GUIA_FLUXO_POWER_AUTOMATE.md`, `GUIA_TEAMS_CARD_POWER_AUTOMATE.md` e `GUIA_TEAMS_SOLICITACAO_ACESSO.md` **não existem mais** — usem o guia unificado. Repontei `CLAUDE.md`, `BACKEND_START.md` e o `DOC_FILES` em `scripts/build_update_package.py`.

    **Validação:** `compileall backend/app` limpo; `backend/scripts/test_report_teams_card.py` **8/8 PASS**; regressão `test_scheduled_report_json_delivery.py` / `test_pdf_resend_flow.py` / `test_pdf_recovery.py` **PASS**. **Pendência:** `git push` para `origin/claude/session-improvements` aguardando confirmação do usuário.

### 📅 01/07/2026 — Card-imagem do Teams + agendamento opt-in + fix de contagem + release (Claude Code)
*   **Autor:** Claude Code (Opus 4.8)
*   **Mensagem:**
    Sessão de continuação. Entreguei (T-009 a T-012) e o usuário juntou tudo no commit **`203c0ac "Commit PowerAutomate"`** (o card-texto de adoção anterior — T-005/f3eb3b4 — evoluiu para o **card-IMAGEM** desta sessão):

    1.  **Card semanal do Teams vira IMAGEM fiel do mockup (T-009):** o HUB gera um **PNG** idêntico ao mockup (HTML+SVG 100% offline → screenshot com o **Chromium 1217** offline, renderizado numa thread p/ não travar o event loop) e o Power Automate posta a imagem num card com os botões **Abrir Playground / Solicitar Acesso / Baixar Relatório (PDF)**. Novo `backend/app/services/report_image.py`; `compute_card_image_data` + `build_report_image_card` em `reports.py`; sidecar ganhou `image_file`/`image_url_placeholder`; **fallback** automático para o card-texto quando o PNG não é gerado (sem Chromium). Guia Parte I reescrita (share-link **direto** do PNG, com o caveat de tenant). Setting `REPORT_CARD_PLAYGROUND_URL`.

    2.  **Agendamento com entrega opt-in + caminho dos relatórios (T-010):** a cópia para `REPORT_DELIVERY_PATH` deixou de acontecer em TODO relatório — virou **opt-in por agendamento** (`schedules.deliver_to_folder`, botão no modal "Agendar Relatório", **migration 0011** nos 2 ambientes). `REPORTS_PATH` mudou de `../relatorios/` para **`backend/data/reports`** (a pedido; revertendo a decisão de jun/2026 — registrado no CLAUDE.md).

    3.  **UX (T-011):** seletor de Workspace na automação **inicia vazio** ("Selecione um Workspace"); ação **Resolvido** devolve a automação para `active`.

    4.  **Auditoria de contagem de execuções (T-012):** a pedido, conferi se um run conta 1x. **Histórico ao vivo (`list_executions`) já contava 1x** (filtra `upload_files_to_workspace` + guard de task ativa). Mas o **relatório (`block_executions`) contava cada `agent_task`** do run (upload + monitor + connect + convert...). **Corrigido:** `block_executions` agora filtra só `upload_files_to_workspace` → **1 run = 1 execução**, igual ao dashboard.

    **Release + push:** gerada a release incremental `releases/hub_update_COMPLETO_20260701_134324.zip` (0,83 MB, `forbidden_entries=0`, sem DB, 23 `.bak` removidos). Commitei também a feature **T-013 (Automações Personalizadas / IPC Updater)** do usuário — WIP não revisado por mim, incluído a pedido. Push para `origin/claude/session-improvements`.

    **Validação:** `compileall backend/app` limpo; `test_report_teams_card.py` **12/12 PASS**; render real do PNG conferido; `node --check` no bundle OK; migration 0011 aplicada e coluna confirmada nos 2 bancos.

### 📅 01/07/2026 — Fix do Office órfão na conversão PDF + builders de release e release completa (Claude Code)
*   **Autor:** Claude Code (Opus 4.8)
*   **Mensagem:**
    Continuação da mesma sessão. Três frentes fechadas e pushadas para `origin/claude/session-improvements`:

    1.  **Instâncias órfãs do Office travando o PC (T-014, commit `fe47310`):** o usuário notou arquivos **Word/Excel ficando abertos** após a conversão para PDF, acumulando até travar a máquina. Causa: o Office iniciado via **COM** não é processo-filho do PowerShell, então **sobrevivia ao `TimeoutExpired`** do subprocess e virava um processo invisível órfão. Correção em `convert_office_via_com`/`_OFFICE_COM_PS_SCRIPT`: tira um snapshot dos PIDs de Office **antes** de abrir (`$before`), grava em `HUB_PIDFILE` **só o PID novo** que a conversão criou (`Save-NewOfficePid`), e no `finally` mata **apenas esse PID** (`_kill_tracked_office_process`, revalidado via `tasklist` para confirmar que ainda é um processo de Office). ⚠️ **Invariante crítica:** **nunca** encerra o Word/Excel que o próprio usuário abriu — só o que a conversão spawnou. `$app.Quit()` + `ReleaseComObject` continuam antes do kill (encerramento limpo primeiro; o kill é a rede de segurança).

    2.  **Builders de release auto-suficientes e limpos (T-015, commits `ebee533` + `b6f64e8`):** tanto o pacote incremental (`build_update_package.py`) quanto a release completa (`build_release_empty_db.py`) passaram a **incluir `custom_automations/` + `run_ipc_updater.bat`** — sem eles o backend quebra no startup (`ImportError` do router IPC) — e a **filtrar backups `.bak`** (inclui `.bak-YYYYMMDD`, cujo sufixo não é exatamente `.bak`) via `".bak" in name`. Descoberto porque uma ZIP completa havia embarcado arquivos `.bak` mesmo com `forbidden_entries=0`.

    3.  **Release completa do zero:** gerada `releases/Automation_HUB_company_notebook_chromium_no_login_empty_db_20260701_154141.zip` (301 MB) — `forbidden_entries=0`, **0 `.bak`**, Chromium 1217 offline (+ headless_shell + ffmpeg), `custom_automations/` incluído, DB vazio, fix do Office confirmado dentro do ZIP (`HUB_PIDFILE` + `_kill_tracked_office_process`). ZIP é gitignored (não entra no commit — artefato de 301 MB).

    **Validação:** `compileall backend/app` limpo; conteúdo do ZIP inspecionado programaticamente (731 entradas, 0 `.bak`, fix presente); build report `EXITCODE=0`.


---

## 🛠️ Validação de Integridade Cross-Cutting

Sempre que concluir uma tarefa de codificação, execute os seguintes comandos no terminal para garantir que nenhuma regressão foi introduzida:

```powershell
# 1. Compilação estática de arquivos Python
.\backend\.venv\Scripts\python.exe -m compileall backend\app

# 2. Execução dos testes automatizados (se configurados)
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q
cd ..
```
