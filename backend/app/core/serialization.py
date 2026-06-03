from __future__ import annotations

import json
from typing import Any


def parse_json_object(raw: str | None) -> dict[str, Any]:
    """Decodifica uma string JSON para dict, tolerando entrada vazia/invalida.

    Retorna {} quando raw e vazio, nao e JSON valido, ou nao decodifica para um objeto.
    Os campos *_json no banco (payload_json, config_json, metadata_json) sao sempre
    gravados como JSON pelo proprio backend, entao nao ha necessidade de fallbacks
    como ast.literal_eval — JSON estrito basta e evita ambiguidade.
    """
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}
