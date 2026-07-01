"""safe_db_maintenance.py -- Manutencao SEGURA do banco SQLite (preservando dados).

Utilitario chamado pelo `atualizar_producao.bat`. Faz as operacoes data-criticas em Python
(em vez de `python -c` inline no batch) para evitar erros de aspas e garantir robustez.

Comandos:
  backup  --env <operational|developer> --dest <pasta>
      Faz CHECKPOINT do WAL (consolida `-wal`/`-shm` no `.db`), copia o `.db` (+ sidecars que
      restarem) para <pasta> e grava `counts.json` com a contagem de linhas por tabela (PRE).
  verify  --env <...> --backup <pasta>
      Recomputa a contagem e compara com o `counts.json` do backup. FALHA (exit 1) se qualquer
      tabela presente no PRE sumiu ou perdeu linhas -- migracoes aditivas nunca reduzem linhas.
  restore --env <...> --backup <pasta>
      Restaura o `.db` (+ sidecars) do backup sobre o banco ativo (rollback).

Regras de seguranca:
  * Recusa-se a operar se a URL do ambiente nao for `sqlite:///` (este utilitario e so para SQLite).
  * Se o `.db` do ambiente nao existir (ex.: developer ausente em producao), faz SKIP com exit 0.

Uso (a partir de backend/, com a venv):
  .venv\\Scripts\\python.exe -m app.cli.safe_db_maintenance backup --env operational --dest ..\\backups\\X\\operational
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from app.core.config import database_url_for_environment, resolve_backend_path


def _db_path(env: str) -> Path:
    url = database_url_for_environment(env)
    if not url.startswith("sqlite:///"):
        print(
            f"[ERRO] Ambiente '{env}' nao usa SQLite (url={url!r}). "
            f"Este utilitario e exclusivo para SQLite. Abortando.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    raw = url.replace("sqlite:///", "", 1)
    return resolve_backend_path(raw)


def _sidecar_names(db: Path) -> list[str]:
    return [db.name, db.name + "-wal", db.name + "-shm"]


def _checkpoint_wal(db: Path) -> None:
    """Consolida o WAL no arquivo principal para que o backup do `.db` fique completo."""
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def _table_counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name <> 'alembic_version' "
            "ORDER BY name"
        )
        tables = [row[0] for row in cur.fetchall()]
        counts: dict[str, int] = {}
        for table in tables:
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            counts[table] = int(cur.fetchone()[0])
        return counts
    finally:
        conn.close()


def cmd_backup(env: str, dest: str) -> int:
    db = _db_path(env)
    if not db.exists():
        print(f"[SKIP] Banco do ambiente '{env}' nao existe ({db}). Nada a salvar.")
        return 0

    _checkpoint_wal(db)

    dest_dir = Path(dest)
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in _sidecar_names(db):
        src = db.with_name(name)
        if src.exists():
            shutil.copy2(str(src), str(dest_dir / name))
            copied += 1

    counts = _table_counts(db)
    meta = {"env": env, "db": str(db), "db_name": db.name, "counts": counts}
    (dest_dir / "counts.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    total = sum(counts.values())
    print(f"[OK] Backup '{env}': {db.name} -> {dest_dir} ({copied} arquivo(s), {len(counts)} tabelas, {total} linhas)")
    return 0


def cmd_verify(env: str, backup: str) -> int:
    meta_file = Path(backup) / "counts.json"
    if not meta_file.exists():
        print(f"[SKIP] Sem counts.json em {backup} (ambiente nao foi salvo). Verificacao pulada.")
        return 0

    db = _db_path(env)
    if not db.exists():
        print(f"[FALHA] Banco '{env}' nao existe apos a migracao ({db}).", file=sys.stderr)
        return 1

    pre = json.loads(meta_file.read_text(encoding="utf-8")).get("counts", {})
    post = _table_counts(db)

    problems: list[str] = []
    for table, pre_n in pre.items():
        if table not in post:
            problems.append(f"{table}: PRE={pre_n} -> TABELA AUSENTE")
        elif post[table] < pre_n:
            problems.append(f"{table}: PRE={pre_n} -> POS={post[table]} (perdeu {pre_n - post[table]})")

    if problems:
        print(f"[FALHA] Ambiente '{env}' PERDEU dados apos a migracao:", file=sys.stderr)
        for item in problems:
            print("   - " + item, file=sys.stderr)
        return 1

    grew = sum(1 for t, n in post.items() if n > pre.get(t, 0))
    print(
        f"[OK] Verificacao '{env}': nenhuma tabela perdeu linhas "
        f"({len(pre)} conferidas, {grew} cresceram, {len(post) - len(pre)} tabela(s) nova(s))."
    )
    return 0


def cmd_restore(env: str, backup: str) -> int:
    backup_dir = Path(backup)
    meta_file = backup_dir / "counts.json"
    if not meta_file.exists():
        print(f"[SKIP] Sem backup para '{env}' em {backup_dir}. Nada a restaurar.")
        return 0

    db = _db_path(env)
    # Remove os sidecars atuais (WAL/SHM) antes de restaurar para nao misturar estados.
    for name in _sidecar_names(db):
        target = db.with_name(name)
        try:
            if target.exists():
                target.unlink()
        except OSError as exc:
            print(f"[AVISO] Nao consegui remover {target.name}: {exc}", file=sys.stderr)

    restored = 0
    for name in _sidecar_names(db):
        src = backup_dir / name
        if src.exists():
            shutil.copy2(str(src), str(db.with_name(name)))
            restored += 1

    print(f"[OK] Restore '{env}': {restored} arquivo(s) de {backup_dir} -> {db.parent}")
    return 0 if restored else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manutencao segura do banco SQLite (preserva dados).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("backup", "verify", "restore"):
        sp = sub.add_parser(name)
        sp.add_argument("--env", required=True, choices=["operational", "developer"])
        sp.add_argument("--dest", help="(backup) pasta destino do backup")
        sp.add_argument("--backup", help="(verify/restore) pasta do backup gerado")

    args = parser.parse_args(argv)
    if args.cmd == "backup":
        if not args.dest:
            parser.error("backup requer --dest")
        return cmd_backup(args.env, args.dest)
    if args.cmd == "verify":
        if not args.backup:
            parser.error("verify requer --backup")
        return cmd_verify(args.env, args.backup)
    if args.cmd == "restore":
        if not args.backup:
            parser.error("restore requer --backup")
        return cmd_restore(args.env, args.backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
