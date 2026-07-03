(function () {
  console.log("[Custom Automation] Injetor carregado.");

  // Configurações e estados locais
  const CONFIG = {
    project: "J3U",
    apiPrefix: "/api/custom-automations"
  };
  
  let statusInterval = null;
  let logInterval = null;

  // Função utilitária para chamar o backend com o cabeçalho do ambiente correto
  async function apiRequest(method, path, body = null) {
    const headers = {
      "Content-Type": "application/json"
    };
    // Mantém o cabeçalho X-App-Environment se estiver definido no localStorage do HUB
    const currentEnv = localStorage.getItem("hub_environment") || "operational";
    headers["X-App-Environment"] = currentEnv;
    
    // Obtém o token JWT ou o agent token se necessário (usando helpers do hub se disponíveis)
    const token = localStorage.getItem("hub_token");
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const options = { method, headers };
    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(`${path}`, options);
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || "Erro na requisicao");
    }
    return response.json();
  }

  // Monitora alterações no DOM para injetar a aba na sidebar
  const observer = new MutationObserver((mutations) => {
    const sidebar = document.querySelector("nav");
    if (sidebar && !document.getElementById("custom-menu-item")) {
      injectMenuItem(sidebar);
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });

  // Cria e injeta o botão de menu na sidebar
  function injectMenuItem(sidebar) {
    // Localiza os botões existentes
    const buttons = sidebar.querySelectorAll("button, a");
    if (buttons.length === 0) return;

    // Clona o estilo de um botão inativo existente
    const refButton = buttons[buttons.length - 1]; // Geralmente configurações ou lixeira
    
    const customButton = document.createElement("button");
    customButton.id = "custom-menu-item";
    customButton.className = "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-white/5";
    
    // Icone SVG para a aba (Engrenagem com pasta / automação)
    customButton.innerHTML = `
      <svg class="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75" />
      </svg>
      <span>Automação IPC</span>
    `;

    // Adiciona o manipulador de clique
    customButton.addEventListener("click", (e) => {
      e.preventDefault();
      activateCustomTab(customButton, sidebar);
    });

    // Insere antes do botão de Configurações/Lixeira se possível, ou simplesmente anexa no final
    sidebar.appendChild(customButton);
    
    // Captura cliques nos outros botões para desativar a aba customizada se o usuário sair
    buttons.forEach(btn => {
      btn.addEventListener("click", () => {
        customButton.className = "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-white/5";
        clearIntervals();
      });
    });
  }

  function clearIntervals() {
    if (statusInterval) clearInterval(statusInterval);
    if (logInterval) clearInterval(logInterval);
  }

  // Ativa a nossa aba e limpa a área de conteúdo do React
  function activateCustomTab(activeBtn, sidebar) {
    // 1. Remove classe ativa dos outros botões
    sidebar.querySelectorAll("button, a").forEach(btn => {
      if (btn !== activeBtn) {
        btn.className = "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-white/5";
      }
    });

    // 2. Ativa o estilo visual no nosso botão
    activeBtn.className = "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition bg-blue-600 text-white";

    // 3. Localiza a área de conteúdo principal (geralmente uma tag main ou o contêiner ao lado da sidebar)
    // Procuramos o contêiner principal na estrutura do Dashboard
    let mainContent = document.querySelector("main");
    if (!mainContent) {
      // Se não houver tag main, busca o contêiner de maior tamanho à direita da sidebar
      const containers = document.querySelectorAll(".flex-1, .w-full");
      containers.forEach(el => {
        if (el !== sidebar && el.offsetWidth > 400) {
          mainContent = el;
        }
      });
    }

    if (!mainContent) return;

    // Limpa intervalos antigos se houver
    clearIntervals();

    // 4. Renderiza a nossa interface customizada
    renderDashboardUI(mainContent);
  }

  // Renderiza o painel de automação personalizada IPC no contêiner principal
  function renderDashboardUI(container) {
    container.innerHTML = `
      <div class="p-6 max-w-7xl mx-auto space-y-6">
        <!-- Cabeçalho -->
        <div class="flex justify-between items-start border-b border-zinc-200 dark:border-zinc-800 pb-5">
          <div>
            <h1 class="text-2xl font-semibold text-zinc-900 dark:text-white">Automação de Workspace IPC</h1>
            <p class="text-sm text-zinc-500 mt-1">Gerencie a extração inicial de VFs (VFList) e a aplicação incremental de Change Requests (CRs) de rede para o projeto.</p>
          </div>
          <div class="flex items-center gap-3">
            <select id="project-select" class="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-white">
              <option value="J3U" selected>Projeto J3U</option>
            </select>
            <button id="btn-run" class="flex items-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 text-sm font-medium transition shadow-sm">
              <svg id="run-spinner" class="hidden animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span id="run-text">Executar Automação</span>
            </button>
          </div>
        </div>

        <!-- Status e Informações Rápidas -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div class="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-sm">
            <h3 class="text-sm font-medium text-zinc-500">Status do Atualizador</h3>
            <div class="flex items-center gap-2 mt-2">
              <span id="status-badge-indicator" class="h-2.5 w-2.5 rounded-full bg-zinc-400"></span>
              <span id="status-badge-text" class="text-lg font-medium text-zinc-900 dark:text-white">Carregando...</span>
            </div>
            <p id="status-subtext" class="text-xs text-zinc-400 mt-1">Verificando execuções em segundo plano.</p>
          </div>
          <div class="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-sm">
            <h3 class="text-sm font-medium text-zinc-500">Workspace Vinculado</h3>
            <div class="text-lg font-medium text-zinc-900 dark:text-white mt-2" id="info-workspace-id">ID: --</div>
            <p class="text-xs text-zinc-400 mt-1">Detectado no banco SQLite local.</p>
          </div>
          <div class="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-sm">
            <h3 class="text-sm font-medium text-zinc-500">Total de VFs Monitoradas</h3>
            <div class="text-lg font-medium text-zinc-900 dark:text-white mt-2" id="info-vfs-count">0</div>
            <p class="text-xs text-zinc-400 mt-1">Cadastradas na baseline ativa.</p>
          </div>
        </div>

        <!-- Layout Central: Console Logs e Tabelas -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <!-- Console Logs (Esquerda/Topo) -->
          <div class="lg:col-span-8 space-y-6">
            <div class="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-sm flex flex-col">
              <div class="flex justify-between items-center pb-3 border-b border-zinc-200 dark:border-zinc-800">
                <h3 class="text-sm font-medium text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
                  <span class="h-2 w-2 rounded-full bg-emerald-500"></span> Console de Execução (ipc_updater.log)
                </h3>
                <button id="btn-clear-logs" class="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-white transition">Limpar Tela</button>
              </div>
              <pre id="log-console" class="bg-zinc-950 text-zinc-100 font-mono p-4 rounded-lg border border-zinc-800 h-80 overflow-y-auto mt-4 text-xs select-text whitespace-pre-wrap">Nenhum log carregado ainda...</pre>
            </div>
          </div>

          <!-- Ações e Parâmetros (Direita) -->
          <div class="lg:col-span-4 space-y-6">
            <div class="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-sm space-y-4">
              <h3 class="text-sm font-medium text-zinc-700 dark:text-zinc-300 border-b border-zinc-200 dark:border-zinc-800 pb-2">Sobre esta Automação</h3>
              <div class="text-xs text-zinc-500 space-y-2 leading-relaxed">
                <p>1. <strong>Primeira Execução</strong>: O script localiza o arquivo <code>VFList*.docx</code> no Spec, extrai todas as VFs em arquivos individuais e cria a baseline (CREATE).</p>
                <p>2. <strong>Execuções Subsequentes</strong>: O script ignora o arquivo <code>VFList</code> e passa a monitorar e aplicar de forma incremental as Change Requests (CRs) do tipo <code>*IPC__SoftwareFactory.zip</code> (UPDATE).</p>
                <p>3. <strong>Sincronização com o HUB</strong>: Todos os arquivos de VFs atualizados na pasta local são enviados automaticamente para o Playground do Stellantis pelo Local Agent.</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Tabelas de Histórico -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <!-- Tabela VFs -->
          <div class="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-sm">
            <h3 class="text-sm font-medium text-zinc-700 dark:text-zinc-300 border-b border-zinc-200 dark:border-zinc-800 pb-3 mb-4">VFs no Workspace</h3>
            <div class="overflow-x-auto max-h-80 overflow-y-auto">
              <table class="min-w-full text-xs text-left divide-y divide-zinc-200 dark:divide-zinc-800">
                <thead>
                  <tr class="text-zinc-500 font-medium bg-zinc-50 dark:bg-zinc-800/50">
                    <th class="px-4 py-2">Nome da VF</th>
                    <th class="px-4 py-2">Versão</th>
                    <th class="px-4 py-2">Revisão</th>
                    <th class="px-4 py-2">Última Atualização</th>
                  </tr>
                </thead>
                <tbody id="vfs-table-body" class="divide-y divide-zinc-200 dark:divide-zinc-800">
                  <tr>
                    <td colspan="4" class="px-4 py-4 text-center text-zinc-400">Nenhuma VF carregada.</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Tabela CRs -->
          <div class="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-sm">
            <h3 class="text-sm font-medium text-zinc-700 dark:text-zinc-300 border-b border-zinc-200 dark:border-zinc-800 pb-3 mb-4">Change Requests Aplicadas (Histórico)</h3>
            <div class="overflow-x-auto max-h-80 overflow-y-auto">
              <table class="min-w-full text-xs text-left divide-y divide-zinc-200 dark:divide-zinc-800">
                <thead>
                  <tr class="text-zinc-500 font-medium bg-zinc-50 dark:bg-zinc-800/50">
                    <th class="px-4 py-2">Código CR</th>
                    <th class="px-4 py-2">Pacote ZIP</th>
                    <th class="px-4 py-2">Aplicada Em</th>
                    <th class="px-4 py-2">Status</th>
                  </tr>
                </thead>
                <tbody id="crs-table-body" class="divide-y divide-zinc-200 dark:divide-zinc-800">
                  <tr>
                    <td colspan="4" class="px-4 py-4 text-center text-zinc-400">Nenhuma CR aplicada ainda.</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    `;

    // Associa eventos
    document.getElementById("btn-run").addEventListener("click", runAutomation);
    document.getElementById("btn-clear-logs").addEventListener("click", () => {
      document.getElementById("log-console").textContent = "";
    });

    // Inicia pollings
    loadHistory();
    pollStatus();
    loadLogs();
    
    statusInterval = setInterval(pollStatus, 3000);
    logInterval = setInterval(loadLogs, 2500);
  }

  // Carrega e desenha tabelas de histórico
  async function loadHistory() {
    try {
      const data = await apiRequest("GET", `${CONFIG.apiPrefix}/ipc/history?project=${CONFIG.project}`);
      document.getElementById("info-workspace-id").textContent = `ID: ${data.workspace_id}`;
      
      const vfs = data.vfs || {};
      const crs = data.change_requests || [];

      // Renderiza VFs
      const vfsBody = document.getElementById("vfs-table-body");
      const vfsKeys = Object.keys(vfs);
      document.getElementById("info-vfs-count").textContent = vfsKeys.length;
      
      if (vfsKeys.length > 0) {
        vfsBody.innerHTML = vfsKeys.map(name => `
          <tr class="hover:bg-zinc-50 dark:hover:bg-white/5 transition">
            <td class="px-4 py-2 font-mono text-zinc-900 dark:text-zinc-100 font-medium">${name}</td>
            <td class="px-4 py-2">${vfs[name].version}</td>
            <td class="px-4 py-2">${vfs[name].revision}</td>
            <td class="px-4 py-2 text-zinc-400">${vfs[name].updated_at}</td>
          </tr>
        `).join("");
      } else {
        vfsBody.innerHTML = `<tr><td colspan="4" class="px-4 py-4 text-center text-zinc-400">Nenhuma VF na baseline. Rode a automacao pela primeira vez.</td></tr>`;
      }

      // Renderiza CRs
      const crsBody = document.getElementById("crs-table-body");
      if (crs.length > 0) {
        crsBody.innerHTML = crs.map(cr => `
          <tr class="hover:bg-zinc-50 dark:hover:bg-white/5 transition">
            <td class="px-4 py-2 font-medium text-blue-600 dark:text-blue-400 font-mono">${cr.cr_code}</td>
            <td class="px-4 py-2 text-zinc-500 font-mono truncate max-w-xs" title="${cr.package_zip_name}">${cr.package_zip_name}</td>
            <td class="px-4 py-2 text-zinc-400">${cr.applied_at}</td>
            <td class="px-4 py-2">
              <span class="inline-flex items-center rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/10">
                ${cr.status}
              </span>
            </td>
          </tr>
        `).join("");
      } else {
        crsBody.innerHTML = `<tr><td colspan="4" class="px-4 py-4 text-center text-zinc-400">Nenhuma Change Request processada.</td></tr>`;
      }
    } catch (err) {
      console.error("Falha ao carregar historico:", err);
    }
  }

  // Verifica se o script está rodando em background
  async function pollStatus() {
    try {
      const data = await apiRequest("GET", `${CONFIG.apiPrefix}/ipc/status?project=${CONFIG.project}`);
      const btn = document.getElementById("btn-run");
      const spinner = document.getElementById("run-spinner");
      const text = document.getElementById("run-text");
      const badge = document.getElementById("status-badge-indicator");
      const badgeText = document.getElementById("status-badge-text");
      const subtext = document.getElementById("status-subtext");

      if (data.is_running) {
        btn.disabled = true;
        btn.className = "flex items-center gap-2 rounded-lg bg-zinc-400 dark:bg-zinc-700 text-white px-4 py-2 text-sm font-medium transition cursor-not-allowed";
        spinner.classList.remove("hidden");
        text.textContent = `Rodando (${data.mode})...`;
        
        badge.className = "h-2.5 w-2.5 rounded-full bg-amber-500 animate-pulse";
        badgeText.textContent = "Processando";
        subtext.textContent = `Iniciado em ${data.started_at}`;
      } else {
        btn.disabled = false;
        btn.className = "flex items-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 text-sm font-medium transition shadow-sm";
        spinner.classList.add("hidden");
        text.textContent = "Executar Automação";
        
        badge.className = "h-2.5 w-2.5 rounded-full bg-emerald-500";
        badgeText.textContent = "Pronto";
        subtext.textContent = "Nenhuma execucao ativa em segundo plano.";
      }
    } catch (err) {
      console.error("Falha ao consultar status:", err);
    }
  }

  // Carrega e atualiza logs de execucao no console
  async function loadLogs() {
    try {
      const data = await apiRequest("GET", `${CONFIG.apiPrefix}/ipc/logs?project=${CONFIG.project}`);
      const consoleEl = document.getElementById("log-console");
      if (consoleEl) {
        const atBottom = consoleEl.scrollHeight - consoleEl.clientHeight <= consoleEl.scrollTop + 50;
        consoleEl.textContent = data.logs;
        // Auto scroll para o final se o usuário já estava embaixo
        if (atBottom) {
          consoleEl.scrollTop = consoleEl.scrollHeight;
        }
      }
    } catch (err) {
      console.error("Falha ao carregar logs:", err);
    }
  }

  // Executa o disparo da automação
  async function runAutomation() {
    try {
      const btn = document.getElementById("btn-run");
      btn.disabled = true;
      
      const result = await apiRequest("POST", `${CONFIG.apiPrefix}/ipc/run`, { project: CONFIG.project });
      console.log("Automação disparada com sucesso:", result);
      
      // Atualiza status e historico imediatamente
      pollStatus();
      loadHistory();
    } catch (err) {
      alert(`Falha ao disparar automacao: ${err.message}`);
      pollStatus();
    }
  }

})();
