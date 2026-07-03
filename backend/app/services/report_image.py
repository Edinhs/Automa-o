"""Geracao do card-imagem semanal (PNG fiel ao mockup) para postar no Teams via Power Automate.

Pipeline 100% offline:
  compute_card_image_data (reports.py) -> build_report_image_html (aqui) -> render_report_image_png
  usando o Chromium offline que o projeto ja embarca (Playwright, PLAYWRIGHT_BROWSERS_PATH).

Sem JS/CDN: o grafico de linha e SVG inline calculado em Python. Se o Chromium nao estiver
disponivel, render_report_image_png retorna None e o chamador cai no card-texto (fallback).
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

# Paleta / dimensoes do poster (fiel ao mockup Stellantis).
CARD_WIDTH = 1496
VIEWPORT = {"width": 1536, "height": 1200}
DEVICE_SCALE = 2

_CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #061024; font-family: 'Segoe UI', Arial, sans-serif; }
  .card {
    width: 1496px; margin: 16px auto; border-radius: 22px; overflow: hidden;
    background: linear-gradient(160deg, #0a1a3f 0%, #0c2150 55%, #0a1836 100%);
    color: #eaf1ff; padding: 34px 40px 26px;
  }
  .topbar { display: flex; justify-content: space-between; align-items: flex-start; }
  .brand { font-size: 15px; letter-spacing: 3px; color: #7fa8ff; font-weight: 700; }
  .brand-underline { width: 210px; height: 3px; background: #2f6bff; border-radius: 3px; margin: 8px 0 14px; }
  .title { font-size: 44px; font-weight: 800; color: #ffffff; letter-spacing: 1px; }
  .period { font-size: 18px; color: #7fa8ff; font-weight: 600; margin-top: 6px; }
  .wordmark { font-size: 30px; font-weight: 800; letter-spacing: 6px; color: #ffffff; text-align: right; }
  .gen-chip { margin-top: 16px; display: flex; align-items: center; gap: 12px; background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12); border-radius: 14px; padding: 12px 16px; }
  .gen-chip .ic { width: 40px; height: 40px; border-radius: 10px; background: #14336e; display: grid; place-items: center; font-size: 20px; }
  .gen-chip .txt { font-size: 13px; color: #c4d4f2; line-height: 1.35; }
  .gen-chip b { color: #fff; }

  .welcome { display: flex; gap: 16px; align-items: flex-start; margin: 22px 0 20px; }
  .welcome .wic { width: 56px; height: 56px; border-radius: 50%; background: #14336e; display: grid; place-items: center; font-size: 26px; flex: 0 0 auto; }
  .welcome h2 { font-size: 20px; color: #fff; margin-bottom: 4px; }
  .welcome p { font-size: 15px; color: #c4d4f2; line-height: 1.5; }

  .kpis { background: #f4f7fc; border-radius: 16px; padding: 22px 24px; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
  .kpi { display: flex; align-items: center; gap: 16px; padding: 0 10px; }
  .kpi + .kpi { border-left: 1px solid #e2e9f5; }
  .kpi .ic { width: 62px; height: 62px; border-radius: 16px; display: grid; place-items: center; font-size: 26px; flex: 0 0 auto; }
  .kpi.blue .ic { background: #e5edff; } .kpi.green .ic { background: #e3f6ea; } .kpi.purple .ic { background: #ede7fb; }
  .kpi .num { font-size: 40px; font-weight: 800; color: #0b1f45; line-height: 1; }
  .kpi .lbl { font-size: 14px; color: #5b6b86; margin-top: 4px; }
  .kpi .delta { font-size: 13px; font-weight: 700; color: #16a34a; margin-top: 6px; }

  .panels { display: grid; grid-template-columns: 1.15fr 1fr 1.05fr; gap: 18px; margin-top: 20px; }
  .panel { background: rgba(255,255,255,0.035); border: 1px solid rgba(255,255,255,0.10); border-radius: 16px; padding: 20px; }
  .panel h3 { font-size: 15px; letter-spacing: 1px; color: #cfe0ff; font-weight: 700; display: flex; align-items: center; gap: 10px; text-transform: uppercase; }
  .panel h3 .ic { width: 30px; height: 30px; border-radius: 8px; background: #14336e; display: grid; place-items: center; font-size: 15px; }
  .panel .sub { font-size: 13px; color: #9fb3d8; margin: 12px 0 10px; }

  table.specs { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  table.specs th { text-align: left; color: #8aa0c8; font-weight: 600; padding: 8px 8px; border-bottom: 1px solid rgba(255,255,255,0.10); text-transform: uppercase; font-size: 11px; }
  table.specs td { padding: 10px 8px; border-bottom: 1px solid rgba(255,255,255,0.06); color: #dbe6fb; vertical-align: top; }
  table.specs td .desc { color: #9fb3d8; font-size: 11.5px; }
  table.specs td.files { text-align: center; }
  table.specs td.files span { background: #163a7a; color: #bcd2ff; border-radius: 8px; padding: 3px 10px; font-weight: 700; }
  .panel .link { margin-top: 14px; font-size: 13px; color: #6fa0ff; font-weight: 600; }

  .hl-row { display: flex; align-items: center; gap: 14px; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.06); }
  .hl-row .ic { width: 46px; height: 46px; border-radius: 12px; background: #122f61; display: grid; place-items: center; font-size: 20px; }
  .hl-row .big { font-size: 24px; font-weight: 800; color: #fff; line-height: 1; }
  .hl-row .cap { font-size: 12.5px; color: #9fb3d8; margin-top: 3px; }
  .chart { margin-top: 14px; background: rgba(255,255,255,0.04); border-radius: 12px; padding: 12px 10px 6px; }
  .chart .ct { font-size: 11px; letter-spacing: 1px; color: #8aa0c8; text-align: center; text-transform: uppercase; margin-bottom: 6px; }

  .pitch { font-size: 14px; color: #dbe6fb; line-height: 1.5; margin: 12px 0 14px; }
  .bul { display: flex; align-items: center; gap: 10px; font-size: 13.5px; color: #dbe6fb; padding: 7px 0; }
  .bul .ck { width: 24px; height: 24px; border-radius: 50%; background: #16a34a; color: #fff; display: grid; place-items: center; font-size: 13px; flex: 0 0 auto; }
  .promo { margin-top: 14px; background: rgba(47,107,255,0.12); border: 1px solid rgba(47,107,255,0.30); border-radius: 12px; padding: 14px; }
  .promo b { color: #fff; font-size: 14px; } .promo p { color: #bcd2ff; font-size: 12.5px; margin-top: 4px; }
  .btns { display: flex; gap: 10px; margin-top: 16px; }
  .btn { flex: 1; text-align: center; border-radius: 10px; padding: 11px 8px; font-size: 13px; font-weight: 700; }
  .btn.solid { background: #0f2f6b; color: #fff; } .btn.ghost { background: transparent; border: 1px solid #3b6bd6; color: #bcd2ff; }

  .footer { display: flex; align-items: center; gap: 18px; margin-top: 22px; padding-top: 18px; border-top: 1px solid rgba(255,255,255,0.10); font-size: 13px; color: #9fb3d8; }
  .footer .fic { width: 42px; height: 42px; border-radius: 50%; background: #14336e; display: grid; place-items: center; font-size: 18px; flex: 0 0 auto; }
  .footer .fword { margin-left: auto; font-size: 18px; font-weight: 800; letter-spacing: 5px; color: #dbe6fb; }
</style>
"""


def _svg_line_chart(series: list[dict[str, Any]], width: int = 540, height: int = 190, pad: int = 30) -> str:
    """Grafico de linha (SVG inline, offline) a partir da serie cumulativa diaria."""
    if not series:
        return ""
    values = [float(p.get("value", 0)) for p in series]
    vmax, vmin = max(values), min(values)
    span = (vmax - vmin) or 1.0
    n = len(series)
    plot_w, plot_h = width - pad * 2, height - pad * 2

    def x_at(i: int) -> float:
        return pad + (plot_w * i / (n - 1)) if n > 1 else pad + plot_w / 2

    def y_at(v: float) -> float:
        return pad + plot_h * (1 - (v - vmin) / span)

    pts = [(x_at(i), y_at(values[i])) for i in range(n)]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = (
        f"M {pts[0][0]:.1f},{height - pad:.1f} "
        + " ".join(f"L {x:.1f},{y:.1f}" for x, y in pts)
        + f" L {pts[-1][0]:.1f},{height - pad:.1f} Z"
    )
    circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#2f6bff"/>' for x, y in pts)
    grid = ""
    for frac in (0.0, 0.5, 1.0):
        v = vmin + span * frac
        yy = pad + plot_h * (1 - frac)
        grid += f'<line x1="{pad}" y1="{yy:.1f}" x2="{width - pad}" y2="{yy:.1f}" stroke="rgba(255,255,255,0.10)" stroke-width="1"/>'
        grid += f'<text x="{pad - 8}" y="{yy + 4:.1f}" font-size="11" fill="#8aa0c8" text-anchor="end">{int(round(v))}</text>'
    xlabels = "".join(
        f'<text x="{x_at(i):.1f}" y="{height - 8}" font-size="11" fill="#8aa0c8" text-anchor="middle">{escape(str(series[i].get("label", "")))}</text>'
        for i in range(n)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" preserveAspectRatio="xMidYMid meet">'
        f"{grid}"
        f'<path d="{area}" fill="rgba(47,107,255,0.14)"/>'
        f'<polyline points="{polyline}" fill="none" stroke="#2f6bff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
        f"{circles}{xlabels}</svg>"
    )


def _spec_rows_html(specs: list[dict[str, Any]]) -> str:
    if not specs:
        return '<tr><td colspan="4" style="color:#9fb3d8;padding:14px 8px;">Nenhuma SPEC disponível ainda.</td></tr>'
    out = []
    for s in specs:
        out.append(
            "<tr>"
            f'<td><b>{escape(str(s.get("spec", "")))}</b></td>'
            f'<td><span class="desc">{escape(str(s.get("description", "")))}</span></td>'
            f'<td>{escape(str(s.get("updated", "")))}</td>'
            f'<td class="files"><span>{escape(str(s.get("files", 0)))}</span></td>'
            "</tr>"
        )
    return "".join(out)


def build_report_image_html(data: dict[str, Any]) -> str:
    """Monta o HTML completo do poster a partir dos dados de compute_card_image_data."""
    kpis = data.get("kpis", {})
    hl = data.get("highlights", {})
    chart = _svg_line_chart(hl.get("series", []))
    spec_rows = _spec_rows_html(data.get("specs", []))

    body = f"""
<div class="card">
  <div class="topbar">
    <div>
      <div class="brand">{escape(str(data.get("brand", "STELLANTIS AUTOMATION HUB")))}</div>
      <div class="brand-underline"></div>
      <div class="title">{escape(str(data.get("title", "RELATÓRIO SEMANAL")))}</div>
      <div class="period">{escape(str(data.get("period", "")))}</div>
    </div>
    <div>
      <div class="wordmark">STELLANTIS</div>
      <div class="gen-chip">
        <div class="ic">📅</div>
        <div class="txt">Relatório gerado em<br><b>{escape(str(data.get("generated_at", "")))}</b></div>
      </div>
    </div>
  </div>

  <div class="welcome">
    <div class="wic">👋</div>
    <div>
      <h2>Olá, time Stellantis!</h2>
      <p>Seja bem-vindo ao relatório semanal do Automation HUB.<br>
      Aqui você acompanha os principais resultados das automações e o impacto gerado no Stellantis GenAI Playground.</p>
    </div>
  </div>

  <div class="kpis">
    <div class="kpi blue">
      <div class="ic">📄</div>
      <div><div class="num">{escape(str(kpis.get("files_total", 0)))}</div>
        <div class="lbl">Arquivos Processados</div>
        <div class="delta">+{escape(str(kpis.get("files_week_delta", 0)))} na última semana</div></div>
    </div>
    <div class="kpi green">
      <div class="ic">🕐</div>
      <div><div class="num">{escape(str(kpis.get("hours_total", "0 h")))}</div>
        <div class="lbl">Horas Economizadas com automações</div>
        <div class="delta">{escape(str(kpis.get("hours_week_delta", "+0h")))} na última semana</div></div>
    </div>
    <div class="kpi purple">
      <div class="ic">📁</div>
      <div><div class="num">{escape(str(kpis.get("workspaces", 0)))}</div>
        <div class="lbl">Workspaces Disponíveis</div></div>
    </div>
  </div>

  <div class="panels">
    <div class="panel">
      <h3><span class="ic">📋</span> SPECs Disponíveis</h3>
      <div class="sub">Confira abaixo as SPECs disponíveis para uso no Playground.</div>
      <table class="specs">
        <thead><tr><th>SPEC</th><th>Descrição</th><th>Última atualização</th><th style="text-align:center">Arquivos</th></tr></thead>
        <tbody>{spec_rows}</tbody>
      </table>
      <div class="link">Ver todos os workspaces disponíveis →</div>
    </div>

    <div class="panel">
      <h3><span class="ic">⭐</span> Highlights da Semana</h3>
      <div class="hl-row"><div class="ic">📄</div><div><div class="big">{escape(str(hl.get("files_week", 0)))}</div><div class="cap">Arquivos atualizados nesta semana</div></div></div>
      <div class="hl-row"><div class="ic">🕐</div><div><div class="big">{escape(str(hl.get("hours_total", "0 h")))}</div><div class="cap">Horas economizadas com automações</div></div></div>
      <div class="hl-row" style="border-bottom:none"><div class="ic">📊</div><div><div class="big" style="font-size:18px">Crescimento contínuo</div><div class="cap">Mais eficiência, menos retrabalho.</div></div></div>
      <div class="chart"><div class="ct">Evolução de arquivos processados</div>{chart}</div>
    </div>

    <div class="panel">
      <h3><span class="ic">🤖</span> Stellantis GenAI Playground</h3>
      <div class="pitch">O Stellantis GenAI Playground é nossa plataforma corporativa para colaboração, inovação e produtividade com Inteligência Artificial.</div>
      <div class="bul"><span class="ck">✓</span> Centralize conhecimento e documentos</div>
      <div class="bul"><span class="ck">✓</span> Acelere análises e tomada de decisão</div>
      <div class="bul"><span class="ck">✓</span> Automatize tarefas e reduza retrabalho</div>
      <div class="bul"><span class="ck">✓</span> Promova inovação com segurança e governança</div>
      <div class="promo"><b>🚀 Impulsionando o futuro com Inteligência Artificial.</b><p>Mais produtividade. Mais inovação. Mais Stellantis.</p></div>
      <div class="btns"><div class="btn solid">🌐 Abrir Playground</div><div class="btn ghost">📄 Baixar Relatório (PDF)</div></div>
    </div>
  </div>

  <div class="footer">
    <div class="fic">📁</div>
    <div>Este relatório é gerado automaticamente pelo Stellantis Automation HUB e reflete o desempenho<br>das automações e o impacto positivo no seu dia a dia.</div>
    <div style="display:flex;align-items:center;gap:10px;margin-left:24px"><div class="fic">🏆</div><div>Obrigado por fazer parte desta<br>jornada de transformação e inovação!</div></div>
    <div class="fword">STELLANTIS</div>
  </div>
</div>
"""
    return f'<!doctype html><html lang="pt-br"><head><meta charset="utf-8">{_CSS}</head><body>{body}</body></html>'


def render_report_image_png(html: str, out_path: str | Path, *, timeout_ms: int = 20000) -> Path | None:
    """Renderiza o HTML para PNG com o Chromium offline (Playwright sync API).

    Retorna o Path do PNG ou None em qualquer falha (Playwright/Chromium ausente, timeout).
    ATENCAO: a Sync API nao roda dentro de um event loop asyncio -> chame via run_in_threadpool
    nos caminhos async (ver reports.write_report_to_delivery_folder).
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--force-color-profile=srgb"])
            try:
                page = browser.new_page(viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE)
                page.set_default_timeout(timeout_ms)
                page.set_content(html, wait_until="load")
                page.wait_for_timeout(200)  # deixa layout/emoji assentarem
                element = page.query_selector(".card")
                if element is not None:
                    element.screenshot(path=str(out_path))
                else:
                    page.screenshot(path=str(out_path), full_page=True)
            finally:
                browser.close()
    except Exception:
        return None
    return out_path if out_path.exists() else None


def generate_report_image(data: dict[str, Any], out_path: str | Path) -> Path | None:
    """Conveniencia: dados -> HTML -> PNG. Retorna Path ou None (fallback do chamador)."""
    return render_report_image_png(build_report_image_html(data), out_path)
