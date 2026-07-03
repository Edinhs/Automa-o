import os
import sys
import unittest
import tempfile
import shutil
import zipfile
from pathlib import Path

# Adiciona o diretório atual e a raiz do projeto ao sys.path para garantir imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from custom_automations.ipc_workspace_updater.db_helper import DBHelper
from custom_automations.ipc_workspace_updater.cr_processor import scan_and_apply_crs, parse_cr_code
from custom_automations.ipc_workspace_updater.document_parser import parse_vf_name

class TestIPCWorkspaceUpdater(unittest.TestCase):
    def setUp(self):
        # Cria diretório temporário para testes isolados
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_ipc_history.db")
        self.db = DBHelper(self.db_path)
        
        # Mocks para caminhos de rede e locais
        self.workspace_local_path = os.path.join(self.test_dir, "local_workspace")
        self.cr_repo_path = os.path.join(self.test_dir, "cr_repo")
        self.cr_folder = "J3U - Data Change Request Management"
        
        os.makedirs(self.workspace_local_path, exist_ok=True)
        os.makedirs(os.path.join(self.cr_repo_path, self.cr_folder), exist_ok=True)

    def tearDown(self):
        # Remove diretório temporário e todos os arquivos gerados
        shutil.rmtree(self.test_dir)

    def test_db_helper_workspace_creation(self):
        """Testa se o helper de banco de dados cria e recupera o workspace corretamente."""
        workspace_id = self.db.get_or_create_workspace("J3U", self.workspace_local_path)
        self.assertIsNotNone(workspace_id)
        
        # Recupera novamente e o ID deve ser o mesmo
        workspace_id_2 = self.db.get_or_create_workspace("J3U", self.workspace_local_path)
        self.assertEqual(workspace_id, workspace_id_2)

    def test_db_helper_cr_tracking(self):
        """Testa o controle de aplicação de CRs no banco de dados local."""
        workspace_id = self.db.get_or_create_workspace("J3U", self.workspace_local_path)
        
        cr_code = "CR03748"
        self.assertFalse(self.db.is_cr_applied(workspace_id, cr_code))
        
        # Registra a CR
        cr_id = self.db.register_cr(workspace_id, cr_code, "J3U_DCR_1_7_CR03748_IPC__SoftwareFactory.zip")
        self.assertIsNotNone(cr_id)
        self.assertTrue(self.db.is_cr_applied(workspace_id, cr_code))

    def test_db_helper_vf_upsert(self):
        """Testa a inserção e atualização de VFs com gravação no histórico."""
        workspace_id = self.db.get_or_create_workspace("J3U", self.workspace_local_path)
        
        vf_name = "VF395_V1_R1"
        version, revision = "V1", "R1"
        file_hash = "mock_hash_1"
        file_path = os.path.join(self.workspace_local_path, f"{vf_name}.txt")
        
        # 1. Cria a VF inicial
        vf_id, is_updated = self.db.upsert_vf(
            workspace_id=workspace_id,
            vf_name=vf_name,
            version=version,
            revision=revision,
            file_hash=file_hash,
            file_path=file_path
        )
        self.assertTrue(is_updated)
        self.assertIsNotNone(vf_id)
        
        # Se fizermos upsert com o mesmo hash, não deve marcar como atualizada
        _, is_updated_2 = self.db.upsert_vf(
            workspace_id=workspace_id,
            vf_name=vf_name,
            version=version,
            revision=revision,
            file_hash=file_hash,
            file_path=file_path
        )
        self.assertFalse(is_updated_2)
        
        # 2. Atualiza a VF (muda o hash ou a versão/revisão)
        new_hash = "mock_hash_2"
        new_version = "V2"
        new_revision = "R1"
        _, is_updated_3 = self.db.upsert_vf(
            workspace_id=workspace_id,
            vf_name="VF395_V2_R1", # nova nomenclatura
            version=new_version,
            revision=new_revision,
            file_hash=new_hash,
            file_path=file_path
        )
        self.assertTrue(is_updated_3)

    def test_parse_cr_code_and_vf_name(self):
        """Testa as expressões regulares e utilitários de nome."""
        path_example = "CR03748\\DCR_1\\Packages\\J3U_DCR_1_7_CR03748_IPC__SoftwareFactory.zip"
        cr_code = parse_cr_code(path_example)
        self.assertEqual(cr_code, "CR03748")
        
        version, revision = parse_vf_name("VF395_V2_R1")
        self.assertEqual(version, "V2")
        self.assertEqual(revision, "R1")

    def test_cr_scanning_and_application(self):
        """Testa o fluxo completo de varredura e aplicação de Change Requests com pacotes ZIP mocks."""
        workspace_id = self.db.get_or_create_workspace("J3U", self.workspace_local_path)
        
        # 1. Cria a estrutura mock de CR no repositório simulado
        # CR03748\DCR_1\Packages\J3U_DCR_1_7_CR03748_IPC__SoftwareFactory.zip
        cr_folder_dir = os.path.join(self.cr_repo_path, self.cr_folder, "CR03748", "DCR_1", "Packages")
        os.makedirs(cr_folder_dir, exist_ok=True)
        
        # Cria um arquivo ZIP de teste contendo arquivos de VFs mockados
        zip_file_path = os.path.join(cr_folder_dir, "J3U_DCR_1_7_CR03748_IPC__SoftwareFactory.zip")
        
        # Cria arquivos temporários para compactar
        zip_temp_dir = os.path.join(self.test_dir, "zip_temp")
        os.makedirs(zip_temp_dir, exist_ok=True)
        
        vf_file_1 = os.path.join(zip_temp_dir, "VF395_V2_R1.txt")
        with open(vf_file_1, "w", encoding="utf-8") as f:
            f.write("Conteudo atualizado da VF395 para versao 2.")
            
        vf_file_2 = os.path.join(zip_temp_dir, "VF429_V1_R2.txt")
        with open(vf_file_2, "w", encoding="utf-8") as f:
            f.write("Conteudo da nova VF429.")
            
        with zipfile.ZipFile(zip_file_path, "w") as z:
            z.write(vf_file_1, arcname="VF395_V2_R1.txt")
            z.write(vf_file_2, arcname="VF429_V1_R2.txt")
            
        # 2. Executa a varredura e processamento de CRs
        temp_extract_dir = os.path.join(self.test_dir, "temp_extract")
        applied_crs = scan_and_apply_crs(
            project_name="J3U",
            cr_repo_path=self.cr_repo_path,
            cr_folder=self.cr_folder,
            workspace_local_path=self.workspace_local_path,
            workspace_id=workspace_id,
            db=self.db,
            temp_dir=temp_extract_dir
        )
        
        # 3. Validações
        self.assertEqual(len(applied_crs), 1)
        self.assertEqual(applied_crs[0]["cr_code"], "CR03748")
        self.assertEqual(applied_crs[0]["status"], "applied")
        self.assertIn("VF395_V2_R1", applied_crs[0]["updated_vfs"])
        self.assertIn("VF429_V1_R2", applied_crs[0]["updated_vfs"])
        
        # Verifica se os arquivos foram criados fisicamente no local_workspace
        dest_vf1 = os.path.join(self.workspace_local_path, "VF395_V2_R1.txt")
        dest_vf2 = os.path.join(self.workspace_local_path, "VF429_V1_R2.txt")
        self.assertTrue(os.path.exists(dest_vf1))
        self.assertTrue(os.path.exists(dest_vf2))
        
        with open(dest_vf1, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "Conteudo atualizado da VF395 para versao 2.")
            
        # Verifica se a CR foi marcada como aplicada no banco local
        self.assertTrue(self.db.is_cr_applied(workspace_id, "CR03748"))

    def test_single_baseline_logic_flow(self):
        """Testa se a checagem de baseline ativa no banco funciona para evitar re-processamento."""
        workspace_id = self.db.get_or_create_workspace("J3U", self.workspace_local_path)
        
        # Inicialmente, não há VFs cadastradas
        existing_vfs = self.db.get_workspace_vfs(workspace_id)
        self.assertEqual(len(existing_vfs), 0)
        
        # Adiciona uma VF para simular que a baseline já rodou uma vez
        self.db.upsert_vf(
            workspace_id=workspace_id,
            vf_name="VF395_V1_R1",
            version="V1",
            revision="R1",
            file_hash="hash1",
            file_path="some_path"
        )
        
        # Agora o banco de dados deve indicar que já há VFs no workspace
        existing_vfs_after = self.db.get_workspace_vfs(workspace_id)
        self.assertEqual(len(existing_vfs_after), 1)
        self.assertIn("VF395_V1_R1", existing_vfs_after)

if __name__ == "__main__":
    unittest.main()
