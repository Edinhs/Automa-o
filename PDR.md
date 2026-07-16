# 📄 PDR — Documento de Produto e Requisitos · Stellantis Automation HUB

> **Product / Design Requirements (PDR)** · **Versão:** 1.0 · **Data:** 2026-07-15
> **Autor:** Claude Code (Opus 4.8) · **Dono do produto:** Ederson Siqueira (TA25413)
> **Documentos irmãos:** [`Briefing.md`](./Briefing.md) (executivo) · [`SPECS.md`](./SPECS.md) (técnico) ·
> [`GUIA_POWER_AUTOMATE.md`](./GUIA_POWER_AUTOMATE.md) (entrega Teams).

---

## 1. Sumário executivo

O **Automation HUB** devolve tempo de engenharia eliminando o trabalho manual e repetitivo de
**encontrar arquivos/SPECs, subir a um workspace seguro do Playground e acompanhar o processamento**.
O engenheiro deixa de operar o navegador; a HUB detecta os arquivos na pasta, envia em lotes, monitora
o status, converte e reenvia o que falha, e reporta o resultado — com rastreabilidade completa e um
convite de adoção entregue no Teams.

**Proposta de valor em uma frase:** *"Seu ambiente já está pronto — entre e crie seu agente."*

---

## 2. Problema

1. **Trabalho manual repetitivo e caro.** Subir dezenas/centenas de documentos ao Playground é lento,
   sujeito a erro e desestimula a adoção da plataforma.
2. **Falhas silenciosas e retrabalho.** Uploads que falham no processamento exigem reconversão manual
   (para PDF) e reenvio, sem trilha clara do que aconteceu.
3. **Ambiente corporativo restritivo.** Rede offline, proxy/cert corporativo bloqueando downloads, SSO
   obrigatório — soluções SaaS ou que dependem de internet não servem.
4. **Baixa visibilidade de adoção.** Falta uma métrica simples ("quantas horas poupamos?", "quantos
   engenheiros já têm acesso?") para justificar e impulsionar o uso.

---

## 3. Personas e stakeholders

| Persona | Necessidade principal | Como a HUB atende |
| :--- | :--- | :--- |
| **Operador/Owner (admin local)** | Configurar automações, disparar/agendar, resolver erros, gerar relatórios. | Dashboard completo; ação "Resolvido"; agendador; relatórios. |
| **Engenheiro (usuário final)** | Ter seus arquivos no workspace sem operar o navegador; pedir acesso. | Ingestão automática; card de adoção no Teams com "Solicitar acesso". |
| **Gestor/Liderança** | Enxergar valor gerado (horas, adoção, saúde). | Card semanal (imagem) + Relatório Simplificado. |
| **Agente de IA / desenvolvedor** | Evoluir o sistema com contexto e sem conflito. | `CLAUDE.md`, `SPECS.md`, `COMUNICACAO_AGENTES.md`, subagentes `.claude/agents/`. |

---

## 4. Objetivos e não-objetivos

### 4.1 Objetivos
- **O1** — Zero interação de navegador para o caminho feliz de ingestão.
- **O2** — Nenhuma duplicata no workspace, mesmo com falhas parciais, reenvios e execuções concorrentes.
- **O3** — Recuperação automática de erros de processamento (conversão PDF + reenvio) e de sessão (login).
- **O4** — Operação 100% offline no notebook corporativo (Chromium embarcado, sem dependência de internet).
- **O5** — Rastreabilidade total: logs, metadados, screenshots de incidente, relatórios auditáveis.
- **O6** — Entrega de valor visível (card de adoção no Teams) sem exigir infraestrutura nova.

### 4.2 Não-objetivos (fora de escopo)
- **N1** — Não substitui o Playground nem cria/gerencia os agentes de IA lá dentro.
- **N2** — Não é multiusuário concorrente em escala web (deploy single-host; ver §8, riscos).
- **N3** — Não faz OCR nem transformação de conteúdo dos documentos (só conversão de formato p/ PDF).
- **N4** — **Automações Personalizadas / IPC Workspace Updater** foram **removidas** (2026-07-07, a pedido
  do dono) e **não serão mais produzidas**.
- **N5** — Relatórios automáticos de *monitoramento de pasta* estão desativados (só geração manual/agendada).

---

## 5. Requisitos funcionais

> Convenção: **RF-n**. Status reflete o código atual.

| ID | Requisito | Status |
| :--- | :--- | :--- |
| **RF-01** | Monitorar uma pasta local e detectar arquivos novos/alterados por mtime + `content_sha256`. | ✅ Implementado |
| **RF-02** | Deduplicar entre execuções (baseline persistente); classificar `new`/`updated`/`audit_duplicate`. | ✅ |
| **RF-03** | "Execução Completa" (`full_execution`) reenvia todos os arquivos ativos. | ✅ |
| **RF-04** | Enviar ao workspace em **lotes** com **checkpoint por lote** (idempotente). | ✅ |
| **RF-05** | Confirmar upload apenas por sinal real de rede/UI (sem falso-positivo). | ✅ |
| **RF-06** | Monitorar status no Playground em **passo único** após o envio. | ✅ |
| **RF-07** | Converter para PDF e **reenviar** arquivos que falharam, em lotes, sem novo monitoramento. | ✅ |
| **RF-08** | Recuperar login: headless → reabrir visível e repetir a tarefa uma vez, sem falhar. | ✅ |
| **RF-09** | Criar workspace, adicionar usuário e conectar sessão via tarefas dedicadas. | ✅ |
| **RF-10** | Ação **"Resolvido"** por arquivo e por automação; recalcular status pela fonte única. | ✅ |
| **RF-11** | Agendar automações e relatórios (`once/interval/daily/weekly/monthly`). | ✅ |
| **RF-12** | Gerar relatórios (Geral/Simplificado/…) em XLSX/PDF/CSV; **1 run = 1 execução**. | ✅ |
| **RF-13** | Entregar o **Relatório Simplificado** na pasta de pickup (Power Automate) — opt-in por agendamento. | ✅ |
| **RF-14** | Card semanal no Teams como **imagem** fiel + botões (Abrir Playground / Solicitar Acesso / PDF). | ✅ |
| **RF-15** | Enviar relatório por **E-mail/Teams** via MS Graph (com fallback gracioso `not_configured`). | ✅ |
| **RF-16** | Isolamento por ambiente (**operacional × desenvolvedor**) em banco, caminhos e agente. | ✅ |
| **RF-17** | Dashboard: automações, workspaces, arquivos (auditoria), histórico, logs, lixeira, perfil. | ✅ |
| **RF-18** | Abrir a pasta do arquivo no Windows Explorer a partir da auditoria ("Pasta"). | ✅ |
| **RF-19** | Auth desabilitável (`AUTH_DISABLED`) para deploy offline sem login; JWT preservado. | ✅ |

---

## 6. Requisitos não-funcionais

| ID | Requisito | Como é atendido |
| :--- | :--- | :--- |
| **RNF-01 · Offline** | Operar sem internet no notebook corporativo. | Chromium 1217 embarcado (`PLAYWRIGHT_BROWSERS_PATH`); sem CDNs. |
| **RNF-02 · Resiliência** | Falha parcial nunca gera duplicata nem estado sujo. | Checkpoints por lote; delete verificado por F5; `get_db` rollback-on-exception. |
| **RNF-03 · Idempotência** | Reprocessos e cliques repetidos são seguros. | `batch-complete` idempotente; claim atômico de tarefa. |
| **RNF-04 · Rastreabilidade** | Toda ação relevante é auditável. | `execution_logs` estruturados; metadados; screenshots de incidente. |
| **RNF-05 · Segurança** | Segredos não vazam; token do agente é comparado em tempo constante. | `sanitize_for_storage`; `compare_digest`; bcrypt. |
| **RNF-06 · Portabilidade de dados** | Trocar SQLite→PostgreSQL sem mudar código. | Só `DATABASE_URL`; PRAGMAs só no ramo SQLite. |
| **RNF-07 · Não-destrutivo** | Preservar arquivos/artefatos para auditoria. | Staging temp nunca auto-deletado; soft-delete em todas as tabelas. |
| **RNF-08 · Fuso** | Horários corretos para o time (São Paulo). | `core/timezone.py` em todo o scheduler/relatório. |

---

## 7. Fluxos-chave (nível produto)

1. **Ingestão agendada:** scheduler dispara → agente escaneia/deduplica/copia p/ staging → login (se
   preciso) → upload em lotes → monitoramento único → conversão+reenvio dos que falharam → status final →
   (opcional) relatório e card no Teams.
2. **Resolução de erro:** arquivo em `manual_review`/`failed` → operador clica **"Resolvido"** →
   `recalculate_automation_status` devolve a automação para `active`/`completed`.
3. **Adoção:** card semanal chega no Teams com horas economizadas, engenheiros com acesso, SPECs prontas
   e saúde; engenheiro toca **"Solicitar acesso"** (formulário Power Automate → lista SharePoint).

---

## 8. Riscos e mitigações

| Risco | Impacto | Mitigação atual / recomendada |
| :--- | :--- | :--- |
| **UI do Playground muda** (RPA frágil) | Alto | Seletores multilíngues + `get_by_role`; `UIChangedError`; edição cirúrgica. |
| **Custo de finalização cresce com o histórico** (`automation_id` em JSON, não coluna) | Médio | **Recomendação:** promover `automation_id` a coluna indexada em `agent_tasks` (ver `SPECS.md` §12, achado #1). |
| **Match de arquivo por nome global** sem escopo de automação | Baixo-Médio | Priorizar `file_id`; escopar fallback por nome à automação. |
| **MS Graph indisponível/403 em canal** | Médio | Fallback `not_configured`; entrega por pasta (Power Automate) + Teams deep link. |
| **Deprecação do `on_event` do FastAPI** | Baixo | Migrar para `lifespan`. |
| **Deriva de documentação** (IPC removido, tests como scripts) | Baixo | Reconciliar `CLAUDE.md`/`RELEASE_POLICY.md`. |

---

## 9. Métricas de sucesso

- **Adoção:** nº de engenheiros distintos (`network_id`) com acesso concedido (tarefas
  `add_playground_user_to_workspace` concluídas), tendência semanal.
- **Valor:** horas economizadas = arquivos enviados × `REPORT_MINUTES_PER_FILE` (semana + acumulado).
- **Qualidade:** taxa de arquivos que chegam a `ready` sem intervenção manual; nº de itens em
  `manual_review`/`failed` por run.
- **Confiabilidade:** zero duplicatas no workspace; zero instâncias órfãs de Office pós-conversão.

---

## 10. Roadmap sugerido (backlog priorizado)

> Não comprometido — sugestões derivadas da revisão de código. Aprovação do dono necessária.

1. **[Dívida arquitetural]** Coluna `automation_id` indexada em `agent_tasks` + backfill (resolve o
   achado #1; melhora finalização, histórico e relatórios).
2. **[Correção defensiva]** Escopar o match de arquivo por nome ao `automation_id` (achado #2).
3. **[Limpeza]** Remover ramo morto em `update_files_from_result` (achado #3).
4. **[Modernização]** Migrar `on_event` → `lifespan` (achado #4).
5. **[Documentação]** Reconciliar `CLAUDE.md`/`RELEASE_POLICY.md` (IPC removido; tests como scripts).
6. **[Observabilidade]** Painel de adoção/valor no próprio dashboard (hoje só via card/Relatório).

---

## 11. Decisões de produto registradas (ADR resumido)

| Data | Decisão | Motivo |
| :--- | :--- | :--- |
| 2026-07-07 | **Remover** a feature IPC / Automações Personalizadas. | Pedido do dono; não será mais produzida (N4). |
| 2026-07-01 | `REPORTS_PATH` volta para `backend/data/reports`; entrega vira **opt-in**. | Evitar cópia automática indesejada a cada relatório. |
| 2026-07-07 | Entrega na pasta só do **Relatório Simplificado**. | É o único consumido pelo fluxo Teams/Power Automate. |
| 2026-06/07 | Card do Teams: de *data dump* → **convite de adoção** → **imagem fiel**. | Engajamento; foco em valor, não em status cru. |
| — | `AUTH_DISABLED=true` no release. | Deploy offline sem login; JWT preservado para o futuro. |
