import os
import sys
import argparse
import yaml
import logging
import hashlib
from datetime import datetime
from pathlib import Path

# Adiciona o diretório atual ao sys.path para garantir que imports relativos funcionem
sys.path.append(str(Path(__file__).parent.parent))

from ipc_workspace_updater.db_helper import DBHelper
from ipc_workspace_updater.document_parser import extract_vfs_from_word
from ipc_workspace_updater.cr_processor import scan_and_apply_crs

def setup_logger(log_dir: str) -> logging.Logger:
    """Configura o sistema de logs para o console e arquivo local."""
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "ipc_updater.log")
    
    logger = logging.getLogger("ipc_updater")
    logger.setLevel(logging.INFO)
    
    # Evita duplicar handlers se o logger já foi configurado
    if not logger.handlers:
        formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
        
        # Handler para arquivo
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # Handler para console
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
    return logger

def main():
    parser = argparse.ArgumentParser(description="Script de Atualização Automática de Workspace - IPC")
    parser.add_argument("--project", required=True, help="Nome do projeto (ex: J3U)")
    parser.add_argument("--mode", required=True, choices=["CREATE", "UPDATE"], help="Modo de execução: CREATE (novo workspace) ou UPDATE (workspace existente)")
    parser.add_argument("--workspace-id", type=int, help="Identificador do workspace (obrigatório no modo UPDATE)")
    parser.add_argument("--config", default=None, help="Caminho do arquivo config.yaml")
    parser.add_argument("--db", default="ipc_workspace_history.db", help="Caminho do banco SQLite local de histórico")
    
    args = parser.parse_args()
    
    # 1. Carrega e valida configurações
    script_dir = Path(__file__).parent
    config_path = args.config or os.path.join(script_dir, "config.yaml")
    if not os.path.exists(config_path):
        print(f"[ERROR] Arquivo de configuracao nao encontrado em {config_path}. Abortando.")
        sys.exit(1)
        
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    project = args.project
    if project not in config.get("projects", {}):
        print(f"[ERROR] Projeto '{project}' nao configurado no config.yaml. Abortando.")
        sys.exit(1)
        
    proj_config = config["projects"][project]
    net_config = config.get("network_paths", {})
    
    # Inicializa caminhos
    workspace_local_path = proj_config.get("workspace_local_path", f"./data/workspaces/{project}")
    os.makedirs(workspace_local_path, exist_ok=True)
    
    # Inicializa Logger
    logger = setup_logger(workspace_local_path)
    logger.info(f"Iniciando execucao do script - Projeto: {project} | Modo: {args.mode}")
    
    # Inicializa Banco de Dados Local
    db = DBHelper(args.db)
    
    # Execução baseada no Modo
    if args.mode == "CREATE":
        logger.info("Executando no modo CREATE - Criando workspace inicial a partir do Word")
        
        # 1. Localização do diretório e documento de requisitos
        spec_repo = net_config.get("spec_repository", "")
        spec_folder = proj_config.get("spec_folder", "")
        req_subpath = proj_config.get("requirements_subpath", "")
        word_pattern = proj_config.get("word_file_pattern", "*.docx")
        
        spec_full_path = Path(spec_repo) / spec_folder / req_subpath
        if not spec_full_path.exists():
            logger.error(f"Diretorio de requisitos do projeto nao encontrado no SPEC: {spec_full_path}")
            sys.exit(1)
            
        logger.info(f"Diretorio de requisitos localizado: {spec_full_path}")
        
        # Busca o arquivo Word no diretório
        word_files = list(spec_full_path.glob(word_pattern))
        if not word_files:
            logger.error(f"Documento Word de VFs ({word_pattern}) nao encontrado em: {spec_full_path}")
            sys.exit(1)
            
        word_file_path = word_files[0]
        logger.info(f"Documento Word localizado: {word_file_path.name}")
        
        # 2. Obtém ou Cria o Workspace no banco local
        workspace_id = db.get_or_create_workspace(project, workspace_local_path)
        logger.info(f"Workspace local inicializado - ID: {workspace_id} | Pasta: {workspace_local_path}")
        
        # Requisito: O arquivo contendo a lista de VFs (VFList) deve ser separado apenas na primeira vez
        existing_vfs = db.get_workspace_vfs(workspace_id)
        if existing_vfs:
            logger.info("O arquivo contendo a lista de VFs (VFList) ja foi separado na primeira execucao (baseline ativa). Ignorando processamento de Word.")
            print(f"WORKSPACE_ID={workspace_id}")
            return
            
        # 3. Leitura e Extração das VFs do Word
        try:
            logger.info("Extraindo VFs do arquivo Word...")
            vfs = extract_vfs_from_word(str(word_file_path))
            
            if not vfs:
                logger.warning("Nenhuma VF identificada no documento Word.")
            
            # Grava as VFs na pasta local do workspace e registra no banco local (baseline)
            created_count = 0
            for vf_name, vf_data in vfs.items():
                version = vf_data["version"]
                revision = vf_data["revision"]
                content = vf_data["content"]
                
                # Salva como arquivo de texto individual no workspace local
                vf_filename = f"{vf_name}.txt"
                vf_file_path = Path(workspace_local_path) / vf_filename
                
                with open(vf_file_path, "w", encoding="utf-8") as vf_f:
                    vf_f.write(content)
                    
                # Calcula o hash do arquivo gerado
                file_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
                
                # Faz o upsert no banco local
                db.upsert_vf(
                    workspace_id=workspace_id,
                    vf_name=vf_name,
                    version=version,
                    revision=revision,
                    file_hash=file_hash,
                    file_path=str(vf_file_path.absolute()),
                    cr_id=None # None indica baseline (CREATE)
                )
                created_count += 1
                logger.info(f"VF Registrada (Baseline): {vf_name} ({version}_{revision}) -> {vf_filename}")
                
            logger.info(f"Modo CREATE finalizado com sucesso. Total de VFs extraidas: {created_count}")
            print(f"WORKSPACE_ID={workspace_id}") # Retorna o ID no stdout para scripts integradores
            
        except Exception as e:
            logger.exception(f"Falha durante a criacao do workspace: {e}")
            sys.exit(1)
            
    elif args.mode == "UPDATE":
        logger.info("Executando no modo UPDATE - Buscando e aplicando Change Requests (CRs)")
        
        # Validações do modo UPDATE
        if args.workspace_id is None:
            logger.error("Parametro --workspace-id e obrigatorio no modo UPDATE. Abortando.")
            sys.exit(1)
            
        workspace_id = args.workspace_id
        
        # Verifica se o workspace correspondente existe no banco local
        # (Opcional, mas garante consistência)
        # 1. Configurações de rede
        cr_repo = net_config.get("cr_repository", "")
        cr_folder = proj_config.get("cr_folder", "")
        
        try:
            logger.info(f"Varrendo Change Requests para o workspace {workspace_id}...")
            applied_crs = scan_and_apply_crs(
                project_name=project,
                cr_repo_path=cr_repo,
                cr_folder=cr_folder,
                workspace_local_path=workspace_local_path,
                workspace_id=workspace_id,
                db=db,
                temp_dir="./data/temp/ipc_updater"
            )
            
            applied_count = sum(1 for cr in applied_crs if cr.get("status") == "applied")
            failed_count = sum(1 for cr in applied_crs if cr.get("status") == "failed")
            
            logger.info(f"Modo UPDATE finalizado. CRs aplicadas com sucesso: {applied_count} | Falhas: {failed_count}")
            
            for cr in applied_crs:
                if cr.get("status") == "applied":
                    logger.info(f"  CR {cr['cr_code']} aplicada: {len(cr['updated_vfs'])} VFs modificadas {cr['updated_vfs']}")
                elif cr.get("status") == "failed":
                    logger.error(f"  CR {cr['cr_code']} falhou ao aplicar: {cr.get('error')}")
                    
        except Exception as e:
            logger.exception(f"Falha durante a atualizacao do workspace: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
