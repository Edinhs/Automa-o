r"""
test_report_teams_card.py -- Testes deterministicos (sem DB/navegador) do card semanal do Teams
(Relatorio Simplificado virou um CONVITE de adocao) e da entrega via Power Automate:

  1. build_card_summary(..., business=...) -> card "kind=adoption" com manchete-convite, horas
     economizadas (semana+acumulado), adocao (engenheiros/SPECs) e saude em 1 linha; SEM tabela.
  2. build_adaptive_card -> Adaptive Card 1.4 com 2 FactSets, botoes "Solicitar acesso"(quando
     access_url setado) + "Ver detalhes (PDF)", e sem previa SPEC-por-SPEC.
  3. build_report_image_card -> card com 1 Image (PNG) + botoes [Abrir Playground, Solicitar Acesso,
     Baixar Relatorio (PDF)]; build_report_image_html/_svg_line_chart -> poster HTML/SVG offline,
     sem CTAs visuais embutidos no PNG.
  4. _format_hours (minutos->horas) e o fallback de "Periodo" (nunca em branco).
  5. write_report_to_delivery_folder -> grava relatorio + PDF companheiro + sidecar '*.meta.json';
     com image_data e PNG gerado -> card-imagem + image_file; senao -> fallback card-texto de adocao.

Uso: a partir de backend/  ->  .venv\Scripts\python.exe scripts\test_report_teams_card.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# A pasta de entrega e lida das settings no import; aponta para um diretorio temporario
# ANTES de importar o app (settings sao instanciadas no import de app.core.config).
_DELIVERY_DIR = Path(tempfile.mkdtemp(prefix="teams_card_delivery_"))
os.environ["REPORT_DELIVERY_PATH"] = str(_DELIVERY_DIR)

import app.routers.reports as rp  # noqa: E402


class _FakeReport:
    """Suficiente para build_card_summary / write_report_to_delivery_folder."""

    def __init__(self, name: str):
        self.id = 12
        self.name = name
        self.period_start = datetime(2026, 5, 25, 0, 0, 0)
        self.period_end = datetime(2026, 6, 24, 23, 59, 59)
        self.created_at = datetime(2026, 6, 24, 14, 30, 22)


def _simplificado_section() -> rp.ReportSection:
    return rp.ReportSection(
        "simplificado",
        rp.REPORT_BLOCKS["simplificado"],
        ["SPEC", "PORCENTAGEM", "STATUS", "OBSERVAÇÃO", "ULTIMA ATUALIZAÇÃO", "ARQUIVOS"],
        [
            ["WS A", "100%", "COMPLETO", "Disponivel no Playground", datetime(2026, 6, 24, 10, 0), 10],
            ["WS B", "90%", "ERRO", "Tratamento de erros", datetime(2026, 6, 24, 11, 0), 5],
            ["WS C", "40%", "PROGRESSO", "Enviando para Playground", datetime(2026, 6, 24, 12, 0), 3],
        ],
    )


def _filters() -> dict:
    return {
        "start": datetime(2026, 5, 25, 0, 0, 0),
        "end": datetime(2026, 6, 24, 23, 59, 59),
        "automation_id": None,
        "workspace_id": None,
        "status": None,
        "source_task_id": None,
    }


def _business() -> dict:
    """Numeros de negocio montados a mao (compute_card_business precisa de DB; aqui simulamos)."""
    return {
        "hours": {"week": "12.0 h", "total": "120 h", "files_week": 180, "files_total": 1800, "minutes_per_file": 4.0},
        "adoption": {"engineers": 7, "specs_ready": 23},
        "health": {"items": 2},
    }


def test_card_summary_adoption() -> None:
    rep = _FakeReport("Relatório Simplificado (XLSX) - 24/06/2026 14:30")
    card = rp.build_card_summary("Relatório Simplificado", [_simplificado_section()], rep, _filters(), business=_business())

    assert card["kind"] == "adoption", card
    assert card["headline"] == rp.CARD_HEADLINE and "agente" in card["headline"].lower(), card["headline"]
    assert card["period"].count("/") >= 4, f"Periodo deve ter 2 datas, veio: {card['period']!r}"
    assert card["hours"]["week"] == "12.0 h" and card["hours"]["total"] == "120 h", card["hours"]
    assert card["adoption"] == {"engineers": 7, "specs_ready": 23}, card["adoption"]
    assert card["health"]["items"] == 2, card["health"]
    # O card de adocao NAO carrega tabela/previa SPEC-por-SPEC.
    assert not card.get("preview", {}).get("rows"), card.get("preview")
    print("[PASS] build_card_summary -> card de adocao (convite + horas + adocao + saude), sem tabela")


def test_adoption_card_shape() -> None:
    rep = _FakeReport("Relatório Simplificado")
    card = rp.build_card_summary("Relatório Simplificado", [_simplificado_section()], rep, _filters(), business=_business())
    card["access_url"] = "https://teams.microsoft.com/l/app/abc123"
    ac = rp.build_adaptive_card(card)

    assert ac["type"] == "AdaptiveCard" and ac["version"] == "1.4", ac
    blob = json.dumps(ac, ensure_ascii=False)
    assert rp.CARD_HEADLINE in blob, "manchete-convite ausente"
    assert "Não tem acesso ao workspace" in blob, "linha 'como pedir acesso' ausente no convite"
    # 2 FactSets: horas (semana/acumulado) + adocao (engenheiros/SPECs).
    assert sum(1 for el in ac["body"] if el.get("type") == "FactSet") == 2, "esperava 2 FactSets"
    # Sem logo e sem tabela -> nenhum ColumnSet no corpo.
    assert sum(1 for el in ac["body"] if el.get("type") == "ColumnSet") == 0, "nao deveria haver tabela/ColumnSet"
    assert "Previa" not in blob, "nao deveria existir previa SPEC-por-SPEC"
    # Ordem do prompt: convite -> horas -> adocao -> saude (saude por ultimo).
    texts = [el.get("text", "") for el in ac["body"]]
    i_horas = next(i for i, t in enumerate(texts) if "Tempo devolvido" in t)
    i_adocao = next(i for i, t in enumerate(texts) if "Quem já está usando" in t)
    i_saude = next(i for i, t in enumerate(texts) if "tratamento" in t or "Tudo certo" in t)
    assert i_horas < i_adocao < i_saude, f"ordem errada: horas={i_horas} adocao={i_adocao} saude={i_saude}"
    titles = [a.get("title") for a in ac.get("actions", [])]
    assert titles == ["Solicitar acesso", "Ver detalhes (PDF)"], titles
    assert any(a.get("url") == rp.DOWNLOAD_URL_PLACEHOLDER for a in ac["actions"]), "placeholder do PDF ausente"
    json.dumps(ac, ensure_ascii=False)  # serializavel
    print("[PASS] build_adaptive_card -> ordem convite->horas->adocao->saude + linha de acesso + 2 botoes")


def _image_data() -> dict:
    """Dados do poster-convite montados a mao (compute_card_image_data precisa de DB; aqui simulamos)."""
    return {
        "brand": "STELLANTIS AUTOMATION HUB",
        "title": "CONVITE — AUTOMATION HUB",
        "period": "19/06/2026 a 25/06/2026",
        "generated_at": "25/06/2026 11:01",
        "headline": rp.CARD_HEADLINE,
        "invite_body": rp.CARD_INVITE_BODY,
        "access_line": rp.CARD_ACCESS_LINE,
        "playground_url": "https://genai.stellantis.com/",
        "hours": {"week": "11,3 h", "total": "42,5 h"},
        "hours_series": [{"label": f"{d:02d}/06", "value": 16.5 + (d - 19) * 4.3} for d in range(19, 26)],
        "adoption": {"engineers": 7, "specs_ready": 23},
        "health": {"items": 2, "eta": rp.CARD_HEALTH_ETA},
    }


def test_image_card_shape() -> None:
    # Com access_url setado -> 3 botoes (Abrir Playground, Solicitar Acesso, Baixar Relatorio (PDF)).
    old = rp.settings.REPORT_CARD_ACCESS_URL
    rp.settings.REPORT_CARD_ACCESS_URL = "https://teams.microsoft.com/l/app/abc123"
    try:
        ac = rp.build_report_image_card()
    finally:
        rp.settings.REPORT_CARD_ACCESS_URL = old
    assert ac["type"] == "AdaptiveCard" and ac["version"] == "1.4", ac
    imgs = [el for el in ac["body"] if el.get("type") == "Image"]
    assert len(imgs) == 1 and imgs[0]["url"] == rp.IMAGE_URL_PLACEHOLDER, ac["body"]
    titles = [a.get("title") for a in ac["actions"]]
    assert titles == ["Abrir Playground", "Solicitar Acesso", "Baixar Relatório (PDF)"], titles
    assert any(a.get("url") == rp.DOWNLOAD_URL_PLACEHOLDER for a in ac["actions"]), "placeholder do PDF ausente"

    # Sem access_url -> some o botao "Solicitar Acesso".
    old2 = rp.settings.REPORT_CARD_ACCESS_URL
    rp.settings.REPORT_CARD_ACCESS_URL = ""
    try:
        titles2 = [a.get("title") for a in rp.build_report_image_card()["actions"]]
    finally:
        rp.settings.REPORT_CARD_ACCESS_URL = old2
    assert titles2 == ["Abrir Playground", "Baixar Relatório (PDF)"], titles2
    print("[PASS] build_report_image_card -> 1 Image + botoes (Solicitar Acesso condicional)")


def test_image_html_and_chart_offline() -> None:
    from app.services.report_image import build_report_image_html, _svg_line_chart

    data = _image_data()
    svg = _svg_line_chart(data["hours_series"])
    assert svg.startswith("<svg") and "polyline" in svg, "SVG do grafico invalido"
    html = build_report_image_html(data)
    assert html.lstrip().lower().startswith("<!doctype html"), "HTML sem doctype"
    # Poster na ordem do convite: manchete -> horas -> adocao -> saude.
    for needle in (
        "crie seu agente", "Tempo devolvido ao time", "11,3 h", "42,5 h",
        "Engenheiros já usando", "SPECs prontas no ambiente", "em tratamento",
        "previsão de correção",
    ):
        assert needle in html, f"faltou '{needle}' no HTML do poster"
    # O que saiu de cena: KPI de contagem de arquivos, tabela SPEC-por-SPEC e workspaces.
    for gone in ("SPEC_341", "Arquivos Processados", "Workspaces Disponíveis", "table", "Abrir Playground", "Baixar Relatório (PDF)"):
        assert gone not in html, f"'{gone}' nao deveria mais aparecer no poster-convite"
    assert "<script" not in html.lower(), "poster deve ser 100% offline (sem <script>)"
    print("[PASS] build_report_image_html + _svg_line_chart -> poster-convite (horas/adocao/saude), sem tabela")


def test_count_unique_requesters() -> None:
    from app.services.access_requests import count_unique_requesters

    assert count_unique_requesters([" TA25413 ", "ta25413", "", "  ", None, "AbC123", "abc123", "ZX9"]) == 3
    assert count_unique_requesters([]) == 0
    print("[PASS] count_unique_requesters -> trim + case-insensitive + ignora vazios")


def test_adoption_card_health_and_logo() -> None:
    rep = _FakeReport("Relatório Simplificado")
    # Saude com itens -> aviso; com logo -> Image no cabecalho.
    card = rp.build_card_summary("Relatório Simplificado", [_simplificado_section()], rep, _filters(), business=_business())
    card["logo_url"] = "https://exemplo.com/stellantis-logo.png"
    blob = json.dumps(rp.build_adaptive_card(card), ensure_ascii=False)
    assert '"Image"' in blob and "https://exemplo.com/stellantis-logo.png" in blob, "logo Image ausente"
    assert "em tratamento" in blob, "saude (itens em tratamento) ausente"

    # Sem logo e saude zerada -> sem Image e linha 'Tudo saudavel'; sem botao 'Solicitar acesso'.
    healthy = rp.build_card_summary("Relatório Simplificado", [_simplificado_section()], rep, _filters(),
                                    business={**_business(), "health": {"items": 0}})
    ac = rp.build_adaptive_card(healthy)
    blob2 = json.dumps(ac, ensure_ascii=False)
    assert '"Image"' not in blob2, "nao deveria haver Image sem logo"
    assert "Tudo certo" in blob2, "linha 'Tudo certo' (saude verde) ausente"
    assert [a.get("title") for a in ac["actions"]] == ["Ver detalhes (PDF)"], "sem access_url nao deve ter botao Solicitar acesso"
    print("[PASS] build_adaptive_card -> logo opcional, saude verde/amarela e botao de acesso condicional")


def test_minutes_to_hours() -> None:
    assert rp._format_hours(0) == "0 min", rp._format_hours(0)
    assert rp._format_hours(30) == "30 min", rp._format_hours(30)   # < 1h -> minutos
    assert rp._format_hours(90) == "1,5 h", rp._format_hours(90)    # 1-10h -> 1 decimal (pt-BR, virgula)
    assert rp._format_hours(600) == "10 h", rp._format_hours(600)   # >= 10h -> sem decimal
    assert rp._format_hours(725) == "12 h", rp._format_hours(725)
    print("[PASS] _format_hours -> minutos convertidos em horas legiveis (4 min/arquivo)")


def test_period_fallback() -> None:
    rep = _FakeReport("Relatório Simplificado")
    empty = {"start": None, "end": None, "automation_id": None, "workspace_id": None, "status": None, "source_task_id": None}
    card = rp.build_card_summary("Relatório Simplificado", [_simplificado_section()], rep, empty, business=_business())
    assert card["period"].count("/") >= 4, f"Periodo deve cair no fallback (7 dias), veio: {card['period']!r}"
    print("[PASS] build_card_summary -> 'Periodo' nunca em branco (fallback de 7 dias)")


def _bundle(rep: _FakeReport, filename: str, content: bytes, file_format: str) -> dict:
    card = rp.build_card_summary("Relatório Simplificado", [_simplificado_section()], rep, _filters(), business=_business())
    return {
        "report": rep,
        "report_type": "Relatório Simplificado",
        "file_format": file_format,
        "content": content,
        "filename": filename,
        "media_type": rp.MEDIA_TYPES[file_format],
        "summary": "x",
        "sections": [_simplificado_section()],
        "card": card,
        "adaptive_card": rp.build_adaptive_card(card),
        "pdf_content": b"%PDF-1.4 companheiro\n",
        "pdf_filename": f"{Path(filename).stem}.pdf",
    }


def _read_sidecar(stem: str) -> dict:
    return json.loads((_DELIVERY_DIR / f"{stem}.meta.json").read_text(encoding="utf-8"))


def test_delivery_xlsx_writes_three_files() -> None:
    rep = _FakeReport("Relatório Simplificado (XLSX)")
    stem = "relatorio_simplificado_xlsx_20260624_000001"
    bundle = _bundle(rep, f"{stem}.xlsx", b"xlsx-bytes", "xlsx")
    rp.write_report_to_delivery_folder(bundle)

    assert (_DELIVERY_DIR / f"{stem}.xlsx").exists(), "relatorio xlsx ausente"
    assert (_DELIVERY_DIR / f"{stem}.pdf").exists(), "PDF companheiro ausente"
    sidecar = _read_sidecar(stem)
    assert sidecar["attachment_file"] == f"{stem}.pdf", sidecar
    assert sidecar["report_file"] == f"{stem}.xlsx", sidecar
    assert sidecar["adaptive_card"]["type"] == "AdaptiveCard", sidecar
    assert sidecar["card"]["kind"] == "adoption", sidecar["card"]
    assert sidecar["download_url_placeholder"] == rp.DOWNLOAD_URL_PLACEHOLDER, sidecar
    assert rp.DOWNLOAD_URL_PLACEHOLDER in json.dumps(sidecar["adaptive_card"]), "placeholder ausente no card"
    print("[PASS] entrega xlsx -> relatorio + PDF companheiro + sidecar .meta.json com card de adocao")


def test_delivery_json_not_overwritten() -> None:
    rep = _FakeReport("Relatório Simplificado (JSON)")
    stem = "relatorio_simplificado_json_20260624_000002"
    original = b'{"relatorio":"conteudo-json-original"}'
    bundle = _bundle(rep, f"{stem}.json", original, "json")
    rp.write_report_to_delivery_folder(bundle)

    report_file = _DELIVERY_DIR / f"{stem}.json"
    assert report_file.exists() and report_file.read_bytes() == original, "relatorio .json foi sobrescrito!"
    assert (_DELIVERY_DIR / f"{stem}.pdf").exists(), "PDF companheiro ausente (json)"
    sidecar = _read_sidecar(stem)
    assert sidecar["attachment_file"] == f"{stem}.pdf", sidecar
    print("[PASS] entrega json -> sidecar .meta.json (nao colide); relatorio .json preservado")


def test_delivery_pdf_reuses_report_as_attachment() -> None:
    rep = _FakeReport("Relatório Simplificado (PDF)")
    stem = "relatorio_simplificado_pdf_20260624_000003"
    bundle = _bundle(rep, f"{stem}.pdf", b"%PDF-1.4 relatorio\n", "pdf")
    rp.write_report_to_delivery_folder(bundle)

    sidecar = _read_sidecar(stem)
    # Relatorio ja e PDF: o anexo e o proprio arquivo (sem duplicar).
    assert sidecar["attachment_file"] == f"{stem}.pdf" == sidecar["report_file"], sidecar
    print("[PASS] entrega pdf -> anexo reutiliza o proprio relatorio (sem PDF duplicado)")


def test_delivery_image_card_and_fallback() -> None:
    rep = _FakeReport("Relatório Simplificado (XLSX)")
    original = rp._render_report_image_threaded

    # (a) Render OK -> card-imagem (Image + image_file/image_url_placeholder no sidecar).
    stem = "relatorio_simplificado_img_20260624_000004"
    bundle = _bundle(rep, f"{stem}.xlsx", b"xlsx-bytes", "xlsx")
    bundle["image_data"] = _image_data()
    fake_png = _DELIVERY_DIR / f"{stem}.png"
    fake_png.write_bytes(b"\x89PNG\r\n")
    rp._render_report_image_threaded = lambda data, out, **k: fake_png
    try:
        rp.write_report_to_delivery_folder(bundle)
    finally:
        rp._render_report_image_threaded = original
    sc = _read_sidecar(stem)
    assert sc.get("image_file") == f"{stem}.png", sc
    assert sc.get("image_url_placeholder") == rp.IMAGE_URL_PLACEHOLDER, sc
    imgs = [el for el in sc["adaptive_card"]["body"] if el.get("type") == "Image"]
    assert len(imgs) == 1 and imgs[0]["url"] == rp.IMAGE_URL_PLACEHOLDER, sc["adaptive_card"]
    print("[PASS] entrega -> card-imagem (Image + image_file) quando o PNG e gerado")

    # (b) Render falha -> fallback card-texto de adocao, sem image_file.
    stem2 = "relatorio_simplificado_imgfb_20260624_000005"
    bundle2 = _bundle(rep, f"{stem2}.xlsx", b"xlsx-bytes", "xlsx")
    bundle2["image_data"] = _image_data()
    rp._render_report_image_threaded = lambda data, out, **k: None
    try:
        rp.write_report_to_delivery_folder(bundle2)
    finally:
        rp._render_report_image_threaded = original
    sc2 = _read_sidecar(stem2)
    assert "image_file" not in sc2, sc2
    assert sc2["card"]["kind"] == "adoption", sc2
    assert rp.DOWNLOAD_URL_PLACEHOLDER in json.dumps(sc2["adaptive_card"]), "fallback deve manter o placeholder do PDF"
    print("[PASS] entrega -> fallback card-texto de adocao quando o PNG NAO e gerado")


if __name__ == "__main__":
    test_card_summary_adoption()
    test_adoption_card_shape()
    test_image_card_shape()
    test_image_html_and_chart_offline()
    test_count_unique_requesters()
    test_adoption_card_health_and_logo()
    test_minutes_to_hours()
    test_period_fallback()
    test_delivery_xlsx_writes_three_files()
    test_delivery_json_not_overwritten()
    test_delivery_pdf_reuses_report_as_attachment()
    test_delivery_image_card_and_fallback()
    print("\nTODOS OS TESTES DE CARD/ENTREGA TEAMS PASSARAM.")
