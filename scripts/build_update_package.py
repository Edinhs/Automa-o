"""
Build an INCREMENTAL UPDATE package (overlay) for the Automation HUB.

Unlike build_release_empty_db.py (a full clean runtime that starts with an empty
DB), this produces a small ZIP meant to be extracted *over an existing install*.
It ships only application code + dist + operational scripts + docs. It NEVER ships
the database, runtime data, virtualenv, browser sessions or the offline Chromium,
so applying it PRESERVES the existing banco de dados and runtime state.

Output: releases/hub_update_COMPLETO_YYYYMMDD_HHMMSS(.zip)

The operational batch scripts -- including stop_all.bat and restart_services.bat --
are part of the overlay so an update install gets them too.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

# Reuse the release guard (forbidden patterns / copy helpers) from the strict builder.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_release_empty_db import (  # noqa: E402
    FORBIDDEN_FILE_NAMES,
    FORBIDDEN_PARTS,
    FORBIDDEN_RELATIVE_PATHS,
    FORBIDDEN_RELATIVE_PREFIXES,
    FORBIDDEN_SUFFIXES,
    copy_dir,
    copy_file,
)

ROOT = Path(__file__).resolve().parents[1]
RELEASES_DIR = ROOT / "releases"

# Operational launchers shipped with every update (stop_all + restart included).
ROOT_FILES = [
    ".env.example",
    "build_release_empty_db.bat",
    "build_update_package.bat",
    "setup_backend.bat",
    "start_agent.bat",
    "start_all.bat",
    "start_all_hidden.vbs",
    "start_backend.bat",
    "start_dashboard.bat",
    "stop_all.bat",
    "restart_services.bat",
]

# Operational / release documentation worth carrying in an update.
DOC_FILES = [
    "CLAUDE.md",
    "BACKEND_START.md",
    "RELEASE_POLICY.md",
    "ESTUDO_MULTIUSUARIO.md",
    "GUIA_POWER_AUTOMATE.md",
    "README.md",
]

# Application overlay. NO backend/data, NO ms-playwright, NO .venv (preserves DB/runtime).
ROOT_DIRS = ["dist", "public", "scripts"]
BACKEND_FILES = ["requirements.txt", ".env.example", "alembic.ini"]
# NAO inclui "scripts": backend/scripts sao testes/dumps de DEV (test_*.py, *_dump.json) que o
# backend nao importa em runtime -- alinhado ao strict builder (build_release_empty_db.py), que
# tambem omite backend/scripts. Incluir vazava testes de dev na instalacao corporativa.
BACKEND_DIRS = ["app", "alembic"]


def is_forbidden(relative: str, name: str, suffix: str, parts: set[str]) -> bool:
    """Mirror the strict-release guard, plus reject hand-edit *.bak* backups."""
    if (
        parts & FORBIDDEN_PARTS
        or name in FORBIDDEN_FILE_NAMES
        or suffix.lower() in FORBIDDEN_SUFFIXES
        or relative in FORBIDDEN_RELATIVE_PATHS
        or any(relative.startswith(prefix) for prefix in FORBIDDEN_RELATIVE_PREFIXES)
    ):
        return True
    # dist/ carries tracked *.bak_* hand-edit backups that must not ship.
    if ".bak" in name:
        return True
    # Testes de dev soltos (test_*.py) nunca vao ao pacote.
    if name.startswith("test_") and name.endswith(".py"):
        return True
    return False


def forbidden_entries(release_dir: Path) -> list[str]:
    entries: list[str] = []
    for path in release_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(release_dir).as_posix()
        if relative in {"LEIA-ME.txt", "UPDATE_VALIDATION.txt"}:
            continue
        parts = set(path.relative_to(release_dir).parts)
        if is_forbidden(relative, path.name, path.suffix, parts):
            entries.append(relative)
    return sorted(entries)


def strip_backups(release_dir: Path) -> int:
    """Remove any *.bak* that slipped through copytree (dist hand-edit backups)."""
    removed = 0
    for path in list(release_dir.rglob("*")):
        if path.is_file() and ".bak" in path.name:
            path.unlink()
            removed += 1
    return removed


LEIA_ME = """\
Automation HUB - Pacote de ATUALIZACAO (overlay)
================================================

O QUE E ESTE PACOTE
-------------------
Atualizacao incremental. Contem SOMENTE as modificacoes da aplicacao
(codigo backend, dist do frontend, scripts .bat e documentacao).

NAO contem e NAO apaga:
  - backend/data/ (banco de dados SQLite, sessoes de navegador, logs, relatorios)
  - .venv, node_modules, backend/ms-playwright (Chromium offline)

Ou seja: aplicar este pacote PRESERVA o seu banco de dados e o estado de runtime.

COMO APLICAR
------------
1. Pare os servicos:        stop_all.bat
2. Extraia este ZIP por cima da pasta da sua instalacao, mantendo a estrutura
   de pastas (sobrescreva os arquivos quando perguntado).
3. Se houver novas migracoes em backend/alembic/versions, rode setup_backend.bat
   (ele aplica "alembic upgrade head" nos dois ambientes, sem apagar dados).
4. Reinicie:                restart_services.bat

OBSERVACOES
-----------
- stop_all.bat encerra apenas os processos deste pacote nas portas 8000/5173.
- Nenhum arquivo *.db, *.sqlite, .env ou .venv esta incluido neste pacote.
"""


def main() -> int:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    package_name = f"hub_update_COMPLETO_{timestamp}"
    package_dir = RELEASES_DIR / package_name
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    for item in ROOT_FILES + DOC_FILES:
        copy_file(ROOT / item, package_dir / item)
    for item in ROOT_DIRS:
        copy_dir(ROOT / item, package_dir / item)

    backend_dst = package_dir / "backend"
    for item in BACKEND_FILES:
        copy_file(ROOT / "backend" / item, backend_dst / item)
    for item in BACKEND_DIRS:
        copy_dir(ROOT / "backend" / item, backend_dst / item)

    removed_backups = strip_backups(package_dir)
    (package_dir / "LEIA-ME.txt").write_text(LEIA_ME, encoding="utf-8")

    forbidden = forbidden_entries(package_dir)

    zip_path = RELEASES_DIR / f"{package_name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    # Entries are written at the archive ROOT (no wrapping folder) so the ZIP can be
    # extracted directly over an existing install, overlaying files in place.
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(package_dir))

    entry_count = sum(1 for path in package_dir.rglob("*") if path.is_file())
    has_db = any(
        path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
        for path in package_dir.rglob("*")
        if path.is_file()
    )
    validation = [
        f"package={package_name}",
        f"created_at={datetime.now().isoformat(timespec='seconds')}",
        f"type=incremental_overlay_update",
        f"preserves_database=True",
        f"has_stop_all={(package_dir / 'stop_all.bat').exists()}",
        f"has_restart_services={(package_dir / 'restart_services.bat').exists()}",
        f"has_dist_index={(package_dir / 'dist' / 'index.html').exists()}",
        f"has_backend_app={(backend_dst / 'app').exists()}",
        f"contains_database_file={has_db}",
        f"removed_bak_backups={removed_backups}",
        f"forbidden_entries={len(forbidden)}",
        f"entry_count={entry_count}",
        f"zip_path={zip_path}",
        f"zip_size_mb={zip_path.stat().st_size / (1024 * 1024):.2f}",
    ]
    if forbidden:
        validation.append("forbidden_list=" + ", ".join(forbidden[:50]))
    (package_dir / "UPDATE_VALIDATION.txt").write_text("\n".join(validation) + "\n", encoding="utf-8")
    print("\n".join(validation))

    # Fail the build if the package is unsafe: forbidden content, a DB leaked in,
    # or the requested stop/restart launchers are missing.
    ok = (
        not forbidden
        and not has_db
        and (package_dir / "stop_all.bat").exists()
        and (package_dir / "restart_services.bat").exists()
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
