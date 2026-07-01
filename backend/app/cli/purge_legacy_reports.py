from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import environment_scope, runtime_path
from app.db.session import session_for_environment
from app.models.execution import ExecutionReport
from app.services.audit import create_log


def report_files(reports_dir: Path) -> list[Path]:
    resolved_dir = reports_dir.resolve()
    if not resolved_dir.exists():
        return []
    return [
        path
        for path in resolved_dir.rglob("*")
        if path.is_file() and resolved_dir in path.resolve().parents
    ]


def purge_legacy_reports(db: Session, reports_dir: Path, apply: bool = False) -> dict:
    files = report_files(reports_dir)
    report_count = db.query(ExecutionReport).count()
    result = {
        "mode": "apply" if apply else "check",
        "execution_reports": report_count,
        "report_files": len(files),
        "reports_path": str(reports_dir.resolve()),
    }
    if not apply:
        return result

    db.query(ExecutionReport).delete(synchronize_session=False)
    for path in files:
        path.unlink(missing_ok=True)
    db.commit()
    create_log(
        db,
        "warning",
        "Atualizacao de relatorios aplicada; historico anterior removido.",
        "maintenance",
        metadata={"deleted_reports": report_count, "deleted_report_files": len(files)},
    )
    result["deleted_reports"] = report_count
    result["deleted_report_files"] = len(files)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Confere ou remove relatorios anteriores ao escopo de monitoramento de pasta.")
    parser.add_argument("--apply", action="store_true", help="Exclui registros existentes e arquivos em REPORTS_PATH.")
    parser.add_argument("--environment", choices=["operational", "developer"], default="operational")
    args = parser.parse_args()
    with environment_scope(args.environment):
        db = session_for_environment(args.environment)
        try:
            result = purge_legacy_reports(db, runtime_path("REPORTS_PATH"), apply=args.apply)
        finally:
            db.close()
    result["environment"] = args.environment
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
