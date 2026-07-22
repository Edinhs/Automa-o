# 📬 Envio Automático de Relatório — Como Funciona (passo a passo)

> Guia rápido e prático de **como o envio automático do relatório está funcionando hoje** no
> Automation HUB. Complementa (não substitui) o `GUIA_POWER_AUTOMATE.md` (guia técnico completo de
> como montar o fluxo no Power Automate) e o `BACKEND_START.md` (contrato de endpoints).
>
> *Última atualização: 2026-07-21.*

---

## 1. Visão geral em 1 minuto

Existem **duas formas** de o relatório sair do HUB e chegar sozinho no Teams, sem ninguém precisar
abrir o dashboard toda semana. Você pode usar uma ou as duas:

| | **Caminho A — Agendamento + pasta + Power Automate** | **Caminho B — PNG automático direto pro Teams** |
|---|---|---|
| **O que envia** | O relatório (XLSX/PDF/CSV) + PDF + imagem-convite (PNG) + um arquivo de instruções | Só a imagem (PNG) mais recente de uma pasta |
| **Quem entrega no Teams** | O **Power Automate** (fluxo configurado uma vez, ver `GUIA_POWER_AUTOMATE.md`) | O **próprio HUB**, via Playwright (sem Power Automate) |
| **Precisa de OneDrive/SharePoint?** | Sim | Não |
| **Onde configura** | Dashboard (aba Relatórios → "Agendar Relatório") + `backend\.env` | Só `backend\.env` |
| **Está ligado por padrão?** | Não (é opt-in por agendamento) | Não (`TEAMS_PNG_DELIVERY_ENABLED=false`) |

Se você já usa o card semanal de adoção no grupo do Teams, é o **Caminho A**. Se você só quer que um
PNG qualquer (gerado por você ou por outro processo) seja postado automaticamente sem depender do
Power Automate, use o **Caminho B**.

---

## 2. Caminho A — Agendamento automático + entrega por pasta (Power Automate)

### Passo 1 — Criar o agendamento no dashboard
1. Abra o dashboard → aba **Relatórios**.
2. Clique em **"Agendar Relatório"**.
3. Preencha o modal:
   - **Tipo do Relatório** — recomendado: **Relatório Simplificado** (é o único formato pensado para o
     card do Teams).
   - **Formato do Arquivo** — XLSX, PDF ou CSV (o HUB sempre gera também um PDF e um PNG junto, para o
     card — isso é automático e independe do formato escolhido aqui).
   - **Frequência** — `once` / `interval` / `daily` / `weekly` / `monthly` (ex.: `weekly`, toda
     segunda-feira).
   - **Data/Hora inicial** — quando a primeira execução deve rodar (fuso de São Paulo).
   - **Idioma** — Português (padrão) ou Inglês.
   - **Marque "Enviar para a pasta de entrega"** — é o interruptor que liga a cópia automática para o
     Power Automate. **Sem marcar essa opção, o relatório é gerado normalmente, mas fica só dentro do
     HUB — nada é copiado para fora, nada chega no Teams sozinho.**
4. Salve. O agendamento aparece na lista de agendamentos, com a data da próxima execução.

### Passo 2 — Configurar a pasta de entrega (uma vez só)
1. Abra `backend\.env` (copie de `backend\.env.example` se ainda não existir).
2. Defina a variável apontando para uma pasta **sincronizada pelo OneDrive/SharePoint** (precisa ser
   uma pasta que sincroniza com a nuvem, não uma pasta local qualquer):
   ```env
   REPORT_DELIVERY_PATH=C:\Users\<voce>\OneDrive - Stellantis\AutomationHUB\reports
   ```
3. Reinicie os serviços para aplicar: `.\restart_services.bat`

> Sem essa variável preenchida, marcar "Enviar para a pasta de entrega" no agendamento não tem efeito
> — o recurso fica desligado (comportamento seguro por padrão, nada muda se você não configurar nada).

### Passo 3 — O que acontece sozinho, no horário agendado
Sem nenhuma ação manual, no horário configurado:
1. O **agendador embutido do backend** (`schedule_runner.py`, rodando em background enquanto o backend
   está de pé) detecta que o agendamento venceu.
2. Gera o relatório automaticamente, consultando os dados de auditoria dos **últimos 30 dias**, no
   idioma configurado.
3. Grava o arquivo em `backend\data\reports\agendados\`.
4. Como a opção **"Enviar para a pasta de entrega"** está marcada, o HUB **copia 4 arquivos** para a
   pasta do `REPORT_DELIVERY_PATH`, todos com o mesmo nome-base:
   - o relatório no formato escolhido (`.xlsx`/`.pdf`/`.csv`),
   - um **PDF** (sempre gerado, mesmo se você escolheu outro formato),
   - um **PNG** (a imagem-convite do card, gerada offline via Chromium),
   - um **`.meta.json`** (o "sidecar" com as instruções — já traz o card pronto e os nomes dos outros
     3 arquivos).
5. O OneDrive sincroniza esses 4 arquivos para a nuvem automaticamente (ícone do OneDrive na bandeja).

### Passo 4 — O Power Automate detecta e posta no Teams
Isso já roda sozinho **depois que o fluxo foi montado uma vez** (passo a passo completo de como criar
esse fluxo está no `GUIA_POWER_AUTOMATE.md`, Parte I):
1. O fluxo do Power Automate está com um gatilho **"quando um arquivo é criado"** apontando para a
   pasta de entrega.
2. Ele espera especificamente o `.meta.json` (é o último arquivo a chegar, então os outros 3 já estão
   prontos quando ele aparece).
3. Lê as instruções do `.meta.json`, gera links de download do PDF e da imagem, monta o card final e
   **posta 1 mensagem** no grupo/canal do Teams: a imagem-convite (tempo economizado + adoção + saúde)
   com os botões **Abrir Playground / Solicitar Acesso / Baixar Relatório (PDF)**.
4. Ninguém precisa abrir o dashboard nem o OneDrive — do agendamento até o Teams é 100% automático.

### Resumo do Caminho A (linha do tempo)
```
Agendamento vence (schedule_runner)
   → gera relatório (XLSX/PDF/CSV) + PDF + PNG + .meta.json
   → (se "Enviar para a pasta de entrega" estiver marcado) copia os 4 arquivos p/ REPORT_DELIVERY_PATH
   → OneDrive sincroniza
   → Power Automate detecta o .meta.json e posta o card no Teams
```

### Alternativa sem Power Automate (envio manual pelo próprio HUB)
Se você não quiser depender do Power Automate, o dashboard também tem, em cada relatório já gerado,
botões manuais de **E-mail** e **Teams** que usam o Microsoft Graph diretamente (precisa configurar
`MS_GRAPH_*` no `.env` — ver `BACKEND_START.md`). Sem isso configurado, o envio simplesmente retorna
"não configurado" sem quebrar nada.

---

## 3. Caminho B — PNG automático direto pro Teams (sem Power Automate)

Esse é o caminho **mais simples e mais automático**: o próprio HUB monitora uma pasta e, quando
encontra um **PNG novo**, ele mesmo abre o navegador (Playwright) e posta o arquivo num chat/canal do
Teams — sem OneDrive, sem SharePoint, sem Power Automate.

### Passo 1 — Ativar no `.env`
Edite `backend\.env` e preencha o bloco (já vem comentado no `.env.example`):
```env
TEAMS_PNG_DELIVERY_ENABLED=true
TEAMS_PNG_WATCH_FOLDER=C:\caminho\para\a\pasta\do\relatorio
TEAMS_PNG_DELIVERY_CHAT_NAME=1:1 Ederson
TEAMS_PNG_DELIVERY_TEXT=
TEAMS_PNG_DELIVERY_MODE=schedule
TEAMS_PNG_DELIVERY_DAY_OF_WEEK=monday
TEAMS_PNG_DELIVERY_TIME=09:00
TEAMS_PNG_DELIVERY_POLL_INTERVAL_SECONDS=300
```

| Variável | O que faz |
|---|---|
| `TEAMS_PNG_DELIVERY_ENABLED` | Liga/desliga a feature inteira (`true`/`false`). |
| `TEAMS_PNG_WATCH_FOLDER` | Pasta onde o PNG aparece. O HUB sempre pega o **mais recente** dela. |
| `TEAMS_PNG_DELIVERY_CHAT_NAME` | Nome exato do chat/canal no Teams Web (vazio = usa o mesmo do relatório simplificado). |
| `TEAMS_PNG_DELIVERY_TEXT` | Texto enviado junto (vazio = mensagem padrão com o nome do arquivo). |
| `TEAMS_PNG_DELIVERY_MODE` | `schedule` (dia/hora fixos) ou `continuous` (verifica a cada N segundos). |
| `TEAMS_PNG_DELIVERY_DAY_OF_WEEK` / `TEAMS_PNG_DELIVERY_TIME` | Usados só no modo `schedule`. |
| `TEAMS_PNG_DELIVERY_POLL_INTERVAL_SECONDS` | Usado só no modo `continuous`. |

### Passo 2 — Reiniciar os dois processos
A feature roda em dois lugares — reinicie ambos:
1. **Backend** (porta 8000) — é quem verifica se está na hora/intervalo certo.
2. **Agente local** (`python -m app.cli.local_agent`) — é quem de fato abre o navegador e envia.

O dashboard (porta 5173) não precisa reiniciar.

### Passo 3 — O que acontece sozinho
1. No modo `schedule`: uma vez por semana, no dia/hora configurados, o HUB olha a pasta.
   No modo `continuous`: a cada N segundos, o dia todo.
2. Ele compara o PNG mais recente da pasta com o **hash (sha256)** do último que já enviou.
3. **Só reenvia se o conteúdo mudou** — renomear o mesmo arquivo não dispara reenvio; gerar um PNG
   diferente (mesmo nome ou não), sim.
4. Se for novo, cria uma tarefa (`deliver_png_teams_playwright`); o agente local abre o Chromium,
   entra no Teams e envia o arquivo para o chat/canal configurado.
5. O hash só é gravado como "já enviado" **depois** da confirmação de sucesso — se falhar, tenta de
   novo (no modo `continuous`, no próximo intervalo; no modo `schedule`, só na próxima semana).
6. O estado fica em `backend\data\teams_png_delivery_state.json`. Não precisa mexer nesse arquivo —
   apagá-lo força o próximo PNG a ser reenviado (funciona como um "reset").

> Guia completo com mais detalhes/exemplos: `PNG_TEAMS_AUTO_DELIVERY.md`.

---

## 4. Como verificar se está funcionando

1. **Agendamento (Caminho A):** aba Relatórios → lista de agendamentos → confira `Próxima execução` e
   `Última execução`. Depois que rodar, confira se apareceram os 4 arquivos na pasta do
   `REPORT_DELIVERY_PATH` (relatório + PDF + PNG + `.meta.json`), e se o card chegou no Teams.
2. **Envio manual de teste (sem esperar o agendamento):** dashboard → Relatórios → gere um relatório
   manualmente e marque a mesma opção de pasta de entrega — testa o mesmo caminho sem esperar o
   cronograma.
3. **PNG automático (Caminho B):** deposite um PNG novo na pasta configurada e, no dia/hora ou
   intervalo definidos, confirme que uma tarefa `deliver_png_teams_playwright` aparece no histórico
   de tarefas do agente e que o arquivo chega no Teams; depositar o mesmo arquivo de novo **não** deve
   reenviar.
4. **Diagnóstico geral:** `GET http://127.0.0.1:8000/api/diagnostics` — confirma que o backend e o
   agente local estão de pé (heartbeat recente). Sem o agente rodando, nenhuma tarefa Playwright
   (upload, monitor, envio de PNG) é executada.
5. **Se nada chegar no Teams:** confira, nesta ordem — (a) o agendamento está `active` e com
   "Enviar para a pasta de entrega" marcado; (b) `REPORT_DELIVERY_PATH` está preenchido e é uma pasta
   sincronizada; (c) o OneDrive terminou de sincronizar os 4 arquivos; (d) o fluxo do Power Automate
   está **ligado** (não em modo rascunho) — ver `GUIA_POWER_AUTOMATE.md`, seção de troubleshooting.

---

## 5. Perguntas rápidas

**Preciso configurar os dois caminhos?** Não — são independentes. A maioria dos casos usa só o
Caminho A (card semanal completo com horas economizadas/adoção/saúde).

**O relatório é enviado por e-mail automaticamente também?** Só se você configurar `MS_GRAPH_*` e
integrar via automação própria — hoje o envio de e-mail (`POST /api/integrations/reports/{id}/email`)
é acionado pelo botão **E-mail** no dashboard, não é automático por agendamento.

**Onde fica o relatório se eu não marcar "Enviar para a pasta de entrega"?** Só em
`backend\data\reports\agendados\` — continua disponível para download manual pelo dashboard, mas
nada é copiado para fora nem enviado ao Teams sozinho.

**Documentos relacionados:** [`GUIA_POWER_AUTOMATE.md`](./GUIA_POWER_AUTOMATE.md) (passo a passo
completo de como montar o fluxo no Power Automate) · [`PNG_TEAMS_AUTO_DELIVERY.md`](./PNG_TEAMS_AUTO_DELIVERY.md)
(detalhes do Caminho B) · [`BACKEND_START.md`](./BACKEND_START.md) (variáveis e endpoints) ·
[`SPECS.md`](./SPECS.md) (contrato técnico do scheduler e das integrações).
