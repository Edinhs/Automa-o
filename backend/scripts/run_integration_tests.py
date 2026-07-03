"""
Teste de integracao ao vivo do Automation HUB (ambiente developer).

Requer o backend (porta 8000) e o agente local em execucao. Exercita, ponta a
ponta e sem navegador (automacao em modo monitor_only):

  workspace -> automacao -> arquivos fisicos -> run_now -> o agente local varre,
  faz hash (SHA256), deduplica e registra os arquivos -> relatorio XLSX persistido
  -> fluxo da Lixeira (soft-delete / restaurar / exclusao definitiva em cascata).

Pode rodar de qualquer diretorio: os caminhos sao resolvidos a partir de backend/.
Usa o X-Agent-Token (caminho de auth do agente); o usuario da sessao da tarefa de
upload e resolvido pelo backend (admin ativo) via fallback.
"""
import os
import sys
import time
import shutil
import hashlib
import requests
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
HEADERS = {
    "X-App-Environment": "developer",
    "X-Agent-Token": "local-dev-agent-token",
}

# backend/ = pai da pasta scripts/ (resolve mesmo rodando de outro cwd).
BACKEND_DIR = Path(__file__).resolve().parents[1]
MONITOR_FOLDER = BACKEND_DIR / "data" / "developer" / "test_monitor_folder"
MONITOR_FOLDER.mkdir(parents=True, exist_ok=True)


def print_step(name):
    print("\n" + "=" * 60)
    print(f" STEP: {name}")
    print("=" * 60)


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    # 1. Autenticacao opcional (apenas se AUTH_DISABLED=false). Por padrao a release
    #    sobe sem login e o X-Agent-Token ja autentica as rotas do agente.
    resp = session.get(f"{BASE_URL}/api/trash/summary")
    if resp.status_code == 401:
        print("Autenticacao exigida. Fazendo login...")
        login_resp = session.post(f"{BASE_URL}/api/auth/login", json={"username": "TA25413", "password": ""})
        if login_resp.status_code == 200:
            token = login_resp.json().get("access_token")
            session.headers.update({"Authorization": f"Bearer {token}"})
            print("Login efetuado com sucesso.")
        else:
            print(f"Erro no login: {login_resp.status_code} - {login_resp.text}")
            sys.exit(1)

    # 2. Criar Workspace de Teste
    print_step("Criando Workspace de Teste")
    resp = session.post(f"{BASE_URL}/api/workspaces", json={
        "name": "WS Teste Automatizado Antigravity",
        "description": "Workspace temporario para testes de integracao",
    })
    assert resp.status_code == 200, f"Erro ao criar workspace: {resp.text}"
    workspace = resp.json()
    workspace_id = workspace["id"]
    print(f"Workspace criado: ID={workspace_id}, Name={workspace['name']}")

    # 3. Criar Automacao de Teste (monitor_only => sem navegador/Playground)
    print_step("Criando Automacao de Teste")
    file_types = [{"extension": e, "enabled": True} for e in ("docx", "xlsx", "pdf", "txt", "csv")]
    resp = session.post(f"{BASE_URL}/api/automations", json={
        "name": "Auto Teste Lixeira e Arquivos",
        "description": "Automacao temporaria de testes",
        "type": "folder_monitoring",
        "folder_path": str(MONITOR_FOLDER),
        "workspace_id": workspace_id,
        "batch_size": 5,
        "monitor_only": True,
        "file_types": file_types,
    })
    assert resp.status_code == 200, f"Erro ao criar automacao: {resp.text}"
    automation = resp.json()
    automation_id = automation["id"]
    print(f"Automacao criada: ID={automation_id}, Name={automation['name']}, Folder={MONITOR_FOLDER}")

    # 4. Criar Arquivos Fisicos de Teste
    print_step("Criando Arquivos Fisicos na Pasta Monitorada")
    for f in MONITOR_FOLDER.iterdir():
        f.unlink()
    test_files = ["doc1.docx", "planilha1.xlsx", "relatorio1.pdf"]
    expected_hashes = {}
    for fname in test_files:
        content = f"Conteudo de teste para o arquivo {fname}".encode("utf-8")
        (MONITOR_FOLDER / fname).write_bytes(content)
        expected_hashes[fname] = hashlib.sha256(content).hexdigest()
        print(f"  Criado: {MONITOR_FOLDER / fname} (sha256={expected_hashes[fname][:12]}...)")

    # 5. Disparar Automacao (acao run_now -> cria a tarefa de upload)
    print_step("Disparando Automacao (run_now)")
    resp = session.post(f"{BASE_URL}/api/automations/{automation_id}/actions/run_now", json={"action": "run_now"})
    assert resp.status_code == 200, f"Erro ao disparar automacao: {resp.text}"
    trigger_res = resp.json()
    task_id = trigger_res.get("task_id") or (trigger_res.get("task_ids") or [None])[0]
    print(f"Tarefa de upload criada no backend: ID={task_id} (status={trigger_res.get('status')})")

    # 6. Aguardar o agente local varrer/registrar os arquivos (com timeout)
    print_step("Aguardando o Agente Local processar a tarefa")
    files_list = []
    task_completed = False
    for i in range(30):
        time.sleep(2)
        files_resp = session.get(f"{BASE_URL}/api/files", params={"limit": 50, "workspace_id": workspace_id})
        if files_resp.status_code == 200:
            data = files_resp.json()
            files_list = data if isinstance(data, list) else data.get("items", [])
        aut_resp = session.get(f"{BASE_URL}/api/automations/{automation_id}")
        aut_status = aut_resp.json().get("status") if aut_resp.status_code == 200 else None
        print(f"  t+{(i + 1) * 2:>3}s  arquivos={len(files_list)}  automacao={aut_status}")
        if len(files_list) >= 3 and aut_status in ("completed", "manual_review", "failed"):
            task_completed = True
            break

    assert task_completed, "O agente local nao processou a tarefa a tempo ou os arquivos nao foram cadastrados."
    for f in files_list:
        print(f"  Arquivo: ID={f['id']}, Name={f.get('file_name')}, Status={f.get('status')}, sha={(f.get('content_sha256') or '')[:12]}")

    # 6b. Conferir que os hashes batem com o disco
    db_hashes = {f.get("file_name"): f.get("content_sha256") for f in files_list}
    matched = sum(1 for n, h in expected_hashes.items() if db_hashes.get(n) == h)
    assert matched == len(expected_hashes), f"SHA256 divergente: {matched}/{len(expected_hashes)} bateram."
    print(f"  SHA256 confere com o disco: {matched}/{len(expected_hashes)}.")

    # 7. Gerar Relatorio (XLSX) e validar o arquivo fisico
    print_step("Gerando Relatorio de Execucao (XLSX)")
    resp = session.post(f"{BASE_URL}/api/reports", json={
        "report_type": "relatorio geral",
        "file_format": "xlsx",
        "environment_mode": "operational",  # gate=salvar (grava na pasta de relatorios do ambiente do header)
        "period_start": "2026-06-01T00:00:00",
        "period_end": "2026-06-30T23:59:59",
    })
    assert resp.status_code == 200, f"Erro ao criar relatorio: {resp.text}"
    report_env = resp.json()
    report = report_env.get("report") or {}
    report_id = report.get("id")
    report_file_path = report.get("file_path")
    assert report_id, f"Relatorio nao retornou id: {report_env}"
    print(f"Relatorio gerado: ID={report_id}, FilePath={report_file_path}")

    if report_file_path:
        absolute_report_path = report_file_path if os.path.isabs(report_file_path) else os.path.abspath(os.path.join(str(BACKEND_DIR), report_file_path))
        print(f"Verificando arquivo fisico de relatorio em: {absolute_report_path}")
        assert os.path.exists(absolute_report_path), f"Arquivo do relatorio nao foi criado fisicamente: {absolute_report_path}"
        print(f"  Sucesso: arquivo do relatorio existe no disco ({os.path.getsize(absolute_report_path)} bytes).")

    # Tambem valida o endpoint de download
    dl = session.get(f"{BASE_URL}/api/reports/{report_id}/download")
    assert dl.status_code == 200 and len(dl.content) > 0, f"Falha no download do relatorio: {dl.status_code}"
    print(f"  Download do relatorio OK ({len(dl.content)} bytes).")

    # 8. Fluxo da Lixeira (soft-delete)
    print_step("Testando soft-delete (Lixeira)")
    session.delete(f"{BASE_URL}/api/automations/{automation_id}")
    session.delete(f"{BASE_URL}/api/workspaces/{workspace_id}")
    print("  Itens deletados logicamente (soft-delete).")

    resp = session.get(f"{BASE_URL}/api/trash")
    assert resp.status_code == 200, f"Erro ao ler lixeira: {resp.text}"
    trash_items = resp.json().get("items", [])
    ws_in_trash = any(it["entity_type"] == "workspace" and it["id"] == workspace_id for it in trash_items)
    auto_in_trash = any(it["entity_type"] == "automation" and it["id"] == automation_id for it in trash_items)
    assert ws_in_trash, "Workspace nao encontrado na lixeira."
    assert auto_in_trash, "Automacao nao encontrada na lixeira."
    print("  Confirmado: Workspace e Automacao estao na lixeira.")

    # 9. Restauracao da Lixeira
    print_step("Testando restauracao da lixeira")
    resp = session.post(f"{BASE_URL}/api/trash/automation/{automation_id}/restore")
    assert resp.status_code == 200, f"Erro ao restaurar item: {resp.text}"
    trash_items = session.get(f"{BASE_URL}/api/trash").json().get("items", [])
    auto_in_trash = any(it["entity_type"] == "automation" and it["id"] == automation_id for it in trash_items)
    assert not auto_in_trash, "Automacao ainda consta na lixeira apos restauracao."
    print("  Confirmado: Automacao restaurada e removida da lixeira.")

    # Soft-deleta novamente para excluir tudo definitivamente
    session.delete(f"{BASE_URL}/api/automations/{automation_id}")

    # 10. Exclusao Definitiva (cascade pelo workspace)
    print_step("Testando exclusao definitiva (cascade)")
    resp = session.delete(f"{BASE_URL}/api/trash/workspace/{workspace_id}")
    assert resp.status_code == 200, f"Erro ao excluir definitivamente o workspace: {resp.text}"
    print("  Workspace excluido definitivamente.")

    trash_items = session.get(f"{BASE_URL}/api/trash").json().get("items", [])
    ws_in_trash = any(it["entity_type"] == "workspace" and it["id"] == workspace_id for it in trash_items)
    auto_in_trash = any(it["entity_type"] == "automation" and it["id"] == automation_id for it in trash_items)
    assert not ws_in_trash, "Workspace ainda consta na lixeira."
    assert not auto_in_trash, "Automacao ainda consta na lixeira (o cascade nao funcionou)."
    print("  Confirmado: Workspace e Automacao sumiram da lixeira.")

    # Limpa a pasta fisica de monitoramento
    shutil.rmtree(MONITOR_FOLDER, ignore_errors=True)
    print("  Pasta de teste limpa.")

    print("\n" + "=" * 60)
    print(" TODOS OS TESTES PASSARAM COM SUCESSO! ")
    print("=" * 60)


if __name__ == "__main__":
    main()
