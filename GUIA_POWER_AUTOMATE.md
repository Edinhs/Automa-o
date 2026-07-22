# Guia Power Automate — Automation HUB no Teams (unificado)

| | |
|---|---|
| **Versão** | 2.0 |
| **Data de revisão** | 03/07/2026 |
| **Área dona / responsável** | Infotainment — Automation HUB |
| **Classificação** | Interno — Stellantis |
| **Próxima revisão** | 03/01/2027 (ou a cada mudança de fluxo) |

> **Guia único.** Reúne, num só lugar e **do zero**, todos os fluxos do Power Automate do Automation HUB. Substitui os antigos `POWER_AUTOMATE.md`, `GUIA_FLUXO_POWER_AUTOMATE.md`, `GUIA_TEAMS_CARD_POWER_AUTOMATE.md` e `GUIA_TEAMS_SOLICITACAO_ACESSO.md`.
>
> **Power Automate em inglês:** os nomes de ações aparecem **em inglês** (como na sua tela) e as explicações em português. Os termos em inglês entre parênteses ajudam a localizar.

O que dá para montar (cada parte é independente):
1. **Parte I — Convite no Teams:** quando o HUB gera o relatório semanal, o fluxo posta **1 card** no grupo: uma **imagem (PNG) de CONVITE** — a manchete "seu ambiente já está pronto, entre e crie seu agente", o **tempo devolvido ao time** (semana + acumulado), a **adoção** (engenheiros usando / SPECs prontas) e a **saúde em 1 linha** — com os botões **Abrir Playground / Solicitar Acesso / Baixar Relatório (PDF)** (Apêndice H). O card **não** traz contagem de arquivos, tabela SPEC-por-SPEC nem status cru de workspace: esse detalhe vive no PDF ("Baixar Relatório").
2. **Parte II — Convite "Solicitar acesso" (legado/fallback):** versão antiga, de quando o botão de acesso ia numa mensagem separada *depois* do card. Hoje o botão já mora dentro do card (Apêndice H) — mantida só como referência.
3. **Parte III — Formulário de Solicitação de Acesso:** self-service (Adaptive Card → **Lista do SharePoint** + aviso ao aprovador), sem mensagem manual.
4. **Parte IV — Alternativas:** entrega por **e-mail**, por **canal do Teams**, ou o **botão manual** do dashboard (sem Power Automate).
5. **Parte V — Automação "PNG → Teams" (sem Power Automate):** o próprio HUB, via Playwright, detecta um PNG **novo** numa pasta vigiada e o envia **direto** para um chat/grupo do Teams — de forma **invisível** (headless), reutilizando a **mesma conta Microsoft/SSO já usada no Playground**; só abre uma janela visível quando um login manual é realmente necessário.

```
Parte I:   HUB gera relatório ─▶ pasta OneDrive (relatório + .pdf + .png + .meta.json) ─▶ Power Automate
              1) share link do PDF + share link (direto) da imagem
              2) posta 1 card = imagem-CONVITE + 3 botões (Playground / Acesso / PDF)
Parte II:  (legado) mensagem separada de "Solicitar acesso" pós-card — não é mais necessária
Parte III: colaborador roda o fluxo ─▶ Adaptive Card (form) ─▶ Lista do SharePoint + aviso ao aprovador
Parte V:   pasta vigiada (TEAMS_PNG_WATCH_FOLDER) ─▶ HUB detecta PNG novo (sha256) ─▶
              Playwright headless entra no Teams Web (sessão já logada) ─▶ envia o PNG ao chat
```

---

## Parte 0 — Pré-requisitos e glossário

### Pré-requisitos
- [ ] Conta corporativa Microsoft 365 com **Power Automate** (https://make.powerautomate.com) e **Microsoft Teams**.
- [ ] Para a **Parte I**: **OneDrive for Business** sincronizando uma pasta local (ícone do OneDrive na bandeja; a pasta aparece no Explorer) e acesso ao `backend\.env` do HUB.
- [ ] Para a **Parte III**: permissão para **criar uma Lista** num site do SharePoint (ou numa Equipe do Teams).
- [ ] Permissão de escrita no **chat de grupo / canal** de destino no Teams.

### 📖 Glossário (leia 1 minuto — facilita tudo)
- **Flow / Fluxo:** a automação que você monta (uma sequência de passos).
- **Trigger / Gatilho:** o **primeiro** passo (o "start"). Ex.: "quando um arquivo novo aparece na pasta" (Parte I) ou "Manually trigger a flow" (Parte III).
- **Action / Ação:** cada passo depois do gatilho (ler arquivo, postar no Teams, criar item, etc.).
- **Dynamic content / Conteúdo dinâmico:** "etiquetas" azuis que carregam dados do passo anterior (ex.: *attachment_file*, *idrede*). Você **clica** para inserir — não digita.
- **Expression / Expressão:** uma "fórmula" (ex.: `body('Parse_JSON')?['attachment_file']`). Vai na aba **Expression** (fx) do seletor de conteúdo.
- **`.meta.json` (sidecar):** o arquivo de "instruções" que dispara e alimenta o fluxo da Parte I — já vem com o **card pronto** e os nomes dos outros arquivos.
- **Adaptive Card:** o formato do "card" visual do Teams. Na Parte I o HUB entrega o card **pronto**; na Parte III o card é um **formulário** (`Input.Text` + `Action.Submit`).
- **SPEC:** a especificação técnica de um projeto/veículo (o conjunto de documentos daquele escopo). No HUB, cada SPEC corresponde a **um workspace** no Playground onde o agente atua.
- **`responder`:** saída da ação de formulário (Parte III) que diz **quem** clicou em Enviar (nome + e-mail) — é como sabemos o solicitante sem pedir login.
- **Run-only:** modo de compartilhar um fluxo para que outras pessoas só possam **executá-lo** (não editar).

---

# Parte I — Fluxo do Convite no Teams (card)

**Resultado:** toda vez que o HUB **gera o relatório semanal**, o fluxo posta, no mesmo grupo, **1 card de CONVITE**: uma **imagem (PNG)** com a manchete "seu ambiente já está pronto — entre e crie seu agente", o **tempo devolvido ao time** (semana + acumulado), a **adoção** (engenheiros usando / SPECs prontas) e a **saúde em 1 linha** — com os botões **Abrir Playground**, **Solicitar Acesso** e **Baixar Relatório (PDF)**.

> **Por que convite, e não status?** O objetivo nº 1 é fazer o engenheiro **entrar e usar** a ferramenta. O gancho é devolver tempo: ele não precisa mais baixar a SPEC, subir no workspace seguro e montar o ambiente — isso já está pronto. Por isso a manchete convida (não "veja o status") e as horas economizadas entram logo abaixo como **prova de valor** (para liderança que lê o mesmo grupo). Contagem de arquivos, tabela SPEC-por-SPEC e status cru de workspace **saíram** do card — ficam no PDF.

### Como funciona (em 1 parágrafo)
Quando o HUB gera o relatório semanal, ele grava numa pasta sincronizada com o OneDrive: (1) o relatório no formato escolhido, (2) um **PDF** (para baixar), (3) um **PNG** (a imagem-convite) e (4) um **`.meta.json`** (o sidecar) — que já vem com o **card pronto** e os nomes dos outros arquivos. O fluxo "acorda" quando o `.meta.json` aparece, lê as instruções, gera **links de download** (PDF + imagem direta), encaixa os dois no card e **posta o card** no chat de grupo.

## I.0 — Preparação (fazer uma vez)

### Apontar a pasta de entrega no HUB
1. Abra `backend\.env` (se não existir, copie de `backend\.env.example`).
2. Defina uma pasta **dentro do OneDrive corporativo sincronizado**:
   ```
   REPORT_DELIVERY_PATH=C:\Users\<voce>\OneDrive - Stellantis\AutomationHUB\reports
   ```
   > Tem que ser uma pasta que o OneDrive **sincroniza** (ícone do OneDrive). Pasta local "pura" não funciona no fluxo de nuvem. Vazio = recurso desligado (padrão).
3. Reinicie os serviços: `.\restart_services.bat`

### Gerar um relatório de teste
1. No dashboard: **Relatórios** → gere um relatório (de preferência **Relatório Simplificado**).
2. Na pasta do OneDrive devem aparecer **3 arquivos** com o mesmo nome-base, por ex.:
   - `relatorio_simplificado_20260624_143022.xlsx` (o relatório)
   - `relatorio_simplificado_20260624_143022.pdf` (o PDF)
   - `relatorio_simplificado_20260624_143022.meta.json` (as instruções)
3. Espere o OneDrive **sincronizar** (check verde "Disponível no dispositivo"). Só depois do sync o Power Automate enxerga.
4. **Guarde** o conteúdo do `.meta.json` (abra no Bloco de Notas e copie tudo) — você vai usá-lo na Parte I.3.

> **Anote o caminho da pasta dentro do OneDrive**, sem a parte "OneDrive - Stellantis". Ex.: se a pasta é `OneDrive - Stellantis\AutomationHUB\reports`, o caminho do Power Automate é **`/AutomationHUB/reports`**. Você precisa dele na I.4.

## I.1 — Criar o fluxo e o gatilho
1. Acesse **https://make.powerautomate.com** (conta corporativa).
2. Menu esquerdo → **Create** → **Automated cloud flow**.
3. **Flow name:** `HUB - Relatório no Teams`.
4. Em **"Choose your flow's trigger"**, busque **OneDrive for Business** → **"When a file is created"** → **Create**.
5. No card do gatilho, em **Folder**, navegue até a sua pasta de entrega (`AutomationHUB/reports`).

## I.2 — Condição: rodar só quando for o `.meta.json`
O HUB grava 3 arquivos, mas só queremos rodar **uma vez** — quando o **sidecar** chega (é o último a ser escrito, então PDF e relatório já existem).
1. **+ New step** → **Control** → **Condition**.
2. **Caixa da esquerda:** clique → aba **Expression** (fx) → cole **exatamente**:
   ```
   triggerOutputs()?['headers']?['x-ms-file-name']
   ```
3. **Operador:** **contains**. · **Caixa da direita:** `meta`
4. Todo o resto vai dentro do **If yes**. Deixe **If no** vazio.

> **⚠️ Não use o chip "File name" nem o valor `.meta.json`.**
> - O chip **"File name"** aponta para `x-ms-file-name-encoded`, que vem **codificado** (o ponto vira `%2E`) — `contains` nunca bate. Use a expressão do nome **legível** acima.
> - O OneDrive ainda **corta a última extensão** (`..._.meta.json` → `..._.meta`). Por isso comparamos com **`meta`** (sem ponto): funciona com ou sem o corte e sobrevive a qualquer codificação.
> - **É seguro:** só o sidecar tem "meta" no nome; o `.pdf`, o `.xlsx`, o `.csv` e o `.json` do relatório não têm.

## I.3 — Ler as instruções do sidecar (Parse JSON)
Dentro do **If yes**:
1. **Add an action** → **Parse JSON** (em *Data Operations*).
2. **Content:** aba **Expression** (fx) → cole **exatamente**:
   ```
   base64ToString(triggerBody()?['$content'])
   ```
   > ⚠️ **Não use o chip "File content".** O OneDrive entrega o conteúdo como **binário** (`application/octet-stream`) e o Parse JSON dá erro *"a propriedade 'content' deve ser do tipo JSON"*. A expressão acima **decodifica** o binário em texto JSON.
3. **Schema:** **Generate from sample** → cole o conteúdo do seu `.meta.json` real (guardado na I.0) → **Done**. *(Se der erro, cole o schema do **Apêndice B**.)*

A partir daqui você tem conteúdos dinâmicos como **attachment_file**, **adaptive_card**, **download_url_placeholder**.

## I.4 — Gerar os links de download (PDF + imagem) (4 ações)

O card semanal é **uma imagem (PNG) de convite + botões**. Por isso o fluxo precisa de **dois**
links de compartilhamento: o do **PDF** (botão "Baixar Relatório (PDF)") e o da **imagem** (que aparece
no corpo do card). Renomeie as ações como abaixo para não confundir os dois "Create share link".

### I.4.1 Achar o PDF pelo nome
1. **Add an action** → **OneDrive for Business** → **"Get file metadata using path"** → renomeie para **`Meta_PDF`** (⋯ → Rename).
2. **File path:** parte fixa da pasta + o dinâmico **attachment_file**:
   ```
   /AutomationHUB/reports/@{body('Parse_JSON')?['attachment_file']}
   ```
   > Troque `/AutomationHUB/reports/` pelo **seu** caminho (anotado na I.0).

### I.4.2 Criar o link do PDF
1. **Add an action** → **OneDrive for Business** → **"Create share link"** → renomeie para **`Link_PDF`**.
2. **File:** **Id** (saída de `Meta_PDF`). · **Link type:** **View**. · **Link scope:** **Organization** (padrão corporativo).
   > 🔒 **Use `Organization`, não `Anyone`.** O PDF é o relatório completo (dado interno). Link "Anyone" é **anônimo** e costuma ser bloqueado pela política de DLP da Stellantis — só use "Anyone" como **exceção aprovada pela Segurança da Informação**.

### I.4.3 Achar a imagem (PNG) pelo nome
1. **Add an action** → **OneDrive for Business** → **"Get file metadata using path"** → renomeie para **`Meta_Imagem`**.
2. **File path:** parte fixa + o dinâmico **image_file**:
   ```
   /AutomationHUB/reports/@{body('Parse_JSON')?['image_file']}
   ```

### I.4.4 Criar o link da imagem (precisa ser DIRETO)
1. **Add an action** → **OneDrive for Business** → **"Create share link"** → renomeie para **`Link_Imagem`**.
2. **File:** **Id** (saída de `Meta_Imagem`). · **Link type:** **View**. · **Link scope:** **Organization** (padrão corporativo).

> 🔒 **Padrão `Organization` — evite `Anyone`.** A imagem-convite é conteúdo interno; um link anônimo é
> vetor de vazamento e normalmente barrado pelo DLP. **Se** a imagem não renderizar no Teams com
> `Organization` (o Flow bot precisa dos BYTES do PNG, não de uma página de visualização — por isso a I.5
> acrescenta **`&download=1`**), a saída corporativamente correta é o **fallback do PDF** (I.9), **não**
> abrir o link como "Anyone". Só use "Anyone" com **aprovação da Segurança da Informação**.

## I.5 — Encaixar os links no card (1 passo)
O card vem com **dois placeholders**: `https://hub-report-download.invalid` (botão do PDF) e
`https://hub-report-image.invalid` (a imagem). Troque os dois de uma vez, com **`replace` aninhado**:
1. **Add an action** → **Compose** (em *Data Operations*) → renomeie para **`Card final`** (⋯ → Rename).
2. **Inputs:** aba **Expression** → cole **exatamente**:
   ```
   replace(replace(string(body('Parse_JSON')?['adaptive_card']), body('Parse_JSON')?['download_url_placeholder'], body('Link_PDF')?['webUrl']), body('Parse_JSON')?['image_url_placeholder'], concat(body('Link_Imagem')?['webUrl'], '&download=1'))
   ```
3. **OK / Add**.

> ⚠️ **O `webUrl` fica em `['webUrl']` (no topo), não em `['link']['webUrl']`.** Caminho errado → `replace`
> recebe **Null** e falha. Se vier vazio, abra a ação numa execução → **Show raw outputs** e use o nome exato do campo.
> O **`&download=1`** faz a URL devolver os **bytes** da imagem (necessário p/ o Teams exibir); se o seu
> tenant já servir o link inline, pode usar só `body('Link_Imagem')?['webUrl']` sem o `concat`.
> Se os nomes das suas ações diferem, ajuste dentro do `body('...')` trocando **espaços por `_`**.

## I.6 — (removido) Mensagem de boas-vindas
> **Não é mais necessária.** O convite ao Playground agora faz parte do **próprio card-imagem** — o
> poster já traz a saudação "👋 Olá, time Stellantis!" e o painel do **GenAI Playground**. O fluxo posta
> **um único card**: a imagem-convite + os botões. **Pule direto para a I.7.**

## I.7 — Postar o card no chat de grupo
1. **Add an action** → **Microsoft Teams** → **"Post card in a chat or channel"**.
   > ⚠️ **NÃO** use **"Post adaptive card and wait for a response"** aqui: ela trava o fluxo esperando um formulário, e o card de relatório só tem botões de link.
2. **Post as:** **Flow bot**. · **Post in:** **Group chat** → selecione o grupo.
   > Se o grupo não aparecer, mande qualquer mensagem nele pelo Teams e reabra a lista.
3. **Adaptive Card:** conteúdo dinâmico **Outputs** da ação **`Card final`** (o Compose da I.5).
4. **Save**.

## I.8 — Testar de ponta a ponta
1. No HUB: **Relatórios** → gere um relatório.
2. Aguarde o OneDrive sincronizar os arquivos (relatório + **`.pdf`** + **`.png`** + `.meta.json`).
3. Power Automate → **Run history**: uma execução **Succeeded** (verde). *(Execuções "Skipped" no ramo If no são normais.)*
4. No grupo do Teams: chega **um card** com a **imagem-convite** (manchete "entre e crie seu agente", tempo devolvido + gráfico, adoção, saúde) e os **3 botões** — **Abrir Playground** · **Solicitar Acesso** · **Baixar Relatório (PDF)**. Clique no PDF → abre.
   > **Imagem não aparece?** É o único ponto sensível a tenant: revise o link direto da imagem (I.4.4/I.5, `&download=1`) ou use o **fallback** abaixo.

## I.9 — Configuração do card no HUB (`backend\.env`)
O relatório semanal vira **1 post**: um card-**convite** (imagem PNG) + botões. O HUB gera o PNG com o
**Chromium offline** (o mesmo do RPA) e grava, na pasta de entrega, o relatório + o **`.pdf`** companheiro
+ o **`.png`** + o `.meta.json`. O JSON do card está no **Apêndice H**: um `Image` (o poster-convite) +
os botões **Abrir Playground** · **Solicitar Acesso** · **Baixar Relatório (PDF)**.

> **Importante:** o card do `.meta.json` já vem **pronto**. O Power Automate só substitui **dois
> placeholders**: `https://hub-report-download.invalid` (link do PDF) e `https://hub-report-image.invalid`
> (link **direto** da imagem) — ambos na I.5. Todo o resto do card e o próprio PNG já chegam prontos.

> **⚠️ Fallback (se a imagem não renderizar no seu tenant):** se a política bloquear links diretos de
> imagem, o HUB continua entregando o **PDF completo** no botão "Baixar Relatório (PDF)". Quando o HUB
> **não** consegue gerar o PNG (sem Chromium), o `.meta.json` traz o **card-texto de convite equivalente**
> (mesma ordem: convite → tempo devolvido → adoção → saúde), sem `image_file` — o fluxo funciona igual.

Ajustes no `backend\.env` (depois: `restart_services.bat` + **gere um relatório novo**):
- **Marca:** o poster desenha o **wordmark "STELLANTIS" localmente** (fidelidade de marca garantida, sem dependência de rede). `REPORT_CARD_LOGO_URL=` (opcional) só é usado no **cabeçalho do card-texto** (fallback); no PNG offline uma logo remota pode não carregar, por isso a marca do poster é sempre local.
- **Horas economizadas** — minutos de setup poupados por arquivo enviado: `REPORT_MINUTES_PER_FILE=4`
- **Botão "Abrir Playground"** — link do Playground (vazio = usa `PLAYGROUND_URL`): `REPORT_CARD_PLAYGROUND_URL=https://genai.stellantis.com/`
- **Botão "Solicitar Acesso"** — link da app Workflows / fluxo da Parte III (vazio = sem botão): `REPORT_CARD_ACCESS_URL=https://teams.microsoft.com/l/app/<appId-da-Workflows>`

O que o HUB calcula e desenha no PNG (via `compute_card_image_data`), na ordem do convite:
1. **Convite (manchete):** "seu ambiente já está pronto — entre e crie seu agente" + corpo + linha "como pedir acesso".
2. **Tempo devolvido ao time:** horas economizadas **desta semana** + **acumulado** (arquivos preparados × `REPORT_MINUTES_PER_FILE`) + **gráfico** cumulativo de horas dos últimos 7 dias.
3. **Adoção:** **engenheiros já usando** (network_ids com acesso concedido) + **SPECs prontas no ambiente**.
4. **Saúde em 1 linha:** nº de itens em tratamento + **previsão de correção** (constante `CARD_HEALTH_ETA` em `routers/reports.py`, padrão "em até 1 dia útil"); ou "tudo certo" quando não há itens.

> **Ficou de fora do card (de propósito):** contagem de arquivos, tabela SPEC-por-SPEC e status cru de
> workspace — isso é "o quanto a máquina trabalhou", não o que o leitor ganha. Quem quiser o detalhe abre
> o **PDF** ("Baixar Relatório").

---

# Parte II — Convite "Solicitar acesso" (2ª mensagem) — LEGADO

> **Não faz mais parte do fluxo principal.** O botão "Solicitar acesso" já vem dentro do card único da Parte I (Apêndice H), via `REPORT_CARD_ACCESS_URL`. Esta parte fica documentada como **alternativa/fallback**, caso o card precise voltar a ser dividido em duas mensagens.

Logo **após** o card do relatório (Parte I), poste **uma segunda mensagem** no mesmo grupo com um botão **"Solicitar acesso"** que abre o formulário self-service (Parte III). É o substituto profissional do antigo "mande seu ID de rede + SPEC por mensagem".

> **Pré-requisito:** o fluxo do formulário (Parte III) já montado.

1. Depois da ação **"Post card in a chat or channel"** (Parte I.7), **+ Add an action** → **Microsoft Teams** → **"Post message in a chat or channel"**.
   > ⚠️ É a **"Post message…"** (mensagem comum, fire-and-forget). **Não** use "…and wait for a response" aqui.
2. **Post as:** **Flow bot** · **Post in:** **Group chat** · selecione **o mesmo grupo**.
3. **Message:** abra a visão de **código/HTML** (ícone **`</>`**) e cole:
   ```html
   <p>📄 Para <b>solicitar acesso</b> a um workspace, clique em
   <a href="COLE_AQUI_O_LINK">Solicitar acesso</a> e execute o fluxo
   <b>"Solicitar acesso - Teams"</b>. Preencha o formulário (ID de rede + SPEC) —
   sua solicitação é registrada automaticamente e o responsável é avisado.</p>
   ```
4. Troque o **`COLE_AQUI_O_LINK`** pelo lançador do formulário (Parte III). Duas formas de obter:
   - **App Workflows:** no Teams → **Apps** → procure **Workflows** → **⋯** → **Copy link** (deep link do seu tenant, `https://teams.microsoft.com/l/app/<appId>`).
   - **Mais direta:** em **make.powerautomate.com**, abra o fluxo **"Solicitar acesso - Teams"** e copie a **URL da página do fluxo**. Quem tem acesso *run-only* cai direto nele e clica **Run**.
5. **Save**.

> ⚠️ **O link leva ao lançador, não ao formulário direto.** Um Adaptive Card *de formulário* (campos + Enviar) **não** abre por URL simples — só funciona quando um fluxo o posta e *aguarda a resposta*. Por isso o botão abre a app Workflows / a página do fluxo, e a pessoa o **executa** ali.

> **Fallback (sem formulário):** deixe o **nome do responsável clicável** abrindo a conversa direta — selecione o nome → ícone de **link** → cole `https://teams.microsoft.com/l/chat/0/0?users=SEU_EMAIL@stellantis.com`.

---

# Parte III — Formulário de Solicitação de Acesso (→ SharePoint)

**Resultado:** em vez de mandar mensagem manual, o colaborador **clica num botão**, preenche um **Adaptive Card** (formulário) e envia. Ao enviar: (1) os dados caem **automaticamente numa Lista do SharePoint** (com Status **Pendente**); (2) o **aprovador é notificado** no Teams com os dados + um **link direto** para o chat com quem pediu.

```
Colaborador clica no botão (Teams) ─▶ Adaptive Card (formulário) ─▶ Envia
        └─▶ grava 1 linha na Lista do SharePoint (Status = Pendente)
        └─▶ avisa o aprovador no Teams (deep link p/ chat do solicitante)
```

### Como funciona (em 1 parágrafo)
Um **fluxo instantâneo** é compartilhado com a equipe. Quando um colaborador o executa (pela app **Workflows** do Teams), o fluxo **posta um Adaptive Card** num canal/chat e **fica esperando o envio** (*Post adaptive card and wait for a response*). Ao clicar **Enviar**, o fluxo recebe **o que ele digitou** (ID de rede, SPEC, justificativa) **e quem enviou** (`responder` = nome + e-mail), grava numa **Lista do SharePoint** e **notifica o aprovador**.

> **⚠️ Esta parte é 100% Microsoft 365** (Teams + Power Automate + SharePoint) — **não** depende do backend do HUB nem do `.env`.

## III.1 — Criar a Lista do SharePoint
1. Abra o **site do SharePoint** da equipe (ou Teams → Equipe → **Arquivos** → **Abrir no SharePoint**).
2. **+ New** → **List** → **Blank list**. **Name:** `Solicitações de Acesso a Workspace` → **Create**.
3. A lista já tem a coluna **Title**. Adicione as demais em **+ Add column**:

| Coluna (display) | Tipo | Observação |
|---|---|---|
| **Title** (já existe) | Single line of text | Vamos usar para a **SPEC / Workspace**. |
| **Solicitante** | Single line of text | Nome de quem pediu (do `responder`). |
| **IDRede** | Single line of text | ID de rede do solicitante. |
| **Email** | Single line of text | E-mail do solicitante (do `responder`). |
| **Justificativa** | Multiple lines of text | Texto livre. |
| **Status** | Choice | **Pendente / Aprovado / Recusado**; **Default value** = **Pendente**. |

> A coluna **Created** (automática) já registra **quando** a solicitação chegou. Anote o **endereço do site** e o **nome da lista** (usados na III.4).

> 🔐 **Privacidade / LGPD (obrigatório).** Esta lista guarda **dados pessoais** (nome, e-mail, ID de rede,
> justificativa). Portanto:
> - **Finalidade única:** controlar pedidos de acesso a workspace. Não use os dados para outro fim.
> - **Acesso restrito:** dê permissão de leitura **apenas ao grupo de aprovadores** (SharePoint → **Configurações da lista → Permissões**); não deixe a lista aberta ao site inteiro.
> - **Retenção:** defina um expurgo periódico (ex.: apagar solicitações **resolvidas há mais de 6 meses**) — pode ser um fluxo agendado do Power Automate.
> - **Classificação:** marque a lista/site como **Interno – Stellantis**. Em caso de dúvida, valide com **Privacidade/Compliance** antes de publicar para toda a equipe.

## III.2 — Criar o fluxo e o gatilho
1. **make.powerautomate.com** → **Create** → **Instant cloud flow**.
2. **Flow name:** `Solicitar acesso - Teams`.
3. Em **"Choose how to trigger this flow"** → **"Manually trigger a flow"** → **Create**.

> **Por quê:** é o "botão". Quem tiver o fluxo compartilhado (III.6) o executa pelo Teams. Cada execução abre **um** formulário e trata **uma** solicitação → várias pessoas podem pedir ao mesmo tempo, sem conflito.

## III.3 — Postar o card do formulário e aguardar o envio
1. **+ New step** → **Microsoft Teams** → **"Post adaptive card and wait for a response"**.
   > **⚠️ Use exatamente a "… and wait for a response".** A ação simples não devolve o que o usuário digitou nem o `responder`.
2. Configure:
   - **Post as:** **Flow bot**.
   - **Post in:** **Channel** (recomendado — canal "Solicitações de Acesso") **ou** **Group chat**.
   - **Team / Channel** (ou **Group chat**): selecione o destino.
   - **Adaptive Card:** cole **todo** o JSON do **Apêndice A** (o formulário).
   - **Update message:** (opcional) `Solicitação recebida ✔️`.
3. Renomeie a ação para **`Formulario`** (⋯ → Rename) — assim as expressões ficam curtas: `body('Formulario')?[...]`.
4. **Save**.

> **Por que num canal/grupo (não 1:1):** o gatilho "Manually trigger a flow" não diz **quem** apertou. Postando num canal/grupo, qualquer um preenche e a ação devolve o **`responder`** (quem enviou). Cada execução posta o **seu** card; não há mistura.

## III.4 — Gravar a solicitação na Lista do SharePoint
1. **+ New step** → **SharePoint** → **"Create item"**.
2. **Site Address:** o site da III.1. · **List Name:** **Solicitações de Acesso a Workspace**.
3. Mapa de campos:

| Campo da Lista | Valor |
|---|---|
| **Title** | conteúdo dinâmico **spec** *(ou `body('Formulario')?['data']?['spec']`)* |
| **IDRede** | conteúdo dinâmico **idrede** *(ou `body('Formulario')?['data']?['idrede']`)* |
| **Justificativa** | conteúdo dinâmico **justificativa** *(ou `body('Formulario')?['data']?['justificativa']`)* |
| **Solicitante** | `body('Formulario')?['responder']?['displayName']` |
| **Email** | `body('Formulario')?['responder']?['email']` |
| **Status Value** | digite `Pendente` |

4. **Save**.

> **⚠️ Campos vazios?** Ao colar o card, o conector costuma mostrar `idrede`/`spec`/`justificativa` como conteúdo dinâmico — clique neles. Se vier vazio, use `body('Formulario')?['data']?['<campo>']`; confirme em **Show raw outputs** se os valores estão sob `data` ou no topo. **E-mail vazio?** Alguns tenants usam `userPrincipalName` em vez de `email`.

## III.5 — Notificar o aprovador
1. **+ New step** → **Microsoft Teams** → **"Post message in a chat or channel"**.
2. **Post as:** **Flow bot** · **Post in:** **Chat with Flow bot** · **Recipient:** e-mail do aprovador (ex.: `AB12345@stellantis.com` — troque pelo e-mail real do responsável).
3. **Message:** visão de **código/HTML** (`</>`) → cole o modelo do **Apêndice C**.
4. **Save**.

> O **deep link** `https://teams.microsoft.com/l/chat/0/0?users=<email>` abre o chat direto com o solicitante. **Alternativa:** trocar por **"Send an email (V2)"** (Office 365 Outlook) — o corpo aceita as mesmas expressões.

## III.6 — Disponibilizar o "botão" para a equipe
1. No Power Automate, abra o fluxo → **Share** → em **Run only users**, adicione as pessoas ou um **grupo do Microsoft 365**.
   > Em **Connections**, mantenha as conexões **do dono** para simplicidade (o card sai sempre pelo mesmo Flow bot/canal).

> 🏢 **Governança (evite dependência de 1 pessoa).** Como as conexões são "do dono", se a conta dona sair
> da empresa ou trocar a senha, **o fluxo quebra para todos**. Recomendação corporativa: usar uma **conta
> de serviço** (mailbox funcional) como **dona** dos fluxos das Partes I e III e adicionar **co-owners**
> (Share → *Owners*). Assim o fluxo sobrevive a trocas de time. Vale para **os dois** fluxos deste guia.
2. **Como o colaborador executa (o "botão"):**
   - **No Teams:** app **Workflows** → lista de fluxos → **`Solicitar acesso - Teams`** → **Run**.
   - **Ou** em **make.powerautomate.com** → **My flows** → **Shared with me** → **Run**.
3. Ao executar, o card aparece no canal/grupo — a pessoa preenche e clica **Enviar**.

> **Descoberta:** fixe (Pin) a app **Workflows** na barra do Teams, ou poste no canal uma mensagem fixada explicando como rodar. O mesmo link é o que entra no botão da **Parte II**.

## III.7 — Testar de ponta a ponta
1. Execute o fluxo pela app **Workflows**. No canal/grupo o **formulário** aparece → preencha **ID de rede / SPEC / Justificativa** → **Enviar**.
2. Power Automate → **Run history**: **Succeeded**.
3. **Lista do SharePoint**: linha nova com **Title = SPEC**, **Solicitante**, **Email**, **IDRede**, **Justificativa**, **Status = Pendente**.
4. O **aprovador** recebe a mensagem com o link **"Abrir chat com o solicitante"** — clique e confirme.

---

# Parte IV — Alternativas

### IV.1 — Entrega por e-mail com anexo (a mais simples)
Em vez do card no grupo (Parte I.5/I.7), depois do **Parse JSON** (I.3) e de um **"Get file content using path"** do `attachment_file`:
1. **Office 365 Outlook** → **"Send an email (V2)"**.
2. **To:** seu destinatário (ou `email_to` do sidecar). · **Subject:** ex. `Relatório Automation HUB — @{body('Parse_JSON')?['name']}`.
3. **Advanced options → Attachments:** **Name** = `attachment_file`; **Content** = a saída do "Get file content using path".

### IV.2 — Postar no canal do Teams com o arquivo
O conector do Teams posta **mensagem**; para o arquivo aparecer no canal, coloque-o na biblioteca **SharePoint** do time:
1. **SharePoint** → **"Create file"** no site do Team, biblioteca **Documents / `<nome do canal>`** → Name = `attachment_file`, Content = o conteúdo do PDF.
2. **Microsoft Teams** → **"Post message in a chat or channel"** no canal, com um aviso e (opcional) o **link do item** criado.

### IV.3 — Botão manual no dashboard (sem Power Automate)
Cada relatório em **Relatórios** tem o botão **Teams**: ele **baixa** o relatório e **abre o Teams** no destino configurado (você anexa manualmente). Configure o destino em **Configurações & Calibração** → **"Link do Teams (URL do canal ou chat)"** (deep link do canal: no Teams, canal → **⋯** → **Obter link para o canal**). Limitação: deep links **não anexam arquivo** automaticamente.

### IV.4 — Roteamento dinâmico pelo sidecar (Parte I)
Como o gatilho já é o `.meta.json` e você já fez o Parse JSON, use os campos `email_to` / `teams_channel` / `subject` (quando presentes) direto nas ações de envio. Eles só aparecem quando o relatório é enviado pelo endpoint manual `POST /api/integrations/reports/{id}/deliver-folder` com esses campos.

---

# Parte V — Automação "PNG → Teams" (sem Power Automate)

**O que é:** diferente das Partes I–IV (que dependem de um fluxo do Power Automate), esta automação é **100% interna ao HUB**: um robô Playwright abre o **Teams Web** sozinho, encontra o chat/grupo configurado e envia o **PNG mais recente** de uma pasta vigiada — sem precisar de OneDrive sincronizado, sem fluxo no Power Automate e sem `.meta.json`. É o mecanismo mais simples dos cinco: "aparece um PNG novo na pasta → o HUB manda".

**Resultado:** invisível no dia a dia (não abre nenhuma janela) — só abre um navegador **visível** na primeira vez, ou sempre que a sessão salva expirar, para você fazer o login manual (a mesma conta Microsoft usada no Playground). Depois do login, a sessão fica salva e as próximas execuções voltam a ser 100% invisíveis.

### Como funciona (em 1 parágrafo)
O backend do HUB verifica periodicamente (ou num dia/hora fixo) a pasta configurada em `TEAMS_PNG_WATCH_FOLDER`. Se houver um `.png` cujo **conteúdo** (hash SHA-256, não o nome) ainda não foi enviado, ele enfileira uma tarefa `deliver_png_teams_playwright` para o **agente local** (o mesmo processo que já dirige o Playground). O agente abre um Chromium com um **perfil de navegador próprio e persistente** (`TEAMS_BROWSER_SESSION_PATH`), acessa `teams.microsoft.com`, localiza o chat pelo nome configurado, anexa o PNG e envia a mensagem. Só então o arquivo é marcado como "já enviado" — se o envio falhar, ele tenta de novo na próxima checagem, nunca reenvia um arquivo que já foi confirmado.

### V.1 — Passo a passo do fluxo interno

1. **Detecção (backend, a cada checagem):** `app/services/teams_png_watch.py` lista os `.png` de `TEAMS_PNG_WATCH_FOLDER` e pega o mais recente por data de modificação.
2. **Dedup por conteúdo:** calcula o SHA-256 do arquivo e compara com o último hash enviado (guardado em `backend/data/teams_png_delivery_state.json`). Hash igual → não faz nada (evita reenviar o mesmo relatório várias vezes só porque a checagem rodou de novo).
3. **Fila da tarefa:** se o hash é novo, o `schedule_runner.py` cria a tarefa `deliver_png_teams_playwright` para o **mesmo usuário que já está conectado ao Playground** (`fallback_session_user` — por isso não é preciso configurar uma conta separada para o Teams: é sempre a identidade corporativa já usada no HUB).
4. **Execução (agente local):** o agente pega a tarefa na próxima vez que consultar o backend (`POST /api/agents/poll`), abre o Chromium com o perfil `TEAMS_BROWSER_SESSION_PATH` e roda `app/services/playwright/teams_delivery.py::deliver_file_teams_playwright`.
5. **Login (só quando necessário):** o robô confere se a sessão salva do Teams ainda está logada (`is_teams_logged_in`). Se estiver, segue **invisível** (headless). Se **não** estiver (primeira vez, ou sessão expirada), ele avisa o agente, que reabre o **mesmo** Chromium de forma **visível** uma única vez, aguarda você concluir o login SSO (a mesma conta Microsoft do Playground) e repete a tarefa automaticamente — sem precisar reiniciar nada.
6. **Envio:** localiza o chat pelo nome (`TEAMS_PNG_DELIVERY_CHAT_NAME`), anexa o PNG pelo seletor real de "Anexar arquivos" do Teams Web e clica em Enviar. Só confirma sucesso quando o anexo aparece de fato na composição da mensagem (evita "sucesso" falso).
7. **Confirmação:** o agente informa o backend que a tarefa terminou; o hash do PNG enviado é gravado — esse mesmo arquivo nunca mais é reenviado, mesmo que ele continue sendo o "mais recente" da pasta.

### V.2 — Configuração (`backend\.env`)

| Variável | Para que serve | Padrão |
|---|---|---|
| `TEAMS_PNG_DELIVERY_ENABLED` | Liga/desliga a automação inteira. | `false` |
| `TEAMS_PNG_WATCH_FOLDER` | Pasta local vigiada (pode ser a mesma pasta de saída do gerador de relatório/PNG). | *(vazio)* |
| `TEAMS_PNG_DELIVERY_CHAT_NAME` | Nome exato do chat/grupo de destino no Teams. Vazio = usa `TEAMS_DELIVERY_CHAT_NAME`. | *(vazio)* |
| `TEAMS_PNG_DELIVERY_TEXT` | Texto da mensagem enviada junto com o PNG. Vazio = mensagem padrão com o nome do arquivo. | *(vazio)* |
| `TEAMS_PNG_DELIVERY_MODE` | `schedule` = só verifica no dia/hora fixos abaixo; `continuous` = verifica a cada N segundos, qualquer dia. | `schedule` |
| `TEAMS_PNG_DELIVERY_DAY_OF_WEEK` / `TEAMS_PNG_DELIVERY_TIME` | Dia/hora fixos (modo `schedule`). | `monday` / `09:00` |
| `TEAMS_PNG_DELIVERY_POLL_INTERVAL_SECONDS` | Intervalo entre checagens (modo `continuous`). | `300` |
| `TEAMS_BROWSER_SESSION_PATH` | Pasta do **perfil de navegador persistente** do Teams (guarda o login entre execuções — não apagar). | `./data/browser_session_teams` |
| `PLAYWRIGHT_HEADLESS` | `true` = invisível por padrão (recomendado); a automação abre visível sozinha só quando o login expira. `false` = sempre visível (útil só para depurar). | `true` |
| `MANUAL_LOGIN_TIMEOUT_MINUTES` | Quanto tempo a janela visível espera pelo login manual antes de desistir (tentativa seguinte tenta de novo). | `10` |

> **Por que "invisível" e não uma janela minimizada?** `PLAYWRIGHT_HEADLESS=true` faz o Chromium nunca desenhar janela nenhuma (modo headless real do navegador) — não é uma janela escondida atrás de outras, é o processo rodando sem interface gráfica.

### V.3 — Sobre reutilizar a conta do Playground

A automação **não pede uma conta separada**: a tarefa de envio é sempre atribuída ao **mesmo usuário já conectado ao Playground** no HUB (o robô escolhe automaticamente o usuário com sessão Playground ativa). Como o login do Teams e do Playground passam pelo **mesmo SSO corporativo (Azure AD)**, basta fazer o login manual do Teams **uma única vez** (na janela visível que aparece automaticamente quando necessário) usando a **mesma conta Microsoft** já usada para conectar o Playground — depois disso as duas sessões (Playground e Teams) ficam salvas cada uma no seu próprio perfil de navegador (`BROWSER_SESSION_PATH` e `TEAMS_BROWSER_SESSION_PATH`, respectivamente) e a automação passa a rodar sozinha, sem pedir login de novo, a não ser que a sessão expire (o que também é raro, pois o perfil é persistente entre reinicializações do serviço).

### V.4 — Primeira ativação / recalibração de login (passo a passo)

1. No `backend\.env`, confirme `TEAMS_PNG_DELIVERY_ENABLED=true`, `TEAMS_PNG_WATCH_FOLDER=<sua pasta>` e `PLAYWRIGHT_HEADLESS=true`.
2. Rode `restart_services.bat` para o backend e o agente local pegarem a configuração nova.
3. Coloque um `.png` de teste na pasta vigiada (ou aguarde o próximo relatório ser gerado).
4. Se for a **primeira vez** (ou a sessão do Teams expirou), uma janela do Chromium **abrirá sozinha** pedindo o login — faça o SSO normalmente com a conta corporativa (a mesma do Playground) e aguarde a mensagem ser enviada; a janela fecha sozinha ao concluir.
5. Nas próximas vezes, **nenhuma janela aparece** — o envio acontece em segundo plano. Você pode conferir em `backend\data\logs\local_agent_runtime.out.log` (ou nos **Logs** do dashboard) que a tarefa `deliver_png_teams_playwright` foi concluída.
6. Se quiser reforçar/testar o login manualmente a qualquer momento, defina `PLAYWRIGHT_HEADLESS=false` temporariamente, reinicie os serviços, force o disparo (arquivo novo na pasta) e depois volte para `true`.

### V.5 — Solução de problemas específica

| Sintoma | Causa provável / Solução |
|---|---|
| **Nada é enviado e nenhuma janela abre** | Confira `TEAMS_PNG_DELIVERY_ENABLED=true` e se o `.png` realmente é o mais recente da pasta (por data de modificação). Veja `backend\data\logs\backend_runtime.out.log` por linhas `[teams_png_watch]`. |
| **"PNG já foi enviado antes (mesmo conteúdo)"** | Esperado — o HUB não reenvia o mesmo conteúdo duas vezes. Se quiser forçar o reenvio, gere/edite o PNG (o conteúdo/hash muda) ou apague `backend\data\teams_png_delivery_state.json` (reseta o controle de dedup). |
| **A janela do Chromium abre toda vez, mesmo já tendo logado antes** | O login não está persistindo: confirme que `TEAMS_BROWSER_SESSION_PATH` aponta para uma pasta com permissão de escrita e que ninguém está apagando `backend\data\browser_session_teams` entre execuções. |
| **Janela abre e some sem enviar / erro de "chat não encontrado"** | O nome em `TEAMS_PNG_DELIVERY_CHAT_NAME` precisa ser **exatamente** igual ao nome do chat/grupo no Teams. Veja o screenshot de erro em `backend\data\screenshots\errors`. |
| **Depois de reiniciar o notebook, pede login de novo** | Normal ocasionalmente (expiração de sessão do Azure AD). Basta fazer o login uma vez na janela visível que abre sozinha; a sessão volta a persistir. |
| **Quero voltar a ver a janela sempre (depuração)** | Defina `PLAYWRIGHT_HEADLESS=false` no `.env` e rode `restart_services.bat`. Lembre de voltar para `true` depois. |

---

# Solução de problemas (consolidada)

| Sintoma | Causa provável / Solução |
|---|---|
| **(I) O gatilho não dispara** | A pasta precisa estar **no OneDrive sincronizado** (check verde). Pasta local pura não funciona no fluxo de nuvem. |
| **(I) Tudo "Skipped" / nada postado** | A condição foi para o **Falso**. Use a **expressão** `triggerOutputs()?['headers']?['x-ms-file-name']` *contains* **`meta`** (não o chip "File name"). |
| **(I) Parse JSON: "content deve ser do tipo JSON" (octet-stream)** | No **Content** use `base64ToString(triggerBody()?['$content'])`, não o chip "File content". |
| **(I) Card Final: "replace espera string, valor é Null"** | Use `body('Link_PDF')?['webUrl']` / `body('Link_Imagem')?['webUrl']` (no topo), não `['link']['webUrl']`. |
| **(I) Botão abre `hub-report-download.invalid`** | O `replace` não substituiu: confira os nomes das ações (`Link_PDF`/`Link_Imagem`) e se o **webUrl** não está vazio (teste a I.4.2/I.4.4 sozinhas). |
| **(I) A imagem do card não aparece (quadro quebrado)** | O `Image.url` precisa devolver os **bytes** do PNG: revise `Link_Imagem` + o **`&download=1`** (I.5) e o **Link scope** (**Organization** — padrão). Persistindo, use o **fallback do PDF** (I.9) em vez de abrir link "Anyone". |
| **(I) "Get file metadata using path" falha (404)** | O **File path** é relativo à raiz do OneDrive (começa em `/`), sem "OneDrive - Stellantis". Confira a pasta e o `attachment_file`. |
| **(I/III) O grupo não aparece em "Group chat"** | Mande uma mensagem qualquer no grupo pelo Teams e reabra a lista; ou use o **Group chat id**. |
| **(III) `InvalidJsonInBotAdaptiveCard` / "Unexpected character… value: j"** | O campo **Adaptive Card** começou com a palavra `json` (ou crases) coladas. Cole **só** o conteúdo entre `{` e `}` (1º caractere = `{`). |
| **(III) Campos (idrede/spec) vazios na Lista** | Use `body('Formulario')?['data']?['idrede']` (idem `spec`, `justificativa`); confira em **Show raw outputs**. |
| **(III) Solicitante/Email vazios** | `body('Formulario')?['responder']?['displayName']` / `...?['email']` (fallback `...?['userPrincipalName']`). |
| **(III) "Create item" falha — coluna obrigatória** | **Title** é obrigatório (receba a **spec**). Em **Status**, **Status Value** = `Pendente` (texto exato da Choice). |
| **(II/III) Deep link não abre o chat** | O `users=` precisa de e-mail/UPN válido. Teste a URL no navegador. |
| **(III) Colaborador não acha o fluxo** | Precisa estar em **Run only users** (III.6). Procure em **Workflows** (Teams) ou **My flows → Shared with me**. |
| **Card "feio"/quebrado** | Cole o JSON no [Adaptive Card Designer](https://adaptivecards.io/designer/) (Host app: *Microsoft Teams*) para depurar. |

---

# Apêndices

## Apêndice A — JSON do Adaptive Card do formulário (Parte III)
Cole no campo **Adaptive Card** da ação **"Post adaptive card and wait for a response"** (III.3).

> **⚠️ Copie só o conteúdo entre `{` e `}`** (o 1º caractere tem que ser `{`). **Não** inclua a palavra `json` nem as crases — senão o Teams falha com `InvalidJsonInBotAdaptiveCard`.

```json
{
  "type": "AdaptiveCard",
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.4",
  "body": [
    { "type": "TextBlock", "text": "Solicitação de acesso a workspace", "weight": "Bolder", "size": "Large", "wrap": true },
    { "type": "TextBlock", "text": "Preencha os campos abaixo. Seu nome e e-mail são capturados automaticamente.", "isSubtle": true, "wrap": true, "spacing": "None" },
    { "type": "Input.Text", "id": "idrede", "label": "ID de rede", "placeholder": "Ex.: AB12345", "isRequired": true, "errorMessage": "Informe o seu ID de rede." },
    { "type": "Input.Text", "id": "spec", "label": "SPEC / Workspace desejado", "placeholder": "Nome da SPEC ou do workspace", "isRequired": true, "errorMessage": "Informe a SPEC ou o workspace." },
    { "type": "Input.Text", "id": "justificativa", "label": "Justificativa (opcional)", "placeholder": "Por que você precisa do acesso?", "isMultiline": true }
  ],
  "actions": [
    { "type": "Action.Submit", "title": "Enviar solicitação", "data": { "acao": "solicitar_acesso" } }
  ]
}
```

## Apêndice B — Schema pronto para o "Parse JSON" (Parte I)
```json
{
  "type": "object",
  "properties": {
    "report_id": { "type": "integer" },
    "name": { "type": "string" },
    "report_type": { "type": "string" },
    "file_format": { "type": "string" },
    "period_start": { "type": "string" },
    "period_end": { "type": "string" },
    "generated_at": { "type": "string" },
    "report_file": { "type": "string" },
    "attachment_file": { "type": "string" },
    "download_url_placeholder": { "type": "string" },
    "image_file": { "type": "string" },
    "image_url_placeholder": { "type": "string" },
    "card": { "type": "object" },
    "adaptive_card": { "type": "object" },
    "teams_channel": { "type": "string" },
    "email_to": { "type": "string" },
    "subject": { "type": "string" }
  },
  "required": ["report_file", "attachment_file", "adaptive_card", "download_url_placeholder"]
}
```

## Apêndice C — Mensagem de notificação ao aprovador (HTML, Parte III.5)
Cole na visão de **código/HTML** (`</>`) do campo **Message**:
```html
<p><b>Nova solicitação de acesso</b></p>
<ul>
  <li><b>Solicitante:</b> @{body('Formulario')?['responder']?['displayName']} (@{body('Formulario')?['responder']?['email']})</li>
  <li><b>ID de rede:</b> @{body('Formulario')?['data']?['idrede']}</li>
  <li><b>SPEC / Workspace:</b> @{body('Formulario')?['data']?['spec']}</li>
  <li><b>Justificativa:</b> @{body('Formulario')?['data']?['justificativa']}</li>
</ul>
<p><a href="https://teams.microsoft.com/l/chat/0/0?users=@{body('Formulario')?['responder']?['email']}">Abrir chat com o solicitante</a></p>
```

## Apêndice D — Expressões usadas (copiar/colar)
**Parte I (relatório):**
```
triggerOutputs()?['headers']?['x-ms-file-name']            (Condição: contains "meta")
base64ToString(triggerBody()?['$content'])                 (Parse JSON → Content)
/AutomationHUB/reports/@{body('Parse_JSON')?['attachment_file']}   (File path do PDF — troque a pasta)
/AutomationHUB/reports/@{body('Parse_JSON')?['image_file']}        (File path da imagem — troque a pasta)
replace(replace(string(body('Parse_JSON')?['adaptive_card']), body('Parse_JSON')?['download_url_placeholder'], body('Link_PDF')?['webUrl']), body('Parse_JSON')?['image_url_placeholder'], concat(body('Link_Imagem')?['webUrl'], '&download=1'))   (Card final)
```
**Parte III (formulário):**
```
body('Formulario')?['data']?['idrede']  ·  ['spec']  ·  ['justificativa']
body('Formulario')?['responder']?['displayName']  ·  ['email']  (fallback: ['userPrincipalName'])
https://teams.microsoft.com/l/chat/0/0?users=@{body('Formulario')?['responder']?['email']}
```

## Apêndice E — Estrutura do sidecar `.meta.json` (gerado pelo HUB, Parte I)
```json
{
  "report_id": 12,
  "name": "Relatório Simplificado (XLSX)",
  "report_type": "Relatório Simplificado",
  "file_format": "xlsx",
  "period_start": "2026-05-25T00:00:00-03:00",
  "period_end": "2026-06-24T23:59:59-03:00",
  "generated_at": "2026-06-24T14:30:22-03:00",
  "report_file": "relatorio_simplificado_20260624_143022.xlsx",
  "attachment_file": "relatorio_simplificado_20260624_143022.pdf",
  "download_url_placeholder": "https://hub-report-download.invalid",
  "image_file": "relatorio_simplificado_20260624_143022.png",
  "image_url_placeholder": "https://hub-report-image.invalid",
  "card": { "title": "...", "period": "...", "generated_at": "...", "kind": "adoption" },
  "adaptive_card": { "type": "AdaptiveCard", "version": "1.4", "body": ["... Image (poster-convite) ..."] },
  "teams_channel": "Relatorios",
  "email_to": "fulano@stellantis.com",
  "subject": "Relatório Simplificado"
}
```
> `attachment_file` = o **PDF** a anexar; `image_file` = o **PNG** do convite (o card carrega esta imagem); `adaptive_card` = card **pronto** para postar verbatim; `download_url_placeholder`/`image_url_placeholder` = as URLs que o `replace` aninhado (I.5) troca pelos links reais. `image_file`/`image_url_placeholder` **só aparecem quando o HUB gerou o PNG** — sem eles, o `adaptive_card` volta a ser o **card-texto de convite equivalente** (fallback). `teams_channel`/`email_to`/`subject` só aparecem quando enviado pelo endpoint `deliver-folder` com routing.

## Apêndice F — Esquema da Lista do SharePoint (Parte III)
| Coluna | Tipo | Origem no fluxo |
|---|---|---|
| **Title** | Single line of text | `spec` |
| **Solicitante** | Single line of text | `responder.displayName` |
| **IDRede** | Single line of text | `idrede` |
| **Email** | Single line of text | `responder.email` |
| **Justificativa** | Multiple lines of text | `justificativa` |
| **Status** | Choice (Pendente/Aprovado/Recusado) | fixo `Pendente` |
| **Created** | Date (automática) | data/hora do envio |

## Apêndice G — Diagramas (visão de cima)
**Parte I — Convite no Teams:**
```
[Trigger] When a file is created (OneDrive, pasta de entrega)
   └─ [Condition] expr x-ms-file-name  contains  "meta"
        └─ If yes:
             1) Parse JSON          (base64ToString(triggerBody()?['$content']))
             2) Meta_PDF   : Get file metadata using path  (/sua-pasta/ + attachment_file)
             3) Link_PDF   : Create share link  (File = Id)  → webUrl
             4) Meta_Imagem: Get file metadata using path  (/sua-pasta/ + image_file)
             5) Link_Imagem: Create share link  (File = Id)  → webUrl (+ &download=1)
             6) Compose "Card final" (replace aninhado: placeholder PDF + placeholder imagem)
             7) Post card in a chat or channel  (Flow bot, Group chat, Card = Outputs do "Card final" — I.7)
                 → 1 card = imagem-convite + 3 botões (Playground/Acesso/PDF) (Apêndice H)
```
**Parte III — Formulário de Acesso:**
```
[Trigger] Manually trigger a flow   (compartilhado run-only → app Workflows)
   1) Post adaptive card and wait for a response  (Flow bot → Channel/Group; card do Apêndice A) → "Formulario"
   2) Create item  (SharePoint → "Solicitações de Acesso a Workspace")
        Title=spec | IDRede=idrede | Justificativa=justificativa | Solicitante=responder.displayName | Email=responder.email | Status=Pendente
   3) Post message in a chat or channel  (Flow bot → aprovador; dados + deep link p/ chat do solicitante)
```

## Apêndice H — JSON do Adaptive Card de Dados do Relatório Semanal (Parte I)

O card do relatório semanal é **uma imagem (PNG) de CONVITE + botões**. Diferente do Apêndice A (colado estático), este card já chega **pronto** no `.meta.json` (campo `adaptive_card`) — você **não** cola nada no Power Automate. Todo o conteúdo visual (manchete-convite, tempo devolvido + gráfico, adoção, saúde em 1 linha) está **dentro da imagem**, desenhada pelo HUB via **HTML+SVG → PNG** com o **Chromium offline** (`backend/app/services/report_image.py`). O Power Automate só troca **dois placeholders** (na I.5): `https://hub-report-download.invalid` (link do PDF) e `https://hub-report-image.invalid` (link **direto** da imagem).

O JSON abaixo é só **referência** (o que o HUB gera):

```json
{
  "type": "AdaptiveCard",
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.4",
  "msteams": { "width": "Full" },
  "body": [
    {
      "type": "Image",
      "url": "https://hub-report-image.invalid",
      "size": "Stretch",
      "altText": "Relatório Semanal — Stellantis Automation HUB"
    }
  ],
  "actions": [
    { "type": "Action.OpenUrl", "title": "Abrir Playground", "url": "https://genai.stellantis.com/" },
    { "type": "Action.OpenUrl", "title": "Solicitar Acesso", "url": "https://teams.microsoft.com/l/app/<appId-da-Workflows>" },
    { "type": "Action.OpenUrl", "title": "Baixar Relatório (PDF)", "url": "https://hub-report-download.invalid" }
  ]
}
```

> **De onde vêm os valores:** o `Image.url` (`https://hub-report-image.invalid`) é trocado pelo **link direto da imagem** (I.4.4/I.5, com `&download=1`); **Abrir Playground** usa `REPORT_CARD_PLAYGROUND_URL` (ou `PLAYGROUND_URL`); **Solicitar Acesso** usa `REPORT_CARD_ACCESS_URL` (o botão some quando vazio); **Baixar Relatório (PDF)** é o placeholder do PDF trocado na I.5. Todo o conteúdo (convite, tempo devolvido, adoção, saúde) está **na imagem** — nada é montado com elementos do Teams.

> **⚠️ A imagem só renderiza se o `Image.url` devolver os bytes do PNG** (não uma página de visualização do OneDrive/SharePoint) — ver I.4.4/I.5. Quando o HUB **não** gera o PNG (sem Chromium), o `.meta.json` volta a trazer o **card-texto** de adoção (convite + horas + adoção + saúde), sem `image_file` — **fallback** automático, ver I.9.

---

# Checklists finais

**Parte I — Convite no Teams:**
- [ ] `REPORT_DELIVERY_PATH` numa pasta do OneDrive sincronizada + `restart_services.bat`.
- [ ] Relatório de teste gerou o relatório + **`.pdf`** + **`.png`** + `.meta.json` e o OneDrive sincronizou (check verde).
- [ ] Trigger **When a file is created** na pasta · **Condition** `x-ms-file-name` **contains** `meta`.
- [ ] **Parse JSON** com `base64ToString(triggerBody()?['$content'])` + schema (Apêndice B, com `image_file`/`image_url_placeholder`).
- [ ] **PDF:** `Meta_PDF` + `Link_PDF` (**Link scope: Organization**). · **Imagem:** `Meta_Imagem` + `Link_Imagem` (**Organization**, link **direto** `&download=1`).
- [ ] **Compose "Card final"** com o **replace aninhado** (placeholder do PDF **e** da imagem).
- [ ] **Post card in a chat or channel** (não a variante "wait for a response") → Flow bot → Group chat.
- [ ] Card-convite mostra **manchete "entre e crie seu agente" + tempo devolvido + adoção + saúde** + os **3 botões** (Abrir Playground · Solicitar Acesso · Baixar Relatório (PDF)).
- [ ] `backend\.env` com `REPORT_CARD_PLAYGROUND_URL` (ou `PLAYGROUND_URL`) e `REPORT_CARD_ACCESS_URL` preenchidos.
- [ ] Teste real: **Succeeded** + card no grupo com **a imagem-convite** e **Baixar Relatório (PDF)**. *(Imagem não aparece? ver I.4.4/I.5 + fallback I.9.)*

**Parte III — Formulário de Acesso:**
- [ ] **Lista do SharePoint** com as colunas (Title=SPEC, Solicitante, IDRede, Email, Justificativa, Status=Pendente padrão).
- [ ] **Instant flow** com **"Manually trigger a flow"**.
- [ ] **"Post adaptive card and wait for a response"** (não a simples) → Flow bot → Channel/Group → card do Apêndice A → renomeada para **`Formulario`**.
- [ ] **"Create item"** mapeando `spec/idrede/justificativa` + `responder.displayName/email` + `Status = Pendente`.
- [ ] **"Post message in a chat or channel"** para o aprovador (Apêndice C).
- [ ] Fluxo **compartilhado (Run only users)** e acessível pela app **Workflows**.
- [ ] Teste real: card preenchido → **linha nova na Lista (Pendente)** + aviso no Teams com link.

---

# Suporte, governança e riscos conhecidos

**Suporte & escalonamento**
- **Dono do processo:** área **Infotainment — Automation HUB** (ver cabeçalho deste guia).
- **1º nível (fluxo não posta / erro no Power Automate):** dono do fluxo / co-owner → **Run history** do fluxo mostra o passo que falhou; use o **Solução de problemas** acima.
- **2º nível (o HUB não gera `.png`/`.pdf`/`.meta.json`):** time do Automation HUB (backend) — checar `REPORT_DELIVERY_PATH`, Chromium offline e logs do serviço.
- **Acesso a workspace (colaborador):** botão **Solicitar Acesso** (Parte III) → aprovador registrado na Lista do SharePoint.

**Governança**
- Fluxos das Partes I e III devem pertencer a uma **conta de serviço** com **co-owners** (III.6), não a uma conta pessoal.
- A Lista do SharePoint da Parte III guarda **dados pessoais** — seguir a nota de **LGPD** da III.1 (acesso restrito, retenção, classificação Interno).
- Compartilhamento OneDrive: **`Organization`** por padrão; **`Anyone`** só como exceção aprovada pela Segurança da Informação.

**Riscos conhecidos**
- **`&download=1`** (I.5) depende de comportamento **não documentado** da API de compartilhamento do OneDrive/SharePoint para servir os bytes do PNG ao Teams. Funciona hoje; a Microsoft pode alterar. Se a imagem parar de renderizar, o **fallback do PDF** (I.9) mantém a entrega — revalidar o link direto quando isso ocorrer.
- **Acessibilidade:** o conteúdo do convite vive **dentro de um PNG** (leitores de tela só leem o `altText`). A versão acessível/legível por máquina é o **PDF** anexado no botão "Baixar Relatório".

---

*Os nomes de ações/campos podem variar levemente conforme o idioma e a versão do portal do Power Automate (PT/EN). Os termos em inglês entre parênteses ajudam a localizar.*
