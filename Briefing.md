# Automation HUB - Briefing do Projeto

O **Automation HUB** é uma plataforma de orquestração e execução de automações robóticas (RPA) projetada para integrar sistemas de arquivos locais com a plataforma web **Playground**. O sistema automatiza o fluxo de ingestão, monitoramento e tratamento de documentos em larga escala, garantindo eficiência e rastreabilidade.

## 🏗️ Arquitetura do Sistema

O projeto é estruturado em três camadas principais que trabalham de forma sincronizada:

1.  **Backend (FastAPI & SQLAlchemy):**
    -   Centraliza a inteligência do sistema.
    -   Gerencia usuários, permissões, workspaces e configurações de automação.
    -   Orquestra a fila de tarefas (`AgentTask`) e armazena logs de execução.
    -   Suporta isolamento por ambientes (Ex: Desenvolvimento, Produção).

2.  **Agente Local (Python CLI):**
    -   Serviço que opera no ambiente onde os arquivos estão localizados.
    -   Realiza o consumo da fila de tarefas do Backend via polling.
    -   Responsável por operações de I/O: scan de pastas, validação de hashes (SHA256) e preparação de arquivos.

3.  **Serviços de Automação (Playwright):**
    -   Simula interações humanas no navegador para operar a plataforma Playground.
    -   Realiza uploads inteligentes, navegação complexa e monitoramento de status de processamento em tempo real.

## 🛠️ Funcionalidades Principais

*   **Monitoramento Inteligente de Pastas:** Detecção automática de arquivos novos ou modificados através de comparação de hashes.
*   **Gestão de Upload em Lotes (Batching):** Otimização de grandes volumes de dados para evitar instabilidades na interface web.
*   **Agendador Robusto (Scheduler):** Suporte a execuções pontuais, intervalares ou recorrentes (diário/semanal/mensal).
*   **Tratamento Automático de Erros:**
    -   Conversão automática para PDF via LibreOffice Headless quando o processamento original falha.
    -   Mecanismos de recuperação de sessão e reinício automático de tarefas críticas.
*   **Rastreabilidade Total:** Registro de logs detalhados, metadados de execução e capturas de tela automáticas em caso de incidentes.

## 🔄 Fluxo de Operação

1.  **Configuração:** Definição da origem (pasta local) e destino (Workspace Playground).
2.  **Disparo:** Execução via agendamento ou comando manual.
3.  **Preparação:** Scan local, deduplicação e staging dos arquivos.
4.  **Execução Web:** Automação via Playwright para upload e parametrização no Playground.
5.  **Monitoramento:** Verificação contínua até que o processamento na nuvem seja concluído.
6.  **Conclusão:** Atualização de status, geração de relatórios e limpeza de arquivos temporários.

## 💻 Stack Tecnológica

- **Linguagem:** Python 3.x
- **Framework Web:** FastAPI (Backend)
- **ORM:** SQLAlchemy com Alembic para migrações.
- **Automação Web:** Playwright (Chromium).
- **Processamento de Documentos:** LibreOffice (soffice).
- **Banco de Dados:** SQLite/PostgreSQL (via SQLAlchemy).
- **Interface de Usuário:** Dashboard (public/assets indica presença de um frontend possivelmente em React/Vue, integrado via API).

---
*Este documento serve como guia de referência para o entendimento da estrutura e propósito do Automation HUB.*
