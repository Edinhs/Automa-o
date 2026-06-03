"""parse_json_object: decodificacao tolerante dos campos *_json do banco.

Substitui as 3 copias antigas (agents/executions/reports) e remove o fallback
ast.literal_eval. Garante que entrada vazia/invalida/nao-objeto vira {}.
"""

from app.core.serialization import parse_json_object


def test_objeto_valido():
    assert parse_json_object('{"automation_id": 7, "batch_size": 5}') == {
        "automation_id": 7,
        "batch_size": 5,
    }


def test_vazio_e_none():
    assert parse_json_object(None) == {}
    assert parse_json_object("") == {}


def test_json_invalido_vira_dict_vazio():
    assert parse_json_object("{nao eh json}") == {}


def test_json_valido_mas_nao_objeto_vira_dict_vazio():
    assert parse_json_object("[1, 2, 3]") == {}
    assert parse_json_object('"texto"') == {}
    assert parse_json_object("42") == {}


def test_nao_executa_expressao_python():
    # O fallback ast.literal_eval foi removido; isto NAO deve virar dict nem executar nada.
    assert parse_json_object("{'chave': 'aspas simples'}") == {}
