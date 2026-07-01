import os
import re
import zipfile
import shutil
import hashlib
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional
from .db_helper import DBHelper

# Regex para extrair o código da CR (ex: CR03748)
CR_CODE_PATTERN = re.compile(r"CR\d+")
# Regex para identificar nomes de VFs nos arquivos (ex: VF395_V1_R1 ou VF395_V1)
VF_NAME_PATTERN = re.compile(r"VF\d+_V\d+_R\d+")
VF_SIMPLE_PATTERN = re.compile(r"VF\d+")

def calculate_sha256(file_path: str) -> str:
    """Calcula o hash SHA256 de um arquivo."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def extract_zip(zip_path: str, extract_to: str) -> List[str]:
    """Extrai um arquivo ZIP para um diretório e retorna a lista de caminhos de arquivos extraídos."""
    extracted_files = []
    if not os.path.exists(extract_to):
        os.makedirs(extract_to, exist_ok=True)
        
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
        for root, _, files in os.walk(extract_to):
            for file in files:
                extracted_files.append(os.path.join(root, file))
    return extracted_files

def parse_cr_code(path_str: str) -> Optional[str]:
    """Tenta identificar o código da CR (ex: CR03748) a partir do caminho ou nome do arquivo."""
    match = CR_CODE_PATTERN.search(path_str)
    return match.group(0) if match else None

def scan_and_apply_crs(
    project_name: str,
    cr_repo_path: str,
    cr_folder: str,
    workspace_local_path: str,
    workspace_id: int,
    db: DBHelper,
    temp_dir: str = "./data/temp/ipc_updater"
) -> List[Dict[str, Any]]:
    """
    Varre o diretório de CRs do projeto, identifica pacotes ZIP de impacto
    no IPC SoftwareFactory, processa as VFs modificadas e atualiza o workspace.
    """
    applied_crs_summary = []
    
    # Caminho completo do diretório de CRs do projeto
    project_cr_dir = Path(cr_repo_path) / cr_folder
    if not project_cr_dir.exists():
        print(f"[WARNING] Diretorio de CRs do projeto nao encontrado: {project_cr_dir}")
        return applied_crs_summary

    print(f"[INFO] Buscando CRs em: {project_cr_dir}")
    
    # Busca recursiva por pacotes ZIP de IPC SoftwareFactory
    # Seguindo a estrutura: CRxxxxx\DCR_x\Packages\*.zip
    # Para ser flexível, buscamos arquivos *.zip de forma recursiva
    zip_files = list(project_cr_dir.glob("**/Packages/*.zip"))
    if not zip_files:
        # Fallback de busca recursiva geral se a estrutura 'Packages' não for exata
        zip_files = list(project_cr_dir.glob("**/*.zip"))

    # Filtra por pacotes destinados ao IPC SoftwareFactory (ex: *IPC__SoftwareFactory.zip)
    ipc_zip_files = [z for z in zip_files if "IPC__SoftwareFactory" in z.name]
    
    # Ordena os pacotes pelo código da CR (se puder extrair) ou pela data de modificação
    def get_sort_key(p: Path):
        cr_code = parse_cr_code(p.name) or parse_cr_code(str(p))
        if cr_code:
            try:
                return (1, int(cr_code[2:])) # Ordena numericamente pelo número da CR
            except ValueError:
                return (2, cr_code)
        return (3, p.stat().st_mtime)

    ipc_zip_files.sort(key=get_sort_key)

    for zip_path in ipc_zip_files:
        cr_code = parse_cr_code(zip_path.name) or parse_cr_code(str(zip_path))
        if not cr_code:
            # Fallback: se não tiver código CRxxxxx, usa o nome do arquivo ZIP sem extensão
            cr_code = zip_path.stem

        # RNF-01 / RF-12: Verifica se a CR já foi aplicada
        if db.is_cr_applied(workspace_id, cr_code):
            print(f"[INFO] CR {cr_code} ja foi aplicada anteriormente. Pulando.")
            continue

        print(f"[INFO] Processando nova CR encontrada: {cr_code} (Arquivo: {zip_path.name})")
        
        # Cria diretório temporário para extração
        cr_temp_extract = os.path.join(temp_dir, cr_code)
        if os.path.exists(cr_temp_extract):
            shutil.rmtree(cr_temp_extract)
            
        try:
            # Extrai o ZIP
            extracted_files = extract_zip(str(zip_path), cr_temp_extract)
            
            # Registra a CR no banco SQLite local antes de processar as VFs
            cr_db_id = db.register_cr(workspace_id, cr_code, zip_path.name)
            
            updated_vfs_count = 0
            vfs_applied = []
            
            # Analisa as VFs modificadas no pacote
            for file_path in extracted_files:
                file_name = os.path.basename(file_path)
                
                # Identifica se o nome do arquivo se refere a uma VF (ex: VF395_V2_R1.txt ou VF395_V2.md)
                vf_match = VF_NAME_PATTERN.search(file_name)
                if not vf_match:
                    # Tenta encontrar apenas VFxxx
                    vf_simple_match = VF_SIMPLE_PATTERN.search(file_name)
                    if vf_simple_match:
                        # Se achou apenas VFxxx, tentamos construir um nome
                        vf_name = vf_simple_match.group(0)
                    else:
                        # Não parece ser um arquivo de VF
                        continue
                else:
                    vf_name = vf_match.group(0)

                # Determina versão e revisão do arquivo ou assume padrão
                version_match = re.search(r"_V(\d+)", file_name)
                revision_match = re.search(r"_R(\d+)", file_name)
                
                version = f"V{version_match.group(1)}" if version_match else "V1"
                revision = f"R{revision_match.group(1)}" if revision_match else "R1"
                
                # Calcula o hash do arquivo extraído
                file_hash = calculate_sha256(file_path)
                
                # Pasta de destino no workspace local
                dest_workspace_dir = Path(workspace_local_path)
                dest_workspace_dir.mkdir(parents=True, exist_ok=True)
                dest_file_path = dest_workspace_dir / file_name
                
                # RF-10 / RF-11: Compara com a VF ativa e atualiza
                # Faz o upsert no banco local
                vf_id, is_updated = db.upsert_vf(
                    workspace_id=workspace_id,
                    vf_name=vf_name,
                    version=version,
                    revision=revision,
                    file_hash=file_hash,
                    file_path=str(dest_file_path.absolute()),
                    cr_id=cr_db_id
                )
                
                if is_updated:
                    # Copia o arquivo atualizado fisicamente para o workspace
                    shutil.copy2(file_path, dest_file_path)
                    updated_vfs_count += 1
                    vfs_applied.append(vf_name)
                    print(f"  [VF ATUALIZADA] {vf_name} ({version}_{revision}) gravada em {file_name}")

            applied_crs_summary.append({
                "cr_code": cr_code,
                "zip_file": zip_path.name,
                "updated_vfs": vfs_applied,
                "status": "applied"
            })
            
        except Exception as e:
            # RNF-01: Robustez e tratamento de erros
            print(f"[ERROR] Falha ao processar pacote da CR {cr_code}: {e}")
            # Registra no resumo para logs
            applied_crs_summary.append({
                "cr_code": cr_code,
                "zip_file": zip_path.name,
                "error": str(e),
                "status": "failed"
            })
        finally:
            # Limpa pasta temporária
            if os.path.exists(cr_temp_extract):
                shutil.rmtree(cr_temp_extract)

    return applied_crs_summary
