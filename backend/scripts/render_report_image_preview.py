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
        "title": "RELATÓRIO SEMANAL",
        "period": "19/06/2026 a 25/06/2026",
        "generated_at": "25/06/2026 11:01",
        "logo_url": "",
        "kpis": {
            "files_total": 490,
            "files_week_delta": 135,
            "hours_total": "42,5 h",
            "hours_week_delta": "+11,3h",
            "workspaces": 8,
        },
        "specs": [
            {"spec": "SPEC_341_Workinprogress", "description": "Workspace para gestão de especificações 341.", "updated": "25/06/2026 09:45", "files": 120},
            {"spec": "SPEC_281_Workinprogress", "description": "Workspace para gestão de especificações 281.", "updated": "25/06/2026 08:37", "files": 95},
            {"spec": "SPEC_326CL_Workinprogress", "description": "Workspace para gestão de especificações 326CL.", "updated": "24/06/2026 17:12", "files": 90},
            {"spec": "SPEC_363_Workinprogress", "description": "Workspace para gestão de especificações 363.", "updated": "24/06/2026 14:22", "files": 75},
            {"spec": "SPEC_226_Workinprogress", "description": "Workspace para gestão de especificações 226.", "updated": "23/06/2026 16:08", "files": 60},
        ],
        "highlights": {
            "files_week": 135,
            "hours_total": "42,5 h",
            "series": [{"label": f"{d:02d}/06", "value": v} for d, v in zip(range(19, 26), [190, 235, 285, 320, 375, 430, 490])],
        },
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
