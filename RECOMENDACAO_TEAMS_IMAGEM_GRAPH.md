# Recomendação — Imagem do relatório semanal não aparece no Teams (Power Automate vs Python/Graph API)

| | |
|---|---|
| **Complementa** | `GUIA_POWER_AUTOMATE.md` (não substitui — nenhum passo dele foi removido) |
| **Motivo** | A imagem do card semanal parou de renderizar ("quadro quebrado") com os dados do relatório |
| **Data** | 10/07/2026 |

---

## ⚠️ Atualização (10/07/2026) — destino confirmado é um GRUPO, não um canal

Depois de escrever a recomendação abaixo, confirmamos que o destino real é o grupo **"1:1 Ederson"**
no Teams (grupo/chat, não um canal de Equipe). Isso muda a solução:

- A **Seção 3** abaixo (`GraphClient.send_channel_message_with_image_card`, endpoint
  `/api/integrations/reports/{id}/teams-image`) usa credencial de **aplicativo** (client-credentials).
  A Microsoft **não permite** postar em chats 1:1/grupo com credencial de aplicativo — só com login
  delegado de usuário ou um Bot registrado
  ([Microsoft Learn — ChatMessage.Send](https://graphpermissions.merill.net/permission/ChatMessage.Send)).
  **Esse código continua no repositório (não faz mal nenhum ali) mas só serve se um dia vocês
  quiserem postar num canal de Equipe** — não serve para o grupo "1:1 Ederson".
- Embutir os bytes da imagem numa mensagem de grupo via Graph exigiria o conector **Premium**
  "HTTP with Azure AD" dentro do próprio Power Automate (usando o login do dono do fluxo). Como
  vocês optaram por **não usar Premium**, a solução final é outra (Seção 6, abaixo): o backend passa
  a servir a imagem e o PDF em **links diretos e estáveis** (`/api/reports/{id}/image` e
  `/api/reports/{id}/download`), e o Power Automate — que já sabe postar no grupo hoje, porque roda
  com o login do dono do fluxo — só precisa apontar o card para esses links em vez dos links do
  OneDrive. **Vá direto para a Seção 6** para os passos finais.

---

## 1. Diagnóstico (por que a imagem não aparece)

Investiguei o pipeline completo: `backend/app/services/report_image.py` (gera o PNG offline via
Chromium/Playwright), `backend/app/routers/reports.py` (`compute_card_image_data`,
`write_report_to_delivery_folder`, `build_report_image_card`) e o `GUIA_POWER_AUTOMATE.md` (Parte I).
Achei **duas causas**, uma confirmada pelo próprio guia e outra encontrada agora no código:

### 1.1 Causa principal: link de compartilhamento do OneDrive não devolve os bytes do PNG
O fluxo atual (Parte I do guia) não envia a imagem — ele grava o PNG numa pasta do OneDrive e o
Power Automate cria um **link de compartilhamento** (`Create share link`, escopo `Organization`) que
é colado no campo `Image.url` do Adaptive Card, com um sufixo `&download=1` para tentar forçar o
Teams a baixar os bytes em vez de abrir uma página de pré-visualização. O próprio guia já documenta
isso como **"comportamento não documentado"** e principal ponto de falha (seção "Riscos conhecidos" e
item "(I) A imagem do card não aparece"). Ou seja: quando a política de DLP do tenant, o tipo de
link ou uma mudança da Microsoft impede que aquele link devolva bytes puros, o Teams mostra o quadro
quebrado — mesmo com o PNG gerado corretamente (com os dados certos) na pasta.

### 1.2 Bug adicional encontrado: botão "Solicitar Acesso" não tem para onde ir
O card realmente enviado (`build_report_image_card` em `reports.py`, linha ~1251) usa
`build_access_request_showcard()` — um `Action.ShowCard` com um mini-formulário
(`Input.Text` + `Action.Submit`) **embutido no próprio card**. Isso diverge do que o próprio
`GUIA_POWER_AUTOMATE.md` documenta no **Apêndice H**, onde "Solicitar Acesso" é um `Action.OpenUrl`
simples. Confirmei via documentação da Microsoft: **um `Action.Submit` num card postado com "Post
card in a chat or channel" (sem "wait for a response") não tem para onde mandar a resposta — o botão
falha** ([Microsoft Learn](https://learn.microsoft.com/en-us/power-automate/overview-adaptive-cards)).
Como a Parte I do guia usa exatamente essa ação (não a variante "wait for a response", de propósito,
porque ela travaria o fluxo à espera de 1 resposta), o botão "Solicitar Acesso" do card semanal,
como está hoje, **não funciona** — mesmo depois de corrigir a imagem.

---

## 2. Power Automate (ajustado) vs Python/Graph API direto

| | **Power Automate + OneDrive** (atual) | **Python + Microsoft Graph API** (recomendado) |
|---|---|---|
| Onde a imagem "mora" | Link de compartilhamento do OneDrive, injetado por `replace()` no card | Bytes do PNG **dentro da própria mensagem** (`hostedContents` do Graph) |
| Depende de política de DLP/tenant | Sim — `Organization` vs `Anyone`, comportamento de `&download=1` não documentado | Não — não usa OneDrive/SharePoint para a imagem |
| Ponto de falha extra | Gatilho de arquivo + sincronização do OneDrive + 2 "Create share link" | Nenhum — 1 chamada HTTP autenticada (app já usa Graph com client-credentials) |
| Quem já está pronto no projeto | `GUIA_POWER_AUTOMATE.md` completo, testado | `GraphClient` (`graph_client.py`) já existe e já autentica via `msal` (client-credentials) |
| Limite de tamanho da imagem | Não documentado (depende do host) | 4 MB por `hostedContents`, documentado pela Microsoft |
| Manutenção | Um fluxo no make.powerautomate.com (fora do repositório, sem versionamento) | Endpoint FastAPI, versionado no próprio repositório |

**Fontes consultadas:**
- [chatMessageHostedContent — Microsoft Graph](https://learn.microsoft.com/en-us/graph/api/resources/chatmessagehostedcontent?view=graph-rest-1.0) — hosted content é o mecanismo oficial para imagens embutidas em mensagens do Teams, limite de 4 MB.
- [Send chatMessage in a channel — Microsoft Graph](https://learn.microsoft.com/en-us/graph/api/chatmessage-post?view=graph-rest-1.0) — formato do payload (`body.content` com `<img src="../hostedContents/{id}/$value">` + array `hostedContents`).
- [Overview of adaptive cards for Teams — Power Automate](https://learn.microsoft.com/en-us/power-automate/overview-adaptive-cards) — confirma que `Action.Submit` só funciona com as variantes "wait for a response"; nas demais, o botão retorna erro.
- [Create flows that post adaptive cards to Microsoft Teams](https://learn.microsoft.com/en-us/power-automate/create-adaptive-cards) — comportamento de `Post an adaptive card ... and wait for a response` (1 resposta por execução do fluxo).

### Recomendação
**Manter o Power Automate para o fluxo de arquivo → SharePoint (Parte III, já funcional) e usar
Python/Microsoft Graph API para a entrega da imagem + botões do card semanal.** O projeto já tem
90% do necessário (`GraphClient`, credenciais client-credentials, endpoints de integração). Não é
necessário desligar nem reescrever o fluxo do Power Automate — ele continua como estava
(`/api/integrations/reports/{id}/deliver-folder`), servindo de *fallback* caso o Graph não esteja
configurado num ambiente específico.

---

## 3. O que foi implementado (aditivo — nada existente foi alterado)

Adicionei **1 método novo** em `backend/app/services/integrations/graph_client.py`:

```python
GraphClient.send_channel_message_with_image_card(
    team_id=..., channel_id=...,
    image_bytes=..., image_content_type="image/png",
    adaptive_card={...},   # opcional
)
```

Ele monta 1 chamada `POST /teams/{team_id}/channels/{channel_id}/messages` (Graph beta) com:
- `hostedContents`: os bytes do PNG em base64 — a imagem viaja **dentro** da mensagem;
- `body.content`: um `<img src="../hostedContents/1/$value">` (renderiza a imagem inline) seguido de
  um `<attachment id="card1">` (renderiza o Adaptive Card com os botões, na mesma mensagem);
- `attachments`: o Adaptive Card com os 3 botões.

E **1 endpoint novo** em `backend/app/routers/integrations.py`:

```
POST /api/integrations/reports/{report_id}/teams-image
```

Ele reaproveita `compute_card_image_data` + a mesma renderização Chromium/Playwright que já existe
(`_render_report_image_threaded`) — ou seja, **os dados da imagem (arquivos, horas, adoção, saúde)
são os mesmos calculados hoje**; a única mudança é *como* a imagem chega ao Teams. Os 3 botões:

| Botão | Ação | De onde vem a URL |
|---|---|---|
| **Abrir Playground** | `Action.OpenUrl` | `REPORT_CARD_PLAYGROUND_URL` (ou `PLAYGROUND_URL`) — já configurado hoje |
| **Solicitar Acesso** | `Action.OpenUrl` | `REPORT_CARD_ACCESS_URL` — já existe no `.env`; deve apontar para o link do fluxo **"Solicitar acesso - Teams"** (Parte III do `GUIA_POWER_AUTOMATE.md`, já funcional: `Post adaptive card and wait for a response`) |
| **Baixar Relatório (PDF)** | `Action.OpenUrl` | Endpoint do próprio backend `GET /api/reports/{id}/download` (já existe, usado hoje como *fallback* em `/reports/{id}/teams`) — não depende de link do OneDrive |

> Este endpoint **não** usa o `Action.ShowCard` (a causa do botão quebrado, item 1.2). O "Solicitar
> Acesso" abre o fluxo já pronto e testado da Parte III — o mesmo formulário (ID de rede + SPEC +
> justificativa) que grava na Lista do SharePoint e avisa o aprovador. Continua sendo um "pop-up" do
> Teams (o Adaptive Card do formulário aparece dentro do app Workflows/Teams), só que através de um
> mecanismo que a própria Microsoft garante que funciona.

### Pré-requisito para usar o novo endpoint
As mesmas variáveis que já existem no `backend\.env` para `/api/integrations/teams/messages`:
```
MS_GRAPH_TENANT_ID=...
MS_GRAPH_CLIENT_ID=...
MS_GRAPH_CLIENT_SECRET=...
MS_GRAPH_SENDER_USER=...
MS_GRAPH_TEAMS_TEAM_ID=...
MS_GRAPH_TEAMS_CHANNEL_ID=...
```
No Azure AD, o **app registration** precisa da permissão de aplicativo `ChannelMessage.Send` (Graph,
tipo *Application*, com consentimento de administrador) — a mesma exigida hoje para o botão de teste
em **Configurações & Calibração → Microsoft Graph**. Se isso já está configurado (o card de status em
`/api/integrations/graph/status` mostra `teams.messages_configured: true`), o endpoint novo já
funciona sem nenhuma configuração extra.

### Como testar
```
POST /api/integrations/reports/{id}/teams-image
Content-Type: application/json
{}
```
(campos opcionais: `download_url`, `access_url`, `team_id`, `channel_id` — todos com fallback para
as configurações do `.env`). Uma resposta `{"status": "sent", ...}` confirma que a imagem chegou
embutida na mensagem (sem depender do OneDrive).

---

## 4. Sobre o pop-up nativo do "Solicitar Acesso"

Vale registrar a pergunta que motivou a pesquisa: **dá para o botão abrir um formulário *dentro* do
card, sem precisar rodar um fluxo separado pela app Workflows?** Tecnicamente sim, mas exige um
**Bot do Teams registrado** (Azure Bot Service + Bot Framework, com um endpoint HTTP publicado para
receber os `Action.Submit`/`Action.Execute`) — é o mecanismo que teams como Approvals ou Praise usam.
Isso é uma peça de infraestrutura nova (registro de app no Teams, hospedagem do bot, aprovação do
tenant) e não uma mudança de código simples; por isso não incluí aqui, para não contrariar a
orientação de evitar alterações radicais. Se no futuro quiserem um pop-up 100% inline (sem passar
pela app Workflows), esse é o caminho — posso detalhar à parte quando fizer sentido priorizar.

Por ora, a combinação **imagem via Graph (novo endpoint) + botão "Solicitar Acesso" apontando para o
fluxo da Parte III (já pronto)** resolve os dois problemas relatados sem exigir infraestrutura nova.

---

## 5. Resumo do que mudar no dia a dia

1. Continue gerando o relatório semanal normalmente (nenhuma mudança na tela **Relatórios**).
2. Em vez de (ou além de) `deliver-folder` + fluxo do Power Automate, chame
   `POST /api/integrations/reports/{id}/teams-image` (manualmente, por um botão no dashboard, ou por
   um agendador) para postar a imagem + botões direto no canal via Graph.
3. Confirme que `REPORT_CARD_ACCESS_URL` aponta para o link do fluxo **"Solicitar acesso - Teams"**
   (Parte III do `GUIA_POWER_AUTOMATE.md` — já deve estar configurado se o botão de acesso já
   aparecia antes).
4. O fluxo do Power Automate (Parte I) pode continuar existindo como estava — não precisa desligar
   nada; é só deixar de ser o caminho principal da imagem.

---

## 6. Solução final aplicada (destino = grupo, sem Premium) — o que mudou de verdade

Como o destino é o grupo **"1:1 Ederson"**, o Power Automate continua sendo quem posta a mensagem
(ele já sabe postar em grupo, porque roda com o login do dono do fluxo). O que mudou: o backend
agora oferece **links diretos e estáveis** para a imagem e o PDF, então o Power Automate **não
precisa mais criar link de compartilhamento do OneDrive** para nenhum dos dois — eliminando o passo
frágil que causava a imagem quebrada. Sem custo, sem conector Premium, sem mexer no notebook
corporativo (é tudo código do backend, já aplicado neste projeto).

### 6.1 O que foi implementado no backend (aditivo — nada existente foi removido)

1. **Novo endpoint `GET /api/reports/{id}/image`** (`backend/app/routers/reports.py`) — gera o PNG
   do card semanal na hora (mesmo pipeline de sempre: `compute_card_image_data` +
   Chromium/Playwright offline) e devolve os bytes direto, `Content-Type: image/png`. É um link
   **estável**: não expira, não depende de política de compartilhamento do OneDrive, não tem o
   `&download=1` "não documentado". Mesmo princípio do `GET /api/reports/{id}/download` que já
   existe para o PDF.

2. **Nova variável `REPORT_BACKEND_BASE_URL`** (`backend/app/core/config.py`) — URL base do backend
   alcançável pelo Teams (ex.: `http://10.x.x.x:8000` ou um hostname interno da rede Stellantis).
   **Vazia por padrão** (nada muda se não for preenchida — comportamento 100% igual ao de antes).

3. **`write_report_to_delivery_folder` agora, SE `REPORT_BACKEND_BASE_URL` estiver preenchida**,
   grava no `.meta.json`:
   - `image_direct_url`: `{REPORT_BACKEND_BASE_URL}/api/reports/{id}/image`
   - `download_direct_url`: `{REPORT_BACKEND_BASE_URL}/api/reports/{id}/download`
   - e já substitui os dois placeholders **dentro do próprio `adaptive_card`** por esses links —
     ou seja, o campo `adaptive_card` do sidecar já sai **pronto para postar verbatim**, sem o
     Power Automate precisar trocar nada.

4. ~~"Corrigido" o botão "Solicitar Acesso"~~ **— correção revertida.** Cheguei a trocar o
   `Action.ShowCard` por um link simples, achando (pela documentação genérica do
   `GUIA_POWER_AUTOMATE.md`) que o formulário embutido não funcionava. **Ao abrir o fluxo real no
   Power Automate, vi que ele não segue exatamente o guia**: em vez de "Post card in a chat or
   channel", usa **"Post adaptive card and wait for a response"**, seguido de **Create item**
   (grava em `Solicitações de Acesso a Workspace` no SharePoint: `Title=data.spec`,
   `IDRede=data.idrede`, `Justificativa=data.justificativa`, `Solicitante=responder.displayName`,
   `Email=responder.email`) e **Post message in a chat or channel** (avisa o aprovador). Ou seja: o
   `Action.ShowCard` **foi projetado de propósito** para essa combinação — o formulário embutido no
   próprio card semanal já é o pop-up de solicitação de acesso, sem precisar de um fluxo separado
   nem da app Workflows. Revertido para o estado original (`build_access_request_showcard()`), sem
   mudança nenhuma nesse botão.

### 6.2 O que fazer agora (2 passos)

**Passo 1 — preencher 1 variável no `backend\.env` do servidor onde o backend roda:**
```
REPORT_BACKEND_BASE_URL=http://<host-ou-ip-do-backend>:<porta>
```
Tem que ser um endereço que o Teams consiga alcançar (a mesma rede/URL que já é usada hoje para o
link de fallback do PDF em `/reports/{id}/teams`, então se aquele link já funciona de algum lugar,
este endereço é o mesmo). Depois: `restart_services.bat`.

**Passo 2 — simplificar o fluxo do Power Automate** (Parte I do `GUIA_POWER_AUTOMATE.md`): como o
`adaptive_card` do sidecar já chega **pronto** (com os links diretos embutidos), o fluxo fica bem
mais simples — **remova** as ações `Meta_PDF`, `Link_PDF`, `Meta_Imagem`, `Link_Imagem` e o Compose
`Card final` (I.4 e I.5 do guia não são mais necessárias) e troque a ação **"Post card in a chat or
channel"** (I.7) para usar o Adaptive Card direto:
- **Adaptive Card:** conteúdo dinâmico `adaptive_card` (saída do **Parse JSON**, não mais do
  "Card final") · **Post in:** **Group chat** → selecione **"1:1 Ederson"**.

Isso reduz o fluxo de ~7 ações para 2 (Parse JSON → Post card), e remove de vez a dependência do
link de compartilhamento do OneDrive tanto para a imagem quanto para o PDF.

> **Se preferir não mexer no fluxo agora:** funciona também sem simplificar nada — é só trocar, no
> passo **I.5 (`Card final`)**, os valores usados no `replace()` de `body('Link_PDF')?['webUrl']` e
> `concat(body('Link_Imagem')?['webUrl'], '&download=1')` para
> `body('Parse_JSON')?['download_direct_url']` e `body('Parse_JSON')?['image_direct_url']`
> respectivamente — 1 edição pequena, mantém a estrutura atual do fluxo.

### 6.3 O que foi feito de verdade no fluxo "HUB - Relatorios Teams" (make.powerautomate.com)

Entrei no fluxo real (não foi preciso o notebook corporativo — Power Automate é web) e apliquei a
**opção sem custo, com fallback automático** (a alternativa do parágrafo acima), sem remover nenhuma
ação existente:

- **Ação `Card Final` (Compose):** a expressão `replace(...)` passou a preferir
  `body('Parse_JSON')?['download_direct_url']` / `body('Parse_JSON')?['image_direct_url']` quando
  existirem, e só cai para `body('Link_PDF')?['webUrl']` / `body('Link_Imagem')?['webUrl'] +
  '&download=1'` quando não existirem (via `if(empty(...), ...)`). **Nada mais foi alterado** —
  `Meta_PDF`, `Link_PDF`, `Meta_Imagem`, `Link_Imagem` continuam no fluxo como estavam (servem de
  fallback automático até `REPORT_BACKEND_BASE_URL` ser configurada no `.env`).
- Fluxo salvo com sucesso ("Your flow is ready to go").
- **Descoberta importante:** o fluxo real não é o "Post card in a chat or channel" simples do
  guia — é **"Post adaptive card and wait for a response"** → **Create item** (SharePoint,
  `Solicitações de Acesso a Workspace`) → **Post message in a chat or channel** (avisa o
  aprovador), tudo num único fluxo, postando para o **Group chat "1:1 Ederson"**. Por isso o botão
  "Solicitar Acesso" (ShowCard embutido) já está correto — ver correção na Seção 6.1, item 4.

**O que ainda falta para a imagem parar de quebrar:** preencher `REPORT_BACKEND_BASE_URL` no
`backend\.env` (Passo 1, acima) e reiniciar os serviços. Sem isso, o fluxo continua se comportando
exatamente como antes (fallback para o link do OneDrive) — a mudança no Power Automate já está
pronta e é retrocompatível, só "liga" quando o backend passar a enviar os links diretos.
