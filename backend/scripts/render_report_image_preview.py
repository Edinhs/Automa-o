r"""
render_report_image_preview.py -- Harness de conferencia VISUAL do card-imagem semanal.

Monta dados de exemplo (os numeros do mockup), gera o HTML do poster e renderiza o PNG com o
Chromium offline (mesmo do RPA). Nao usa DB nem backend rodando -- so valida o visual.

Uso (a partir de backend/):
  .venv\Scripts\python.exe scripts\render_report_image_preview.py [caminho_de_saida.png]

Se o Chromium/Playwright nao estiver disponivel, gera so o HTML (para abrir no navegador) e avisa.
"""
from __future__ import annotations

import sys
import tempfile
import webbrowser
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.services.report_image import build_report_image_html, render_report_image_png  # noqa: E402


def sample_data() -> dict:
    return {
        "brand": "STELLANTIS AUTOMATION HUB",
        "title": "CONVITE — AUTOMATION HUB",
        "period": "19/06/2026 a 25/06/2026",
        "generated_at": "25/06/2026 11:01",
        "headline": "🚀 Seu ambiente já está pronto — entre e crie seu agente",
        "invite_body": (
            "Esqueça baixar a SPEC, subir no workspace seguro e montar o ambiente: a automação já fez "
            "tudo isso. Entre no Playground e vá direto ao que importa — criar o agente no workspace do "
            "seu projeto."
        ),
        "access_line": '→ Não tem acesso ao workspace? Toque em "Solicitar acesso" abaixo e preencha o formulário.',
        "playground_url": "https://genai.stellantis.com/",
        "hours": {"week": "11,3 h", "total": "42,5 h"},
        "hours_series": [{"label": f"{d:02d}/06", "value": v} for d, v in zip(range(19, 26), [16.5, 20.4, 24.7, 27.8, 32.5, 37.3, 42.5])],
        "adoption": {"engineers": 7, "specs_ready": 23},
        "health": {"items": 2, "eta": "em até 1 dia útil"},
    }


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "report_card_preview.png"
    html = build_report_image_html(sample_data())

    html_path = out_path.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    print(f"HTML gravado em: {html_path}")

    png = render_report_image_png(html, out_path)
    if png is None:
        print("[AVISO] Nao foi possivel renderizar o PNG (Playwright/Chromium offline ausente?).")
        print("        Abra o HTML acima no navegador para conferir o visual.")
        try:
            webbrowser.open(html_path.as_uri())
        except Exception:
            pass
        return 1

    print(f"[OK] PNG gerado: {png}  ({png.stat().st_size} bytes)")
    try:
        webbrowser.open(png.as_uri())
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
