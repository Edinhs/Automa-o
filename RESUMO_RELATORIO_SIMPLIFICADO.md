# Resumo da Modificação — Relatório Simplificado

> Documento de handoff para outra IA / desenvolvedor entender, em contexto, a feature
> **"Relatório Simplificado"** adicionada ao Stellantis Automation HUB.
> Data: 2026-06-22.

## 1. Objetivo

Adicionar um novo tipo de relatório chamado **"Relatório Simplificado"** que reproduz uma
planilha de acompanhamento de workspaces (originalmente mantida à mão no SharePoint:
`Status SPEC Playground.xlsx`). O relatório lista **uma linha por workspace** com as colunas:

`SPEC | PORCENTAGEM | STATUS | OBSERVAÇÃO | ULTIMA ATUALIZAÇÃO | ARQUIVOS`

Decisões do usuário:
- **Onde:** novo tipo selecionável **E** também incluído como aba/seção dentro do "Relatório Geral".
- **Mapeamento:** automático/completo, derivado do estado real dos arquivos no HUB.

## 2. Arquivos modificados

| Arquivo | Camada | Mudança |
|---|---|---|
| `backend/app/routers/reports.py` | Backend (FastAPI) | Novo bloco + tipo de relatório |
| `dist/assets/index-BBcj3Zw-.js` | Frontend (bundle minificado) | Tipo adicionado ao seletor + i18n |
| `dist/assets/index-BBcj3Zw-.js.bak-20260622-142632` | — | Backup automático do bundle (padrão do repo) |

Nenhum outro arquivo de domínio foi tocado. Sem migração de banco (não há coluna nova; o
relatório só lê dados existentes).

## 3. Backend — `backend/app/routers/reports.py`

### 3.1 Novo builder `block_simplificado(db, filters, names)`
Inserido imediatamente antes do dicionário `BLOCK_BUILDERS`. Segue o mesmo contrato dos demais
builders: retorna um `ReportSection(key, titulo, headers, rows)`.

- Itera `Workspace` com `is_deleted == False`, respeitando `within_period(created_at, ...)` e
  `filters["workspace_id"]` quando presente. Ordena por `Workspace.id` ascendente.
- Carrega todos os `WorkspaceFile` ativos dos workspaces selecionados em **uma única query**
  (`workspace_id.in_(...)`, sem N+1), agrupando num dict por `workspace_id`.
- Headers (ordem exata): `["SPEC", "PORCENTAGEM", "STATUS", "OBSERVAÇÃO", "ULTIMA ATUALIZAÇÃO", "ARQUIVOS"]`
- Cada linha: `[ws.name, percentage, status, observation, fmt_utc(ws.updated_at), total_arquivos]`

### 3.2 Regra de mapeamento automático (estado dos arquivos → %/status/observação)

| Condição (sobre os WorkspaceFile do workspace) | PORCENTAGEM | STATUS | OBSERVAÇÃO |
|---|---|---|---|
| `total == 0` (nenhum arquivo) | `10%` | `PROGRESSO` | `WORKSPACE CRIADO` |
| Existe arquivo `failed`/`manual_review`/`pending_retry` e nem todos prontos | `90%` | `ERRO` | `Tratamento de erros` |
| Todos prontos (`status == "ready"` ou `playground_status == "Ready"`) | `100%` | `COMPLETO` | `Disponivel no Playground` |
| Todos enviados (`status` em `{uploaded, ready}`), nem todos prontos, sem erro | `70%` | `PROGRESSO` | `Arquivos enviados` |
| Algum enviado mas ainda há `pending` (ou só pending), sem erro | `40%` | `PROGRESSO` | `Enviando para Playground` |

Notas de contrato:
- **PORCENTAGEM é serializada como string `"NN%"`** (ex.: `"10%"`, `"70%"`, `"100%"`), não como
  número fracionário. O frontend recebe a string pronta para exibição.
- `ARQUIVOS` é a contagem total de arquivos ativos do workspace (inteiro).
- `ULTIMA ATUALIZAÇÃO` usa `fmt_utc(ws.updated_at)`, no mesmo formato dos outros relatórios.

### 3.3 Registros nos dicionários
- `REPORT_BLOCKS`: adicionado `"simplificado": "Relatório Simplificado"`.
- `BLOCK_BUILDERS`: adicionado `"simplificado": block_simplificado`.
- `REPORT_TYPES`: adicionado `"relatorio simplificado": ("Relatório Simplificado", ["simplificado"])`.
- `REPORT_TYPES["relatorio geral"]`: `"simplificado"` adicionado **ao final** da lista de blocos
  (faz o Relatório Geral incluir uma aba "Relatório Simplificado").
- Mensagem de erro 422 em `parse_report_type` atualizada para citar o novo tipo (cosmético, sem
  mudança de contrato).

## 4. Frontend — `dist/assets/index-BBcj3Zw-.js`

O bundle é minificado e **editado à mão** (a fonte React não está no repo). Os tipos de relatório
são **hardcoded** (não vêm de endpoint).

- Array de tipos `q2`: `"Relatório Simplificado"` adicionado ao final, antes do `]`.
- Mapas i18n PT→EN (2 mapas no bundle): adicionada a entrada
  `"Relatório Simplificado":"Simplified Report"` em ambos.
- Validação: `node --check` sobre cópia `.mjs` → OK (sintaxe minificada preservada).

## 5. Como acionar

- **Dashboard:** aba Relatórios → selecionar tipo "Relatório Simplificado" → gerar (XLSX/PDF/CSV).
- **API:** gerar relatório passando `report_type = "Relatório Simplificado"`
  (chave normalizada interna: `relatorio simplificado`).
- O relatório também aparece automaticamente como uma aba/seção dentro do **Relatório Geral**.

## 6. Verificação executada (gate)

- `python -m compileall backend/app` → limpo (exit 0).
- `node --check` no bundle → OK.
- **Smoke test** chamando `block_simplificado` direto contra um SQLite temporário
  (`Base.metadata.create_all`), cobrindo os 5 ramos da regra. Saída confirmada:

| SPEC | PORCENTAGEM | STATUS | OBSERVAÇÃO | ARQUIVOS |
|---|---|---|---|---|
| WS-Vazio (0 arquivos) | 10% | PROGRESSO | WORKSPACE CRIADO | 0 |
| WS-Completo (todos ready) | 100% | COMPLETO | Disponivel no Playground | 2 |
| WS-ComErro (1 ready + 1 failed) | 90% | ERRO | Tratamento de erros | 2 |
| WS-Enviados (todos uploaded) | 70% | PROGRESSO | Arquivos enviados | 2 |
| WS-Parcial (1 uploaded + 1 pending) | 40% | PROGRESSO | Enviando para Playground | 2 |

## 7. Pendência operacional

O backend de produção só passa a servir o novo tipo **após reiniciar os serviços**
(`restart_services.bat`). Enquanto o processo antigo estiver no ar, a rota mantém o comportamento
anterior (e pode retornar 404/422 para o novo tipo). Limpar `__pycache__` se necessário.

## 8. Pontos de extensão futuros (não feitos)

- Sincronizar este relatório de volta para a planilha do SharePoint (`Status SPEC Playground.xlsx`)
  automaticamente.
- Permitir agendamento do "Relatório Simplificado" (o agendador já suporta `report_type`; basta
  selecionar o novo tipo no modal de agendamento).
- Ajustar os textos de OBSERVAÇÃO/limiares de % caso a regra de negócio evolua (centralizados em
  `block_simplificado`).
