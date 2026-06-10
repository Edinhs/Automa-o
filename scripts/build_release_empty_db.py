from __future__ import annotations

import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASES_DIR = ROOT / "releases"
PLAYWRIGHT_CACHE = Path.home() / "AppData" / "Local" / "ms-playwright"
PLAYWRIGHT_RUNTIME_DIR = "ms-playwright"
PLAYWRIGHT_RUNTIME_ITEMS = [
    "chromium-1217",
    "chromium_headless_shell-1217",
    "ffmpeg-1011",
]

ROOT_FILES = [
    ".env.example",
    "BACKEND_START.md",
    "RELEASE_POLICY.md",
    "build_release_empty_db.bat",
    "setup_backend.bat",
    "start_agent.bat",
    "start_all.bat",
    "restart_services.bat",
    "stop_all.bat",
    "stop_automation.bat",
    "start_all_hidden.vbs",
    "start_backend.bat",
    "start_dashboard.bat",
]

# Arquivos que a release NUNCA pode sair sem eles. copy_file ignora ausentes em
# silencio e os flags has_* do RELEASE_VALIDATION.txt sao so informativos; esta
# lista e checada contra o pacote final e FALHA o build (exit != 0) se faltar qualquer
# um. stop_automation.bat e a bat que finaliza TUDO (navegadores da automacao + agente
# + backend + dashboard); stop_all.bat para os servicos do pacote. Caminhos relativos a
# raiz da release (mesma chave usada em ROOT_FILES).
REQUIRED_RELEASE_FILES = [
    "stop_automation.bat",
    "stop_all.bat",
]

ROOT_DIRS = ["dist", "public", "scripts"]
BACKEND_FILES = ["requirements.txt", ".env.example", "alembic.ini"]
BACKEND_DIRS = ["app", "alembic", "wheels"]

FORBIDDEN_PARTS = {
    ".env",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".idea",
    "data",
    "tests",
}
FORBIDDEN_FILE_NAMES = {
    "requirements-dev.txt",
    "seed_dev_data.py",
    "smoke_schedule_runner.py",
    "mockData.js",
}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pyc", ".zip", ".rar", ".7z"}
# Sufixos compostos (nao capturados por Path.suffix): artefatos de debug/format do frontend.
FORBIDDEN_NAME_SUFFIXES = (".formatted.js",)
FORBIDDEN_RELATIVE_PREFIXES = {
    "src/",
    "backend/tests/",
}
FORBIDDEN_RELATIVE_PATHS = {
    "backend/requirements-dev.txt",
    "backend/app/cli/seed_dev_data.py",
    "backend/app/cli/smoke_schedule_runner.py",
    "src/constants/mockData.js",
}


def ignore_runtime(dir_path: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        path = Path(dir_path) / name
        if (
            name in FORBIDDEN_PARTS
            or name in FORBIDDEN_FILE_NAMES
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
            or name.lower().endswith(FORBIDDEN_NAME_SUFFIXES)
        ):
            ignored.add(name)
    return ignored


def copy_file(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_dir(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    shutil.copytree(src, dst, ignore=ignore_runtime)


def copy_playwright_runtime(dst: Path) -> list[str]:
    copied: list[str] = []
    runtime_dst = dst / PLAYWRIGHT_RUNTIME_DIR
    runtime_dst.mkdir(parents=True, exist_ok=True)
    for item in PLAYWRIGHT_RUNTIME_ITEMS:
        src = PLAYWRIGHT_CACHE / item
        if src.exists():
            copy_dir(src, runtime_dst / item)
            copied.append(item)
    return copied


def forbidden_entries(release_dir: Path) -> list[str]:
    entries: list[str] = []
    for path in release_dir.rglob("*"):
        relative = path.relative_to(release_dir).as_posix()
        parts = set(path.relative_to(release_dir).parts)
        if (
            parts & FORBIDDEN_PARTS
            or path.name in FORBIDDEN_FILE_NAMES
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
            or path.name.lower().endswith(FORBIDDEN_NAME_SUFFIXES)
            or relative in FORBIDDEN_RELATIVE_PATHS
            or any(relative.startswith(prefix) for prefix in FORBIDDEN_RELATIVE_PREFIXES)
        ):
            if relative != "RELEASE_VALIDATION.txt":
                entries.append(relative)
    return sorted(entries)


def create_zip(release_dir: Path) -> Path:
    zip_path = RELEASES_DIR / f"{release_dir.name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(release_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(release_dir.parent))
    return zip_path


def main() -> int:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    release_name = f"Automation_HUB_company_notebook_chromium_no_login_empty_db_{timestamp}"
    release_dir = RELEASES_DIR / release_name
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True, exist_ok=True)

    for item in ROOT_FILES:
        copy_file(ROOT / item, release_dir / item)
    for item in ROOT_DIRS:
        copy_dir(ROOT / item, release_dir / item)

    backend_dst = release_dir / "backend"
    for item in BACKEND_FILES:
        copy_file(ROOT / "backend" / item, backend_dst / item)
    for item in BACKEND_DIRS:
        copy_dir(ROOT / "backend" / item, backend_dst / item)
    copied_playwright = copy_playwright_runtime(backend_dst)

    forbidden = forbidden_entries(release_dir)
    missing_required = [item for item in REQUIRED_RELEASE_FILES if not (release_dir / item).is_file()]
    validation_path = release_dir / "RELEASE_VALIDATION.txt"
    validation_path.write_text("validation=pending\n", encoding="utf-8")
    zip_path = create_zip(release_dir)
    for _ in range(2):
        entry_count = sum(1 for path in release_dir.rglob("*") if path.is_file())
        validation = [
            f"release={release_name}",
            f"created_at={datetime.now().isoformat(timespec='seconds')}",
            f"has_dist={(release_dir / 'dist' / 'index.html').exists()}",
            f"has_src={(release_dir / 'src').exists()}",
            f"has_backend_app={(backend_dst / 'app').exists()}",
            f"has_backend_tests={(backend_dst / 'tests').exists()}",
            f"has_requirements_dev={(backend_dst / 'requirements-dev.txt').exists()}",
            f"has_seed_dev={(backend_dst / 'app' / 'cli' / 'seed_dev_data.py').exists()}",
            f"has_backend_env_example={(backend_dst / '.env.example').exists()}",
            f"has_start_all_hidden={(release_dir / 'start_all_hidden.vbs').exists()}",
            f"has_restart_services={(release_dir / 'restart_services.bat').exists()}",
            f"has_stop_all={(release_dir / 'stop_all.bat').exists()}",
            f"has_stop_automation={(release_dir / 'stop_automation.bat').exists()}",
            f"has_purge_legacy_reports_cli={(backend_dst / 'app' / 'cli' / 'purge_legacy_reports.py').exists()}",
            f"has_folder_monitoring_report_migration={(backend_dst / 'alembic' / 'versions' / 'b8e5f7a9c013_0008_folder_monitoring_report_scope.py').exists()}",
            f"has_offline_chromium={(backend_dst / PLAYWRIGHT_RUNTIME_DIR / 'chromium-1217').exists()}",
            f"has_offline_headless_shell={(backend_dst / PLAYWRIGHT_RUNTIME_DIR / 'chromium_headless_shell-1217').exists()}",
            f"has_offline_ffmpeg={(backend_dst / PLAYWRIGHT_RUNTIME_DIR / 'ffmpeg-1011').exists()}",
            f"playwright_runtime_items={','.join(copied_playwright)}",
            f"forbidden_entries={len(forbidden)}",
            f"missing_required={len(missing_required)}",
            f"entry_count={entry_count}",
            f"zip_path={zip_path}",
            f"zip_size_mb={zip_path.stat().st_size / (1024 * 1024):.2f}",
        ]
        if forbidden:
            validation.append("forbidden_list=" + ", ".join(forbidden[:50]))
        if missing_required:
            validation.append("missing_required_list=" + ", ".join(missing_required))
        validation_path.write_text("\n".join(validation) + "\n", encoding="utf-8")
        zip_path.unlink()
        zip_path = create_zip(release_dir)
    print("\n".join(validation))
    if missing_required:
        print(
            "ERRO: release sem arquivo(s) obrigatorio(s): "
            + ", ".join(missing_required)
            + ". Restaure-o(s) na raiz do repo e refaca o build."
        )
    return 1 if (forbidden or missing_required) else 0


if __name__ == "__main__":
    sys.exit(main())
