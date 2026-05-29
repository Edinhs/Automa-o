from __future__ import annotations

import argparse
import getpass
import os
import sys

from app.core.security import get_password_hash
from app.db.session import session_for_environment
from app.models.user import DEFAULT_THEME_PREFERENCE, User


def prompt_value(label: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    if secret:
        value = getpass.getpass(f"{label}{suffix}: ")
    else:
        value = input(f"{label}{suffix}: ").strip()
    return value or default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or update the initial Automation HUB admin user.")
    parser.add_argument("--network-id", default=os.getenv("INITIAL_ADMIN_NETWORK_ID", "ADMIN"))
    parser.add_argument("--name", default=os.getenv("INITIAL_ADMIN_NAME", "Administrador Automation HUB"))
    parser.add_argument("--email", default=os.getenv("INITIAL_ADMIN_EMAIL", "admin@stellantis.local"))
    parser.add_argument("--password", default=os.getenv("INITIAL_ADMIN_PASSWORD", ""))
    parser.add_argument("--environment", choices=["operational", "developer"], default="operational")
    parser.add_argument("--non-interactive", action="store_true", default=os.getenv("INITIAL_ADMIN_NON_INTERACTIVE") == "1")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    network_id = args.network_id.strip().upper()
    name = args.name.strip()
    email = args.email.strip().lower()
    password = args.password

    if not args.non_interactive:
        network_id = prompt_value("Network ID do admin", network_id).strip().upper()
        name = prompt_value("Nome do admin", name).strip()
        email = prompt_value("E-mail do admin", email).strip().lower()
        if not password:
            password = prompt_value("Senha do admin", secret=True)
            confirmation = prompt_value("Confirmar senha", secret=True)
            if password != confirmation:
                print("ERRO: As senhas nao conferem.", file=sys.stderr)
                return 1

    if not network_id or not name or not email or not password:
        print("ERRO: network-id, name, email e password sao obrigatorios.", file=sys.stderr)
        return 1
    if len(password) < 8:
        print("ERRO: a senha deve ter pelo menos 8 caracteres.", file=sys.stderr)
        return 1

    db = session_for_environment(args.environment)
    try:
        user = db.query(User).filter(User.network_id == network_id).first()
        if user:
            user.name = name
            user.email = email
            user.role = "admin"
            user.status = "active"
            user.is_deleted = False
            user.password_hash = get_password_hash(password)
            user.theme_preference = user.theme_preference or DEFAULT_THEME_PREFERENCE
            action = "atualizado"
        else:
            user = User(
                name=name,
                email=email,
                network_id=network_id,
                role="admin",
                status="active",
                password_hash=get_password_hash(password),
                theme_preference=DEFAULT_THEME_PREFERENCE,
            )
            db.add(user)
            action = "criado"
        db.commit()
        print(f"Admin {action}: {network_id} ({args.environment})")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
