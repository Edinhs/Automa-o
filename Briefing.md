# Automation HUB - Briefing do Projeto

O **Stellantis Automation HUB** é uma plataforma de orquestração e execução de automações robóticas (RPA) que integra uma pasta local monitorada com a plataforma web **Playground** (`https://genai.stellantis.com/`). O sistema automatiza a ingestão, o monitoramento e o tratamento de documentos em larga escala — devolvendo tempo de engenharia com eficiência, resiliência e rastreabilidade total.

> **Documentos relacionados:** [`SPECS.md`](./SPECS.md) (especificação técnica), [`PDR.md`](./PDR.md) (requisitos de produto), [`CLAUDE.md`](./CLAUDE.md) (runbook profundo), [`BACKEND_START.md`](./BACKEND_START.md) (endpoints e tabelas), [`GUIA_POWER_AUTOMATE.md`](./GUIA_POWER_AUTOMATE.md) (entrega Teams), [`COMUNICACAO_AGENTES.md`](./COMUNICACAO_AGENTES.md) (orquestração de agentes).
>
> *Última atualização: 2026-07-15.*

## 🏗️ Arquitetura do Sistema

Três processos cooperantes compartilham um único backend/estado:

1.  **Backend (FastAPI & SQLAlchemy):**
    -   Centraliza o estado, a fila de tarefas (`AgentTask`) e a API REST do dashboard.
    -   Orquestra o scheduler embutido e as integrações Microsoft Graph (e-mail/Teams).
    -   **Isolamento por ambiente** (operacional × desenvolvedor): cada requisição carrega o header `X-App-Environment` e resolve banco e caminhos por ambiente.

2.  **Agente Local (Python CLI):**
    -   Serviço de longa duração que opera onde os arquivos estão.
    -   Faz polling da fila, escaneia a pasta, valida hashes (SHA256) para deduplicação e prepara (staging) os uploads.
    -   Dirige cada tarefa Playwright e reporta o desfecho de volta ao backend.

3.  **Serviços de Automação (Playwright/Chromium):**
    -   Simula interações humanas para operar o Playground: login, criação de workspace, upload em lotes e monitoramento de status.
    -   Chromium 1217 **embarcado e offline** (bypass de proxy/cert corporativo); `PLAYWRIGHT_HEADLESS=false` permite SSO manual.

O **frontend** é um bundle React/Vite **pré-compilado**, servido estaticamente de `dist/` (sem fonte no repositório — alterações são feitas editando o bundle).

## 🛠️ Funcionalidades Principais

*   **Monitoramento inteligente de pastas:** detecção de arquivos novos/alterados por data de modificação (mtime) e hash de conteúdo (SHA256), com baseline persistente entre execuções.
*   **Upload em lotes com checkpoint:** cada lote é confirmado de forma idempotente; nenhum lote posterior é enviado se um checkpoint falhar (sem duplicatas no workspace).
*   **Monitoramento em passo único:** após o envio, o status é lido de uma vez, sem manter o navegador aberto durante a espera.
*   **Tratamento automático de erros:** conversão para PDF (MS Office via COM → fallback LibreOffice headless) e **reenvio em lotes** dos arquivos que falharam; recuperação de sessão (login headless → visível, repetindo a tarefa uma vez).
*   **Ação "Resolvido":** por arquivo e por automação, com recálculo de status por uma fonte única de verdade.
*   **Agendador robusto:** execuções `once` / `interval` / `daily` / `weekly` / `monthly`, em horário de São Paulo, para automações **e** relatórios.
*   **Relatórios & entrega:** XLSX/PDF/CSV; **card semanal do Teams como imagem fiel** (Abrir Playground / Solicitar Acesso / Baixar PDF); entrega do **Relatório Simplificado** na pasta de pickup (Power Automate) — **opt-in por agendamento**.
*   **Integrações Microsoft Graph:** envio de e-mail/Teams com fallback gracioso (`not_configured`) quando não configurado.
*   **Rastreabilidade total:** logs estruturados, metadados de execução, screenshots automáticos em incidentes e preservação do staging para auditoria.

## 🔄 Fluxo de Operação

1.  **Configuração:** origem (pasta local) e destino (workspace do Playground).
2.  **Disparo:** por agendamento ou comando manual → o backend enfileira um `upload_files_to_workspace` com `files: []`.
3.  **Preparação (no agente):** scan, deduplicação por SHA256/mtime, classificação (`new`/`updated`/`audit_duplicate`) e staging.
4.  **Execução web:** login (se necessário), upload em lotes com checkpoint.
5.  **Monitoramento:** passo único lê o status; falhas são convertidas para PDF e reenviadas em lotes.
6.  **Conclusão:** status final por fonte única (`completed`/`manual_review`/`failed`), relatórios e (opcional) card de adoção no Teams.

## 💻 Stack Tecnológica

- **Linguagem:** Python 3.x
- **Backend:** FastAPI (ASGI: uvicorn)
- **ORM/Migrações:** SQLAlchemy + Alembic (head atual: `0012`)
- **Automação Web:** Playwright 1.59.0 (Chromium 1217 offline)
- **Documentos:** MS Office (COM/PowerShell) → LibreOffice headless
- **Relatórios:** openpyxl (XLSX), reportlab (PDF), csv; imagem do card via Chromium
- **Banco:** SQLite (WAL) — trocável por PostgreSQL só via `DATABASE_URL`
- **Integrações:** MSAL + Microsoft Graph (app-only)
- **Interface:** dashboard React/Vite pré-compilado (`dist/`), integrado por API

## 🧭 Restrições e princípios de projeto

-   **Deploy offline sem login por padrão** (`AUTH_DISABLED=true`); o caminho JWT completo é preservado.
-   **Isolamento por ambiente** é a restrição central: nunca hardcodar caminho ou sessão de banco — usar `runtime_path`/`get_db`.
-   **Não enfraquecer** a heurística de confirmação de upload nem a verificação de delete por F5.
-   **Não-destrutivo:** soft-delete em todas as tabelas; staging temp preservado para auditoria.
-   **Fora de escopo:** a feature IPC / Automações Personalizadas foi **removida** (2026-07-07) e não será mais produzida; relatórios automáticos de monitoramento de pasta estão desativados.

---
*Este documento é o guia de referência de alto nível do Automation HUB. Para o contrato técnico detalhado, ver [`SPECS.md`](./SPECS.md); para requisitos e decisões de produto, ver [`PDR.md`](./PDR.md).*
