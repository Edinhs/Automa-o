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
| `T-016` | **Claude Code (Opus 4.8)** | Revisão de código + criação de **SPECS.md** e **PDR.md** + atualização de **Briefing.md** e desta Central | `Concluído` | [SPECS.md](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/SPECS.md), [PDR.md](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/PDR.md), [Briefing.md](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/Briefing.md), [COMUNICACAO_AGENTES.md](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/COMUNICACAO_AGENTES.md) | Revisão estática do backend (`compileall` limpo, exit 0). Criados **SPECS** (contrato técnico: arquitetura, modelo de dados, protocolo agente↔backend, invariantes RPA, API, config) e **PDR** (requisitos de produto, RF/RNF, riscos, roadmap, ADR). Briefing reescrito p/ o estado atual. 6 achados registrados no SPECS §12 (nenhum bloqueante; **sem alteração de comportamento**). **Sem commit/push.** |
| `T-017` | **Claude Code (Opus 4.8)** | Achados da revisão a decidir com o dono (backlog) | `Pendente` | `services/agent_tasks.py`, `routers/agents.py`, `main.py`, `CLAUDE.md` | Backlog priorizado (ver SPECS §12 / PDR §10): #1 promover `automation_id` a coluna indexada em `agent_tasks` (dívida arquitetural, O(N) na finalização); #2 escopar match de arquivo por nome ao `automation_id`; #3 remover ramo morto em `update_files_from_result`; #4 migrar `on_event`→`lifespan`; #6 reconciliar `CLAUDE.md`/`RELEASE_POLICY.md` (IPC removido; tests como scripts). **Aguardando priorização do dono.** |
| `T-018` | **Claude Code (Opus 4.8)** | Ampliar o time de subagentes: 1 especialista por função + orquestrador com paralelização/subagentes | `Concluído` | [.claude/agents/](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/.claude/agents/), [AGENTES_E_SKILLS.md](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/AGENTES_E_SKILLS.md) | **6 novos agentes** (5→11): `reports-expert`, `scheduler-expert`, `integrations-expert`, `frontend-bundle-expert`, `qa-test-expert` (especialistas) + `feature-orchestrator` (opus, decompõe e **spawna** o time). `Task` habilitado em orchestrator/reports/integrations/qa (criam subagentes). `fastapi-expert` recebeu carve-outs (reports/schedules/integrations têm dono). Catálogo + diagrama mermaid + modelo de orquestração reescritos. Territórios disjuntos → paralelização segura. **Sem commit/push.** |

| `T-019` | **Claude Code (Opus 4.8)** | Aba Automações: exibir status "Ativo, Revisão Manual, Executando, Interrompido" (badge + filtro) | `Concluído` | [dist/assets/index-BBcj3Zw-.js](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/dist/assets/index-BBcj3Zw-.js), [CLAUDE.md](file:///c:/Users/Edinh/OneDrive/Ambiente%20de%20Trabalho/Automa-o-main/CLAUDE.md) | O adapter passava a chave crua (`active/running/manual_review/stopped`) ao badge/filtro. Adicionado campo `statusLabel` (pt-BR), mantendo `status` cru (o menu `oW` usa `manual_review`/`failed` p/ o botão **Resolvido**). Coluna badge → `statusLabel`; filtro `T` com base fixa dos 4 + presentes; predicado por `statusLabel`; cores em `rW`; EN no `r3`. **Só frontend** (backend já produzia todos os status). `node --check` OK. Backup `.bak_automation_status_20260715_155357`. **Sem commit/push.** |

| `T-020` | **Líder + 3 subagentes** | Opção de **idioma no relatório (Português/Inglês)** — relatórios em inglês quando solicitado | `Concluído` | `core/report_i18n.py` (novo), `alembic/versions/..0013_report_language.py` (novo), `models/execution.py`, `models/schedule.py`, `routers/reports.py`, `routers/schedules.py`, `services/schedule_runner.py`, `services/report_image.py`, `dist/assets/index-BBcj3Zw-.js` | Delegado (dono pediu "você apenas delega"): **Backend** (reports+db+scheduler) + **Frontend** (bundle) em paralelo, depois **Validação** (release+qa). Contrato: `language` ("pt"/"en") no corpo de `POST /api/reports`; `report_language` no agendamento; colunas `execution_reports.language` e `schedules.report_language` (default "pt"). Migração 0013 aplicada nos 2 ambientes (head `a9c2e4f6b731`). Relatório EN real gerado e localizado; **PT byte-idêntico (zero regressão)**. `compileall` exit 0. ⚠️ 3 testes em `test_report_teams_card.py` + entrega em `test_scheduled_report_json_delivery.py` vermelhos, mas **pré-existentes** (provado vs. snapshot 10/07) — não causados pela feature. **Sem commit/push.** |

| `T-021` | **Líder + subagente** | Bug: **ID de rede não salvo** ao incluir usuário (aba Usuários) | `Concluído` | `backend/app/routers/users.py` | Delegado. **Causa raiz:** não era o `network_id` — o form envia `role` capitalizado ("User") e `status` em PT ("Ativo"), e `user_payload` levantava **422** (`VALID_ROLES`/`VALID_STATUSES` são minúsculo/inglês) → o POST inteiro falhava, nada salvava. **Fix (backend, menor risco):** `normalize_role` (lower) + `normalize_status` (lower + aliases PT→EN: ativo→active, etc.) + `VALID_STATUSES` ganhou `pending`; validação NÃO enfraquecida (`Superadmin`→422). Provado ao vivo (env developer): POST role="User"/status="Ativo" → 200 com `network_id` correto; base de dev limpa. Backend reiniciado. **Sem commit/push.** |
| `T-022` | **Líder + subagente** | UI: modal da **Lixeira** (Config > Lixeira) menor + com barra de rolagem | `Concluído` | `dist/assets/index-BBcj3Zw-.js` | Delegado ao frontend-bundle-expert (sequenciado após T-021 p/ não editar o bundle em paralelo). Painel `max-w-2xl max-h-[85vh]` → `max-w-lg max-h-[75vh]` (42rem→32rem; 85vh→75vh); corpo mantém `flex-1 min-h-0 overflow-auto` (header/footer fixos, conteúdo rola). `max-w-lg` (não md) p/ não apertar "Restaurar"/"Excluir definitivamente". Backup `.bak_lixeira_modal_20260716_104144`, `node --check` OK. Só frontend → **hard-refresh (Ctrl+F5)**. **Sem commit/push.** |

| `T-023` | **Líder (orquestrador)** | Verificação: "sincronização com o backend demorando muito" | `Concluído (diagnóstico)` | — | Triagem read-only. **Backend saudável:** endpoints de sync todos <300ms (operational e developer), DBs pequenos (agent_tasks 22/41, logs 734/2057), `reloadBackendData` já é paralelo (`Promise.all` automations+workspaces). **CAUSA RAIZ:** o **agente local está PARADO** — último heartbeat `2026-07-14 02:02` (~2,5 dias atrás), nos 2 ambientes → tarefas enfileiradas (upload/connect/monitor) nunca são consumidas → a UI fica "sincronizando" sem fim. Também há **2 processos uvicorn órfãos** na :8000 (PID 516 + 35248, efeito colateral de backends subidos por subagentes). **Ação recomendada ao dono:** `restart_services.bat` (mata os HUB na 8000/5173 e sobe backend único + dashboard + **agente**). Sem código a alterar. |

| `T-024` | **Líder + subagente** | Card **"Resumo de Erros"** (Home) deve refletir erros existentes e **diminuir** quando resolvidos | `Concluído` | `backend/app/routers/overview.py`, `dist/assets/index-BBcj3Zw-.js` | Delegado. **Duas causas** (ambas corrigidas): (1) contagem — os 3 contadores do card vinham só da agregação array-side (teto 1000), sem override do `/api/overview`; (2) staleness — a Home não re-buscava o overview ao resolver. **Fix:** `overview.py` devolve `automationErrorCount`(status error/failed)/`workspaceErrorCount`(playground_status ~erro)/`manualActionCount`(status manual_review) por COUNT O(1); `U_final` sobrescreve os 3 de `g.overview`; `reloadBackendData` global (`ie→ce`) dá bump no `refreshVersion` e a Auditoria de Arquivos chama o reload global após resolver. **Prova ao vivo (developer):** criar erro→19; resolver→**18** (desce), resolvedFiles 3→4; dado de teste limpo. Backend reiniciado. Backup `.bak_resumo_erros_20260716_152555`, `node --check` OK. **Hard-refresh** p/ ver. **Sem commit/push.** |
| `T-025` | **Líder + subagente** | Aba Arquivos > **Detalhes**: caminhos/SHA-256 longos vazam da caixa | `Concluído` | `dist/assets/index-BBcj3Zw-.js` | Fix nos componentes compartilhados do drawer `yX_FileDetails`: `Wl` (raiz +`min-w-0`, valor +`break-all`) e `sd` (item de caminho +`break-all`), replicando o `break-all` do `h2` do nome. SHA-256 (64 chars) e caminhos Windows agora quebram dentro do cartão; `min-w-0` deixa o cartão encolher no grid `md:grid-cols-2`. DRY (vale p/ todo uso de `Wl`/`sd`). Anchors únicos. Backup `.bak_detalhes_overflow_20260716_153314`, `node --check` OK. **Hard-refresh.** **Sem commit/push.** |

| `T-025` | **Líder + subagente** | Aba Arquivos > **Detalhes**: caminhos/SHA-256 longos vazam da caixa | `Pendente` | `dist/assets/index-BBcj3Zw-.js` | **Fila atrás do T-024** (mesmo bundle — não editar em paralelo). Diagnóstico: no drawer "Detalhes do Arquivo", o valor do `Wl` (~offset 712974) e o item de caminho do `sd` (~713330) não têm `break-all`/`min-w-0` → hash de 64 chars e caminhos extensos estouram na horizontal. Fix: `break-all` (+ `min-w-0` na raiz do `Wl`) no valor do `Wl` e no `<p>` do `sd` (mesmo padrão que o `h2` do nome já usa). Componentes compartilhados → DRY. Backup + `node --check`. |

| `T-026` | **Líder + subagente** | Janela **"Sobre"**: remover a informação/textura pontilhada (difícil visualização) + janela limpa | `Concluído` | `dist/assets/index-BBcj3Zw-.js` | Removido o `<div>` da camada de pontinhos (`radial-gradient(#fff 1px, transparent 1px)`) do hero de "Sobre & Diagnósticos" (elemento apagado, não só opacidade; bolhas `blur` e conteúdo `z-10` preservados). Adicionada uma **janela limpa** de alto contraste (`rounded-2xl border-white/10 bg-white/5 backdrop-blur-md`, grid 3col) com **Nome / Versão / Autor** (rótulos `#93c5fd`, valores `#f8fafc`, bilíngue). Grid de saúde e botão "Baixar README" intocados. Backup `.bak_sobre_janela_20260716_154515`, `node --check` OK. **Hard-refresh.** **Sem commit/push.** |

| `T-027` | **Líder + subagente** | Login manual sem timeout: headless→visível deve **esperar indefinidamente** pelo login (não falhar) | `Concluído` | `backend/app/services/playwright/playground_login.py` | `wait_for_login_completion` agora é `while True` (sem `deadline`/timeout, `raise PlaygroundLoginTimeout` removido): espera indefinidamente até `is_logged_in`, com `should_continue()` a cada iteração (botão "parar" → task vira `cancelled`, nunca `failed`) + log de lembrete a cada ~30s. Fluxo: headless→`PlaygroundLoginRequired`→retry visível→espera sem timeout→segue. `MANUAL_LOGIN_TIMEOUT_MINUTES`/`PlaygroundLoginTimeout` ficam sem uso (não removidos). `compileall` exit 0. Sem Chromium no dev copy → roteiro de teste ao vivo entregue. **Requer restart do backend na instância real.** **Sem commit/push.** |

| `T-028` | **Líder + subagente** | Pacote de **deploy** das correções da sessão (T-019→T-027) para a instância de produção | `Em Progresso` | `scripts/build_update_package.py`, `releases/`, `DEPLOY_UPDATE_*.md` | Delegado ao release-integrity-expert. Motivo: o HUB de produção do dono roda em OUTRA pasta (diagnóstico: 1981 arquivos, Chromium presente) — as correções estão no working copy de dev e precisam ser implantadas. Gera pacote incremental (overlay que **preserva** DB/dados/venv/Chromium), valida (forbidden_entries=0 + presença de playground_login/users/overview/reports/report_i18n/migração 0013/bundle novo) e escreve runbook (stop_all → backup DB → extrair por cima → alembic upgrade head 2 envs → start_all c/ **agente** → hard-refresh → verificar /api/diagnostics). |

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

### 📅 15/07/2026 — Revisão de código + SPECS/PDR + atualização de Briefing e Central (Claude Code)
*   **Autor:** Claude Code (Opus 4.8)
*   **Mensagem:**
    Sessão de documentação e revisão a pedido do dono ("revise o código, crie SPECS, PDR e atualize Briefing e comunicação com o Agente"). **Nenhuma linha de código de produto foi alterada** — entrega de documentação + revisão. Quatro frentes (T-016):

    1.  **Revisão de código (backend `backend/app`, ~15,3k linhas):** li os núcleos — `main.py`, `core/config.py` (ContextVar de ambiente), `db/session.py` (engines por-ambiente), `routers/deps.py` (auth), `routers/agents.py` (protocolo), `services/agent_tasks.py` (fonte única de status), `cli/local_agent.py` (loop do agente, dispatch, dedup, reenvio), trechos de `routers/reports.py` (card/relatório/`block_executions`) e todos os `models/`. **`compileall backend/app` limpo (exit 0).** Pontos fortes confirmados: isolamento por ambiente consistente, claim atômico de tarefa, heurística de upload defensiva, checkpoints por lote sem duplicata, `get_db` com rollback-on-exception, fix do Office órfão. **6 achados** registrados (nenhum bloqueante).

    2.  **`SPECS.md` (novo):** contrato técnico completo — visão, stack, arquitetura de execução (isolamento por ambiente, migrações, ciclo de vida), **modelo de dados** (12 tabelas), **protocolo agente↔backend** (6 tipos de tarefa, claim atômico, dedup, checkpoints, monitor único, recuperação de login, máquina de estados), **invariantes do RPA**, superfície da **API REST**, scheduler, integrações, frontend, configuração e **§12 com os achados/dívida técnica**.

    3.  **`PDR.md` (novo):** documento de produto e requisitos — problema, personas, objetivos/não-objetivos, **19 RF + 8 RNF**, fluxos-chave, riscos, métricas de sucesso, roadmap sugerido e ADR (decisões registradas: remoção do IPC, entrega opt-in, card→imagem, etc.).

    4.  **`Briefing.md` (reescrito)** para o estado atual (isolamento por ambiente, checkpoints, monitor único, ação "Resolvido", card-imagem, entrega opt-in, IPC removido) + **esta Central** (T-016/T-017 e este handoff).

    > **Achados a decidir (T-017, backlog — ver SPECS §12 / PDR §10):** #1 (**média**) `automation_id` vive no `payload_json` de `agent_tasks`, não em coluna → `recalculate_automation_status`/`related_automation_tasks`/`block_executions` varrem todo o histórico e filtram em Python (O(N)); recomendo promover a coluna indexada com migração de backfill. #2 match de arquivo por `file_name` global sem escopo de automação. #3 ramo morto em `update_files_from_result` (`routers/agents.py:210`). #4 `@app.on_event` deprecado → `lifespan`. #5 upsert de `LocalAgent` sem filtro `is_deleted`. #6 **deriva de documentação:** `CLAUDE.md`/comandos citam `backend/tests`+pytest+`requirements-dev.txt` (inexistentes — testes vivem em `backend/scripts/test_*.py`) e ainda referenciam a feature IPC já removida.

    **Validação:** `backend/.venv/Scripts/python.exe -m compileall -q backend/app` → **exit 0**. Sem testes rodados (nenhuma mudança de código). **Sem commit/push** — aguardando revisão do dono.

### 📅 15/07/2026 — Ampliação do time de subagentes (1 por função) + orquestrador com paralelização (Claude Code)
*   **Autor:** Claude Code (Opus 4.8)
*   **Mensagem:**
    A pedido do dono ("crie agentes para cada função do projeto, com paralelização, e que criem subagentes para trabalharem em conjunto"), ampliei o time de **5 → 11 subagentes** em `.claude/agents/` (T-018). **Nenhuma mudança de código de produto** — só definições de agente + catálogo.

    **6 novos agentes** (formato idêntico aos existentes: `name`/`description`/`tools`/`model` + system prompt em pt-BR, território disjunto, invariantes, fluxo de validação, "como reportar"):
    1. **`reports-expert`** (sonnet, +Task) — `routers/reports.py` + `services/report_image.py`: blocos de relatório, XLSX/PDF/CSV, 1-run-1-execução, card-imagem + fallback, entrega opt-in.
    2. **`scheduler-expert`** (sonnet) — `schedule_runner.py` + `routers/schedules.py` + `timezone.py`: loop asyncio dual-environment, frequências, `next_run_at` idempotente, disparo de automação/relatório.
    3. **`integrations-expert`** (sonnet, +Task) — `routers/integrations.py` + `graph_client.py` + `GUIA_POWER_AUTOMATE.md`: MS Graph app-only, `IntegrationDelivery`, sanitização de segredo, entrega por pasta/deep link, fallback `not_configured`.
    4. **`frontend-bundle-expert`** (sonnet) — `dist/assets/index-BBcj3Zw-.js`: edição do bundle minificado, backup `.bak`, helpers `Oe`/`kt` (nunca `fetch` cru), `node --check`, padrões visuais.
    5. **`qa-test-expert`** (sonnet, +Task) — `backend/scripts/test_*.py`: gate de teste (sem-duplicata, reenvio PDF, agrupamento de execução, card, entrega agendada); nunca relaxa asserção.
    6. **`feature-orchestrator`** (opus, +Task) — decompõe features cross-cutting, **spawna os especialistas em paralelo/sequência**, escreve o contrato compartilhado nos dois lados, integra e fecha pelo gate. É o agente do "criem subagentes para trabalharem em conjunto".

    **Paralelização:** territórios são **disjuntos no nível de arquivo** → seguros em paralelo (spawn de vários Task numa leva). Dependências de contrato são **sequenciadas** (quem define o schema vai antes de quem consome). Territórios sobrepostos nunca vão em paralelo. **Subagentes aninhados:** `Task` habilitado em orchestrator/reports/integrations/qa; se a versão do Claude Code não permitir spawn aninhado, o agente degrada para um plano de delegação ordenado e devolve ao líder.

    **Ajustes:** `fastapi-expert` ganhou seção de **carve-outs** (reports/schedules/integrations agora têm dono; ele mantém só o registro/proteção em `main.py`). `AGENTES_E_SKILLS.md` reescrito (diagrama mermaid com os 11 agentes em 2 tiers + modelo de orquestração + nota de subagentes aninhados).

    **Validação:** frontmatter dos 11 agentes conferido (`name`/`model`/`tools` OK; `Task` presente onde previsto). **Sem commit/push** — aguardando revisão do dono.

### 📅 16/07/2026 — Idioma do relatório (PT/EN) entregue via delegação a 3 subagentes (Líder)
*   **Autor:** Claude Code (Opus 4.8) — como **líder/orquestrador** (o dono instruiu: "você apenas delega aos agentes"; registrado em memória)
*   **Mensagem:**
    Feature T-020 — opção de idioma **Português (padrão) / Inglês** no relatório — entregue **sem eu editar código**: defini o contrato e deleguei a subagentes.

    **Contrato fixo (liderança):** geração → campo `language` ("pt"/"en") no corpo de `POST /api/reports`; agendamento → `report_language` ("pt"/"en"); persistência em `execution_reports.language` e `schedules.report_language` (default "pt"); `en` traduz títulos de seção, cabeçalhos, rótulos de status e o card/imagem do Teams; `pt`/omitido = comportamento idêntico.

    **Execução (paralela + sequencial):**
    1.  **Frontend-bundle-expert** (paralelo): `<select>` Português/Inglês na geração e no modal "Agendar Relatório" do componente `oX`; envia `language`/`report_language` via `Oe`/`kt`. Backup `.bak_report_language_20260715_160350`, `node --check` OK.
    2.  **Backend** (paralelo, personas reports+db+scheduler): módulo novo `core/report_i18n.py` (mapa PT/EN centralizado), `language` roteado por todos os blocos + summary + card + `report_image.py`, colunas + migração `0013`, propagação no `schedule_runner`. **Caiu por limite de sessão** antes de aplicar a migração.
    3.  **Validação/release** (sequencial, personas release+qa): `compileall` exit 0; migração `0013` confirmada nos 2 ambientes (head `a9c2e4f6b731`, colunas presentes); **relatório EN real gerado e localizado** (Summary/Detected Files/…); **PT byte-idêntico** (regressão zero, provada). Auditoria de coerência do código: nenhuma correção necessária.

    **Verificação de integração (líder):** o contrato bate exatamente entre frontend e backend (`language` na geração, `report_language` no agendamento).

    ⚠️ **Ressalva não-bloqueante:** 3 testes de `test_report_teams_card.py` + a asserção de entrega de `test_scheduled_report_json_delivery.py` estão vermelhos, mas **pré-existentes** (testes desatualizados vs. o botão "Solicitar Acesso" ShowCard de 10/07 e a política "entrega só do Simplificado" de 07/07) — provado empiricamente contra o snapshot pré-feature; **nenhuma asserção foi relaxada**. Sugiro atualizar esses testes stale numa tarefa à parte.

    **Para operar ao vivo:** **reiniciar o backend** (`restart_services.bat`) para carregar o novo tratamento de `language`, e **hard-refresh (Ctrl+F5)** no dashboard (nome do bundle inalterado). **Sem commit/push.**


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
