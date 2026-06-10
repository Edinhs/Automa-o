from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.core.config import resolve_backend_path, runtime_path

DEFAULT_UPLOAD_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".pdf", ".txt", ".csv"}
MAX_IGNORED_FILE_LOGS = 50
MAX_MATCHED_FILE_LOGS = 200
MAX_COPIED_FILE_LOGS = 200

# Prefixos de arquivos temporarios/bloqueio que NUNCA sao documentos reais, mas que carregam uma
# extensao valida (.doc/.docx/.xlsx...) e por isso passavam pelo filtro de extensao: arquivos
# "owner" do MS Office (~$nome.docx, 162 bytes, criados enquanto o documento esta aberto) e locks
# do LibreOffice (.~lock.nome#). Ingeri-los gera Error no Playground e o arquivo some entre ciclos
# (o Office apaga o ~$ ao fechar). Sao filtrados na origem (scan) para nunca entrarem no upload.
TEMP_LOCK_PREFIXES = ("~$", ".~lock.")


def is_temp_or_lock_file(name: str) -> bool:
    """True para owner files do Office (~$...) e locks do LibreOffice (.~lock....)."""
    lowered = (name or "").lower()
    return any(lowered.startswith(prefix) for prefix in TEMP_LOCK_PREFIXES)


def normalize_folder_path(value: str | None) -> str | None:
    if value is None:
        return None
    path = str(value).strip().strip('"').strip("'")
    if not path:
        return None
    path = os.path.expandvars(os.path.expanduser(path))
    if os.name == "nt":
        if path.startswith("//") and not path.startswith("///"):
            path = "\\\\" + path[2:].replace("/", "\\")
        elif path.startswith("\\\\"):
            path = "\\\\" + path[2:].replace("/", "\\")
    return path


def folder_path_diagnostics(value: str | None) -> dict:
    normalized = normalize_folder_path(value)
    text = normalized or ""
    is_unc = text.startswith("\\\\")
    is_windows_drive = len(text) >= 2 and text[1] == ":" and text[0].isalpha()
    return {
        "original_path": value,
        "normalized_path": normalized,
        "is_unc": is_unc,
        "is_mapped_drive": bool(is_windows_drive and not is_unc),
        "drive": text[:2] if is_windows_drive else None,
    }


def enabled_extensions_from_config(config: dict | None) -> set[str]:
    config = config or {}
    enabled = {
        item.get("extension", "").lower()
        for item in config.get("file_types", [])
        if isinstance(item, dict) and item.get("enabled", True)
    }
    enabled.update(str(item).lower() for item in config.get("enabled_extensions", []) if item)
    return {item if item.startswith(".") else f".{item}" for item in enabled if item} or set(DEFAULT_UPLOAD_EXTENSIONS)


def log_event(log: Callable | None, level: str, message: str, **kwargs) -> None:
    if log:
        log(level, message, **kwargs)


def scan_monitored_folder(
    folder: Path,
    enabled_exts: set[str],
    log: Callable | None = None,
) -> tuple[list[Path], dict]:
    files: list[Path] = []
    ignored_extensions: set[str] = set()
    inaccessible_dirs: list[dict] = []
    directories_scanned = 0
    files_seen = 0
    ignored_logs = 0
    matched_logs = 0
    temp_lock_skipped = 0

    log_event(log, "info", "Scan da pasta monitorada iniciado.", metadata={"folder_path": str(folder)})
    stack = [folder]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                current_entries = list(entries)
        except OSError as exc:
            if current == folder:
                raise
            inaccessible_dirs.append({"path": str(current), "error": str(exc)})
            log_event(log, "warning", "Subpasta inacessivel durante scan.", metadata={"path": str(current), "error": str(exc)})
            continue

        directories_scanned += 1
        if directories_scanned == 1 or directories_scanned % 25 == 0:
            log_event(log, "info", "Entrando em pasta monitorada.", metadata={"path": str(current), "directories_scanned": directories_scanned})
        for entry in current_entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError as exc:
                inaccessible_dirs.append({"path": entry.path, "error": str(exc)})
                log_event(log, "warning", "Item inacessivel durante scan.", metadata={"path": entry.path, "error": str(exc)})
                continue

            files_seen += 1
            path = Path(entry.path)
            if is_temp_or_lock_file(path.name):
                temp_lock_skipped += 1
                if ignored_logs < MAX_IGNORED_FILE_LOGS:
                    ignored_logs += 1
                    log_event(log, "info", f"Arquivo temporario/bloqueio ignorado: {path.name}", metadata={"path": str(path), "reason": "office_temp_or_lock"})
                continue
            extension = path.suffix.lower() or "<no_extension>"
            if path.suffix.lower() in enabled_exts:
                files.append(path)
                if matched_logs < MAX_MATCHED_FILE_LOGS:
                    matched_logs += 1
                    log_event(log, "info", f"Arquivo compativel encontrado: {path.name}", metadata={"path": str(path), "extension": extension})
            else:
                ignored_extensions.add(extension)
                if ignored_logs < MAX_IGNORED_FILE_LOGS:
                    ignored_logs += 1
                    log_event(log, "info", f"Arquivo ignorado por extensao: {path.name}", metadata={"path": str(path), "extension": extension})

    stats = {
        "directories_scanned": directories_scanned,
        "files_seen": files_seen,
        "matched_files": len(files),
        "allowed_extensions": sorted(enabled_exts),
        "ignored_extensions": sorted(ignored_extensions),
        "temp_lock_skipped": temp_lock_skipped,
        "inaccessible_dirs_count": len(inaccessible_dirs),
        "inaccessible_dirs": inaccessible_dirs[:20],
    }
    log_event(log, "info", "Scan da pasta monitorada concluido.", metadata=stats)
    return files, stats


def no_files_message(scan_stats: dict) -> str:
    allowed = ", ".join(scan_stats.get("allowed_extensions") or []) or "none"
    ignored = ", ".join((scan_stats.get("ignored_extensions") or [])[:12]) or "none"
    return (
        "No compatible files found in monitored folder/subfolders. "
        f"Folders scanned: {scan_stats.get('directories_scanned', 0)}; "
        f"files seen: {scan_stats.get('files_seen', 0)}; "
        f"allowed extensions: {allowed}; ignored extensions: {ignored}."
    )


def staging_base_path(value: str | None) -> Path:
    normalized = normalize_folder_path(value)
    if normalized:
        path = Path(normalized)
        return path if path.is_absolute() else resolve_backend_path(normalized)
    return runtime_path("TEMP_PATH")


def unique_staging_path(staging_dir: Path, source: Path, used_names: set[str]) -> Path:
    name = source.name
    stem = source.stem or "file"
    suffix = source.suffix
    index = 1
    while name.lower() in used_names or (staging_dir / name).exists():
        name = f"{stem}_{index}{suffix}"
        index += 1
    used_names.add(name.lower())
    return staging_dir / name


def safe_automation_folder_name(value: str | None, automation_id: int) -> str:
    name = str(value or "").strip() or f"automation_{automation_id}"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name)
    name = re.sub(r"\s+", "_", name).strip(" ._")
    return name or f"automation_{automation_id}"


def copy_files_to_staging(
    *,
    automation_id: int,
    automation_name: str | None,
    source_files: list[Path],
    batch_size: int,
    temp_folder_path: str | None,
    log: Callable | None = None,
) -> tuple[list[dict], dict]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    folder_name = safe_automation_folder_name(automation_name, automation_id)
    staging_dir = staging_base_path(temp_folder_path) / f"{folder_name}_{timestamp}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    safe_batch_size = max(1, int(batch_size or 1))
    staged_files: list[dict] = []
    skipped_files: list[dict] = []
    used_names: set[str] = set()
    copied_logs = 0

    log_event(
        log,
        "info",
        "Copia para pasta temporaria iniciada.",
        metadata={"staging_dir": str(staging_dir), "source_files": len(source_files), "batch_size": safe_batch_size},
    )
    for source in source_files:
        batch_number = (len(staged_files) // safe_batch_size) + 1
        batch_dir = staging_dir / f"lote_{batch_number:03d}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        target = unique_staging_path(batch_dir, source, used_names)
        try:
            shutil.copy2(source, target)
            size_bytes = target.stat().st_size
        except Exception as exc:
            skipped = {"path": str(source), "target_path": str(target), "error": str(exc)}
            skipped_files.append(skipped)
            log_event(log, "warning", f"Arquivo nao copiado para temporario: {source.name}", metadata=skipped)
            continue
        staged_files.append(
            {
                "source_path": source,
                "staged_path": target,
                "file_name": target.name,
                "extension": target.suffix.lower(),
                "size_bytes": size_bytes,
                "batch_number": batch_number,
                "batch_folder_path": str(batch_dir),
            }
        )
        if len(staged_files) == 1 or staged_files[-2]["batch_number"] != batch_number:
            log_event(
                log,
                "info",
                f"Subpasta de lote criada: lote_{batch_number:03d}",
                metadata={"batch_number": batch_number, "batch_folder_path": str(batch_dir), "batch_size": safe_batch_size},
            )
        if copied_logs < MAX_COPIED_FILE_LOGS:
            copied_logs += 1
            log_event(
                log,
                "info",
                f"Arquivo copiado para temporario: {target.name}",
                metadata={
                    "source_path": str(source),
                    "temp_path": str(target),
                    "size_bytes": size_bytes,
                    "batch_number": batch_number,
                    "batch_folder_path": str(batch_dir),
                },
            )

    batch_folders = []
    for batch_number in sorted({item["batch_number"] for item in staged_files}):
        batch_items = [item for item in staged_files if item["batch_number"] == batch_number]
        batch_folders.append(
            {
                "batch_number": batch_number,
                "batch_folder_path": batch_items[0]["batch_folder_path"],
                "files_count": len(batch_items),
            }
        )
    stats = {
        "staging_dir": str(staging_dir),
        "staged_files_count": len(staged_files),
        "copy_failed_count": len(skipped_files),
        "copy_failed_files": skipped_files[:20],
        "batch_size": safe_batch_size,
        "batch_count": len(batch_folders),
        "batch_folders": batch_folders,
    }
    log_event(log, "info", "Copia para pasta temporaria concluida.", metadata=stats)
    return staged_files, stats


def no_files_copied_message(copy_stats: dict, scan_stats: dict) -> str:
    return (
        "No files were copied to temp for upload. "
        f"Matched source files: {scan_stats.get('matched_source_files', 0)}; "
        f"copy failures: {copy_stats.get('copy_failed_count', 0)}; "
        f"staging dir: {copy_stats.get('staging_dir')}."
    )
