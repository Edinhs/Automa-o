import os
import re
import sys
import subprocess
import logging
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

# Allowlist do identificador de projeto: 'project' compoe caminhos de arquivo (get_workspace_dir) e
# vira argumento de subprocess (run_ipc_updater.bat). Restringir a [A-Za-z0-9_-] impede path
# traversal (ex.: '..\\..\\algo') e valores inesperados no argv.
_PROJECT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_project(project: str) -> str:
    project = (project or "").strip()
    if not _PROJECT_RE.fullmatch(project):
        raise HTTPException(
            status_code=400,
            detail="Parametro 'project' invalido: use apenas letras, numeros, '_' ou '-' (1-64 caracteres).",
        )
    return project

# Permite importar db_helper a partir da pasta raiz
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from custom_automations.ipc_workspace_updater.db_helper import DBHelper

# Configuração de Logs
logger = logging.getLogger("custom_automations_router")

router = APIRouter()

# Dicionário global em memória para rastrear processos ativos
# project_name -> { "subprocess": Popen, "started_at": str, "mode": str }
ACTIVE_RUNS: Dict[str, Dict[str, Any]] = {}

class RunRequest(BaseModel):
    project: str = "J3U"

def get_db_path() -> str:
    """Retorna o caminho absoluto do banco SQLite local de histórico."""
    # O banco fica na raiz do projeto
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    return os.path.join(base_dir, "ipc_workspace_history.db")

def get_workspace_dir(project: str) -> str:
    """Retorna o caminho absoluto do workspace do projeto."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    return os.path.join(base_dir, "data", "workspaces", project)

@router.post("/ipc/run")
async def run_ipc_automation(req: RunRequest):
    project = _validate_project(req.project)

    # 1. Verifica se já está rodando
    if project in ACTIVE_RUNS:
        proc = ACTIVE_RUNS[project]["subprocess"]
        if proc.poll() is None:
            return {
                "status": "running",
                "message": f"A automacao para o projeto {project} ja esta sendo executada.",
                "started_at": ACTIVE_RUNS[project]["started_at"],
                "mode": ACTIVE_RUNS[project]["mode"]
            }
        else:
            # Limpa se o processo já terminou
            del ACTIVE_RUNS[project]

    db_path = get_db_path()
    workspace_path = get_workspace_dir(project)
    
    # 2. Conecta ao banco local e decide o modo (CREATE se não há VFs, UPDATE se já há)
    db = DBHelper(db_path)
    workspace_id = db.get_or_create_workspace(project, workspace_path)
    vfs = db.get_workspace_vfs(workspace_id)
    
    mode = "UPDATE" if vfs else "CREATE"
    
    # 3. Dispara o script em segundo plano
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    bat_path = os.path.join(base_dir, "run_ipc_updater.bat")
    
    if not os.path.exists(bat_path):
        raise HTTPException(status_code=500, detail="Script run_ipc_updater.bat nao encontrado na raiz do projeto.")
        
    import datetime
    started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Executa o .bat de forma assíncrona
    try:
        # Prepara argumentos do batch
        cmd = [bat_path, project, mode]
        if mode == "UPDATE":
            cmd.append(str(workspace_id))
            
        logger.info(f"Disparando automacao IPC em segundo plano: {' '.join(cmd)}")
        # Executa em segundo plano sem travar a thread principal
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=base_dir,
            text=True
        )
        
        ACTIVE_RUNS[project] = {
            "subprocess": proc,
            "started_at": started_at,
            "mode": mode
        }
        
        return {
            "status": "started",
            "message": f"Automação IPC iniciada em segundo plano no modo {mode}.",
            "started_at": started_at,
            "mode": mode,
            "workspace_id": workspace_id
        }
    except Exception as e:
        logger.error(f"Erro ao disparar automacao IPC: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao disparar a automacao: {str(e)}")

@router.get("/ipc/status")
async def get_ipc_status(project: str = "J3U"):
    project = _validate_project(project)
    if project in ACTIVE_RUNS:
        proc = ACTIVE_RUNS[project]["subprocess"]
        poll = proc.poll()
        if poll is None:
            return {
                "is_running": True,
                "mode": ACTIVE_RUNS[project]["mode"],
                "started_at": ACTIVE_RUNS[project]["started_at"]
            }
        else:
            # Terminou
            del ACTIVE_RUNS[project]
            
    return {
        "is_running": False,
        "mode": None,
        "started_at": None
    }

@router.get("/ipc/history")
async def get_ipc_history(project: str = "J3U"):
    project = _validate_project(project)
    db_path = get_db_path()
    db = DBHelper(db_path)
    
    workspace_path = get_workspace_dir(project)
    workspace_id = db.get_or_create_workspace(project, workspace_path)
    
    # Recupera VFs e CRs do banco local
    vfs = db.get_workspace_vfs(workspace_id)
    
    # Vamos consultar o histórico de CRs aplicadas de forma crua
    crs = []
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT cr_code, package_zip_name, applied_at, status FROM change_requests WHERE workspace_id = ? ORDER BY applied_at DESC",
            (workspace_id,)
        )
        for row in cursor.fetchall():
            crs.append({
                "cr_code": row["cr_code"],
                "package_zip_name": row["package_zip_name"],
                "applied_at": row["applied_at"],
                "status": row["status"]
            })
    finally:
        conn.close()
        
    return {
        "workspace_id": workspace_id,
        "vfs": vfs,
        "change_requests": crs
    }

@router.get("/ipc/logs")
async def get_ipc_logs(project: str = "J3U", lines_count: int = 100):
    project = _validate_project(project)
    workspace_path = get_workspace_dir(project)
    log_file = os.path.join(workspace_path, "ipc_updater.log")
    
    if not os.path.exists(log_file):
        return {
            "logs": f"Nenhum arquivo de log encontrado em {log_file}.\nExecute a automacao pela primeira vez."
        }
        
    try:
        # Lê as últimas N linhas
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            last_lines = lines[-lines_count:]
            return {
                "logs": "".join(last_lines)
            }
    except Exception as e:
        return {
            "logs": f"Erro ao ler arquivo de log: {str(e)}"
        }
