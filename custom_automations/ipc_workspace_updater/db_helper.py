import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any

class DBHelper:
    def __init__(self, db_path: str = "ipc_workspace_history.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Inicializa as tabelas do banco de dados SQLite local se não existirem."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Tabela de workspaces locais (projetos)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS projects_workspace (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_name TEXT NOT NULL UNIQUE,
                    base_path TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Tabela de VFs ativas no workspace
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS project_vfs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id INTEGER NOT NULL,
                    vf_name TEXT NOT NULL,
                    current_version TEXT NOT NULL,
                    current_revision TEXT NOT NULL,
                    current_hash TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (workspace_id) REFERENCES projects_workspace (id),
                    UNIQUE(workspace_id, vf_name)
                )
            """)

            # Tabela de Change Requests (CRs) aplicadas ao workspace
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS change_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id INTEGER NOT NULL,
                    cr_code TEXT NOT NULL,
                    package_zip_name TEXT NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'applied',
                    FOREIGN KEY (workspace_id) REFERENCES projects_workspace (id),
                    UNIQUE(workspace_id, cr_code)
                )
            """)

            # Tabela de histórico de revisões de cada VF
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vf_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vf_id INTEGER NOT NULL,
                    cr_id INTEGER, -- NULL indica a baseline (CREATE)
                    version TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (vf_id) REFERENCES project_vfs (id),
                    FOREIGN KEY (cr_id) REFERENCES change_requests (id)
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def get_or_create_workspace(self, project_name: str, base_path: str) -> int:
        """Obtém ou cria o workspace para um projeto específico."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM projects_workspace WHERE project_name = ?", (project_name,))
            row = cursor.fetchone()
            if row:
                return row["id"]
            
            cursor.execute(
                "INSERT INTO projects_workspace (project_name, base_path) VALUES (?, ?)",
                (project_name, base_path)
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def is_cr_applied(self, workspace_id: int, cr_code: str) -> bool:
        """Verifica se uma Change Request (CR) já foi aplicada ao workspace."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM change_requests WHERE workspace_id = ? AND cr_code = ?",
                (workspace_id, cr_code)
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def register_cr(self, workspace_id: int, cr_code: str, package_zip_name: str) -> int:
        """Registra a aplicação de uma Change Request no banco local."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO change_requests (workspace_id, cr_code, package_zip_name) VALUES (?, ?, ?)",
                (workspace_id, cr_code, package_zip_name)
            )
            conn.commit()
            cursor.execute(
                "SELECT id FROM change_requests WHERE workspace_id = ? AND cr_code = ?",
                (workspace_id, cr_code)
            )
            return cursor.fetchone()["id"]
        finally:
            conn.close()

    def upsert_vf(self, workspace_id: int, vf_name: str, version: str, revision: str, file_hash: str, file_path: str, cr_id: Optional[int] = None) -> Tuple[int, bool]:
        """
        Insere ou atualiza uma VF e grava no histórico.
        Retorna uma tupla (vf_id, is_updated).
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Tenta obter a VF existente
            cursor.execute(
                "SELECT id, current_hash, current_version, current_revision FROM project_vfs WHERE workspace_id = ? AND vf_name = ?",
                (workspace_id, vf_name)
            )
            existing_vf = cursor.fetchone()
            
            is_updated = False
            
            if existing_vf:
                vf_id = existing_vf["id"]
                # Se mudou o hash de conteúdo ou a versão/revisão, atualiza a VF
                if (existing_vf["current_hash"] != file_hash or 
                    existing_vf["current_version"] != version or 
                    existing_vf["current_revision"] != revision):
                    
                    cursor.execute(
                        """
                        UPDATE project_vfs 
                        SET current_version = ?, current_revision = ?, current_hash = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (version, revision, file_hash, vf_id)
                    )
                    is_updated = True
            else:
                cursor.execute(
                    """
                    INSERT INTO project_vfs (workspace_id, vf_name, current_version, current_revision, current_hash)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (workspace_id, vf_name, version, revision, file_hash)
                )
                vf_id = cursor.lastrowid
                is_updated = True

            if is_updated or not existing_vf:
                # Grava no histórico de revisões
                cursor.execute(
                    """
                    INSERT INTO vf_history (vf_id, cr_id, version, revision, file_hash, file_path)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (vf_id, cr_id, version, revision, file_hash, file_path)
                )
                
            conn.commit()
            return vf_id, is_updated
        finally:
            conn.close()

    def get_workspace_vfs(self, workspace_id: int) -> Dict[str, Dict[str, Any]]:
        """Retorna todas as VFs atualmente ativas do workspace mapeadas pelo nome."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT vf_name, current_version, current_revision, current_hash, updated_at FROM project_vfs WHERE workspace_id = ?",
                (workspace_id,)
            )
            rows = cursor.fetchall()
            return {
                row["vf_name"]: {
                    "version": row["current_version"],
                    "revision": row["current_revision"],
                    "hash": row["current_hash"],
                    "updated_at": row["updated_at"]
                } for row in rows
            }
        finally:
            conn.close()
