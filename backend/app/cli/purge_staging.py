from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from app.core.config import environment_scope, runtime_path, settings


def staging_dirs(temp_dir: Path) -> list[Path]:
    """Subpastas de primeiro nivel do TEMP_PATH — cada execucao de automacao cria uma."""
    resolved = temp_dir.resolve()
    if not resolved.exists():
        return []
    return [child for child in resolved.iterdir() if child.is_dir()]


def purge_staging(temp_dir: Path, retention_days: int, apply: bool = False) -> dict:
    """Remove pastas de staging mais antigas que retention_days (por mtime).

    retention_days <= 0 mantem o comportamento padrao (nao apaga nada): a automacao
    NAO limpa o staging de proposito. O cleanup so acontece quando o operador habilita
    a retencao explicitamente (env STAGING_RETENTION_DAYS ou --retention-days).
    """
    resolved = temp_dir.resolve()
    result = {
        "mode": "apply" if apply else "check",
        "temp_path": str(resolved),
        "retention_days": retention_days,
        "candidates": [],
        "deleted": [],
    }
    if retention_days <= 0:
        result["note"] = "retencao desativada (retention_days <= 0); nenhuma pasta sera removida."
        return result

    cutoff = time.time() - retention_days * 86400
    for path in staging_dirs(resolved):
        try:
            if path.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        result["candidates"].append(str(path))
        if apply:
            shutil.rmtree(path, ignore_errors=True)
            result["deleted"].append(str(path))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Confere ou remove pastas de staging (temp) antigas. Opt-in: so age com retention_days > 0."
    )
    parser.add_argument("--apply", action="store_true", help="Remove de fato as pastas elegiveis.")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help="Sobrescreve STAGING_RETENTION_DAYS. 0 ou negativo desativa.",
    )
    parser.add_argument("--environment", choices=["operational", "developer"], default="operational")
    args = parser.parse_args()

    retention_days = args.retention_days if args.retention_days is not None else settings.STAGING_RETENTION_DAYS
    with environment_scope(args.environment):
        result = purge_staging(runtime_path("TEMP_PATH"), retention_days, apply=args.apply)
    result["environment"] = args.environment
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
