# Entrega automatica de PNG para o Teams (pasta monitorada)

Feature nova: o HUB monitora uma pasta local e, quando encontra um PNG **novo**
(nunca enviado antes, verificado por conteudo/sha256), manda automaticamente
esse arquivo para um chat/canal do Teams via Playwright. Nao depende de o
relatorio ter sido gerado pelo proprio HUB -- serve para qualquer PNG que
apareca na pasta (ex.: um relatorio agendado externamente toda segunda-feira).

Desligada por padrao (`TEAMS_PNG_DELIVERY_ENABLED=false`).

## Como ativar

Edite `backend/.env` (bloco ja adicionado, comentado, no final do arquivo):

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

| Variavel | Descricao |
|---|---|
| `TEAMS_PNG_DELIVERY_ENABLED` | `true`/`false`. Liga/desliga a feature inteira. |
| `TEAMS_PNG_WATCH_FOLDER` | Pasta onde o PNG e gerado/depositado. O HUB sempre pega o PNG mais recente dessa pasta. |
| `TEAMS_PNG_DELIVERY_CHAT_NAME` | Nome exato do chat/canal no Teams Web. Vazio = usa `TEAMS_DELIVERY_CHAT_NAME` (mesmo do relatorio simplificado). |
| `TEAMS_PNG_DELIVERY_TEXT` | Texto enviado junto com o arquivo. Vazio = mensagem padrao com o nome do arquivo. |
| `TEAMS_PNG_DELIVERY_MODE` | `schedule` (dia/hora fixos) ou `continuous` (monitoramento continuo por intervalo). |
| `TEAMS_PNG_DELIVERY_DAY_OF_WEEK` | Usado so no modo `schedule`. Ex.: `monday`, `tuesday`... |
| `TEAMS_PNG_DELIVERY_TIME` | Usado so no modo `schedule`. Formato `HH:MM` (24h). |
| `TEAMS_PNG_DELIVERY_POLL_INTERVAL_SECONDS` | Usado so no modo `continuous`. De quantos em quantos segundos verifica a pasta. |

Depois de editar o `.env`, **reinicie os dois processos** (a feature toca
codigo em ambos):

1. Backend (`uvicorn`, porta 8000) -- roda o verificador (`schedule_runner.py`).
2. Agente local (`python -m app.cli.local_agent`) -- executa a entrega real via
   Playwright.

O dashboard (porta 5173) nao precisa reiniciar.

## Como funciona

- **Deteccao "e novo?"**: o arquivo mais recente da pasta e comparado por
  hash sha256 com o ultimo enviado. So reenvia se o conteudo mudar (renomear
  o mesmo PNG nao dispara reenvio; gerar um PNG diferente, sim).
- **Modo `schedule`**: so verifica a pasta no dia/hora configurados (uma vez
  por semana). Se o arquivo la dentro for novo, cria a tarefa de envio.
- **Modo `continuous`**: verifica a pasta a cada N segundos, o dia/hora todo,
  e envia assim que aparecer um PNG novo.
- **Estado**: guardado em `backend/data/teams_png_delivery_state.json`
  (sha256 do ultimo enviado + timestamps de checagem). Nao precisa mexer
  nesse arquivo manualmente; apagar o arquivo forca o proximo PNG encontrado
  a ser reenviado, como um "reset".
- **Falha no envio**: o hash so e gravado como "enviado" apos a confirmacao
  de sucesso do Playwright. Se falhar, o modo `continuous` tenta de novo no
  proximo intervalo; no modo `schedule` a proxima tentativa so ocorre na
  proxima janela semanal (limitacao conhecida -- avise se quiser retry no
  mesmo dia em caso de erro).

## Testado

Logica de deteccao/dedup validada localmente (PNG novo enfileira; checagem
imediata seguinte nao enfileira; apos marcar como enviado nao reenvia o
mesmo conteudo mesmo passado o intervalo; PNG realmente novo enfileira de
novo). Faltando: teste end-to-end real apos ativar no `.env` e reiniciar os
processos (enviar um PNG de verdade para o Teams).
