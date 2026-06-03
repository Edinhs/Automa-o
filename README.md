# Stellantis Automation HUB

Plataforma corporativa integrada para automação inteligente de uploads de arquivos, conversão nativa para PDF e monitoramento ativo com rastro operacional completo no **Stellantis GenAI Playground**.

---

## 🛠️ Visão Geral da Arquitetura

O sistema é desenhado de forma distribuída para garantir isolamento e máxima eficiência operacional em ambientes corporativos Windows:

```
[ Diretório Monitorado ]
           │
           ▼ (Varredura Ativa)
┌──────────────────────┐
│  Agente Local (CLI)  │ ➔ Conversão HEADLESS nativa com LibreOffice
└──────────────────────┘
           │
           ▼ (Cópia / Staging)
┌──────────────────────┐
│   Banco SQLite DB    │ ➔ Rastreabilidade de status, logs e erros
└──────────────────────┘
           │
           ▼ (Envio Seguro)
┌──────────────────────┐
│ Playwright Automator │ ➔ Execução visible/headless no Playground
└──────────────────────┘
           │
           ▼ (Visualização)
┌──────────────────────┐
│  Dashboard React UI  │ ➔ Painel de controle e auditoria em tempo real
└──────────────────────┘
```

---

## 🚀 Como Iniciar os Serviços no Windows

A pasta raiz do projeto possui arquivos de lote (`.bat`) para facilitar o controle de execução em background:

1. **`start_all.bat`**: Inicia automaticamente o banco de dados, o servidor backend FastAPI (porta 8000), o Dashboard React UI (porta 5173) e o Agente Local CLI em janelas de terminal dedicadas.
2. **`stop_all.bat`**: Finaliza com segurança todos os processos em execução no sistema.
3. **`restart_services.bat`**: Reinicia todos os módulos operacionais limpando caches temporários de execução.
4. **`start_agent.bat`**: Executa apenas o Agente de background CLI para monitoramento contínuo das pastas de rede vinculadas.

---

## 📊 Guia de Uso das Funcionalidades

### 1. Painel Executivo (Aba Home)
* **Monitoramento Compacto**: Permite acompanhar os principais indicadores operacionais (Uploads, Taxa de Sucesso, Erros Resolvidos).
* **Grade Dinâmica**: Clicando no botão **⚙️ Personalizar Dashboard** no canto superior direito, você pode arrastar qualquer cartão métrico, gráfico de Pizza de erros resolvidos, ou tabelas para mudar a ordem, além de redimensionar a largura lateral usando os botões `+/-`. O layout personalizado é gravado automaticamente no seu navegador.
* **Erros Resolvidos**: O gráfico em pizza demonstra a eficiência de resolução de problemas, refletindo imediatamente as ações manuais feitas sobre arquivos com falha.

### 2. Gerenciamento de Automações
* **Nova Automação**: Crie monitoramentos de diretórios locais apontando para caminhos de rede (ex: `//servidor/pasta`).
* **Upload Manual**: Se precisar enviar um documento de forma urgente sem esperar a varredura da pasta, arraste e solte o arquivo diretamente nesta ação e selecione o Workspace de destino.

### 3. Auditoria de Arquivos
* **Timeline e Logs**: Cada arquivo possui um botão **Detalhes** e **Logs** para checar os metadados brutos (SHA256, extensões, datas) e os logs em tempo real disparados pelo robô Playwright.
* **Reprocessar**: Caso um arquivo falhe por timeout ou erro na rede do Playground, clique em **Reprocessar** para recolocá-lo na fila imediatamente (ele será convertido para PDF de forma nativa e enviado novamente).
* **Resolvido**: Ação manual de segurança para marcar arquivos pendentes/com erros como resolvidos, alimentando o painel de Erros Resolvidos e liberando-os da fila.

---

## ⚙️ Calibração de Parâmetros Operacionais

Na aba **Configurações**, você pode ajustar o comportamento reativo do Stellantis HUB:
* **Tamanho do lote**: Define quantos arquivos o robô Playwright processará por ciclo de upload. Lotes de **3 a 5 arquivos** são altamente recomendados para evitar sobrecargas de processamento.
* **Modo Playwright**: 
  - **Headless (Recomendado)**: Executa a automação de forma silenciosa e invisível em background.
  - **Visível (Visible/Headful)**: Abre uma janela real do navegador Chromium na tela. Excelente para auditar o fluxo e diagnosticar problemas ou validar logins de rede corporativos.
* **Frequência de Polling**: Calibre a taxa com que a Home atualiza seus indicadores junto ao servidor backend (padrão de **8 segundos** para equilíbrio ideal de recursos).

---

© 2026 Stellantis GenAI Platform. Todos os direitos reservados.
