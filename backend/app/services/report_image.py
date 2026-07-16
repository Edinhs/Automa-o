"""Geracao do card-imagem semanal (PNG do CONVITE) para postar no Teams via Power Automate.

O poster e um CONVITE, nao um relatorio de status. A ordem e sempre a mesma (a mesma do
Adaptive Card de adocao em routers/reports.py):
  1) Convite (manchete) — o ambiente ja esta pronto, entre e crie seu agente + como pedir acesso.
  2) Tempo devolvido ao time (semana + acumulado) — a prova de valor.
  3) Adocao — engenheiros usando + SPECs prontas.
  4) Saude em 1 linha — itens em tratamento + previsao de correcao.
FICA DE FORA (e o "quanto a maquina trabalhou", nao o que o leitor ganha): contagem de arquivos,
tabela SPEC-por-SPEC e status cru de workspace. Detalhe fica no PDF ("Ver detalhes").

Pipeline 100% offline:
  compute_card_image_data (reports.py) -> build_report_image_html (aqui) -> render_report_image_png
  usando o Chromium offline que o projeto ja embarca (Playwright, PLAYWRIGHT_BROWSERS_PATH).

Sem JS/CDN: o grafico de linha e SVG inline calculado em Python; a marca e o wordmark textual
"STELLANTIS" desenhado localmente (nada de logo remota que possa nao carregar no PNG offline).
Se o Chromium nao estiver disponivel, render_report_image_png retorna None e o chamador cai no
card-texto (fallback).
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from app.core.report_i18n import poster_labels

# Paleta / dimensoes do poster (fiel a identidade Stellantis).
CARD_WIDTH = 1496
VIEWPORT = {"width": 1536, "height": 1120}
DEVICE_SCALE = 2

_CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #061024; font-family: 'Segoe UI', Arial, sans-serif; }
  .card {
    width: 1496px; margin: 16px auto; border-radius: 22px; overflow: hidden;
    background: linear-gradient(160deg, #0a1a3f 0%, #0c2150 55%, #0a1836 100%);
    color: #eaf1ff; padding: 34px 40px 28px;
  }
  .topbar { display: flex; justify-content: space-between; align-items: flex-start; }
  .brand { font-size: 15px; letter-spacing: 3px; color: #7fa8ff; font-weight: 700; }
  .brand-underline { width: 210px; height: 3px; background: #2f6bff; border-radius: 3px; margin: 8px 0 12px; }
  .title { font-size: 30px; font-weight: 800; color: #ffffff; letter-spacing: 1px; }
  .period { font-size: 17px; color: #7fa8ff; font-weight: 600; margin-top: 6px; }
  .wordmark { font-size: 30px; font-weight: 800; letter-spacing: 6px; color: #ffffff; text-align: right; }
  .gen-chip { margin-top: 16px; display: flex; align-items: center; gap: 12px; background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12); border-radius: 14px; padding: 12px 16px; }
  .gen-chip .ic { width: 40px; height: 40px; border-radius: 10px; background: #14336e; display: grid; place-items: center; font-size: 20px; }
  .gen-chip .txt { font-size: 13px; color: #c4d4f2; line-height: 1.35; }
  .gen-chip b { color: #fff; }

  /* 1) Convite (manchete) — painel claro para saltar aos olhos como o gancho principal. */
  .hero { margin: 24px 0 22px; background: #f4f7fc; border-radius: 20px; padding: 30px 34px; color: #0b1f45; }
  .hero-badge { display: inline-block; font-size: 12px; letter-spacing: 2px; font-weight: 800; text-transform: uppercase;
    color: #2f6bff; background: #e5edff; border-radius: 999px; padding: 6px 14px; }
  .hero h1 { font-size: 40px; line-height: 1.12; font-weight: 800; color: #0b1f45; margin: 14px 0 12px; letter-spacing: 0.3px; }
  .hero p { font-size: 18px; line-height: 1.55; color: #33436a; max-width: 1080px; }
  .hero .access { margin-top: 14px; font-size: 15px; color: #5b6b86; font-weight: 600; }
  .cta { display: flex; gap: 12px; margin-top: 22px; }
  .cta .btn { font-size: 16px; font-weight: 700; border-radius: 12px; padding: 14px 26px; }
  .cta .solid { background: #2f6bff; color: #fff; }
  .cta .ghost { background: transparent; border: 1.5px solid #2f6bff; color: #2f6bff; }

  /* 2) Tempo devolvido — a prova de valor. */
  .proof { display: grid; grid-template-columns: 1.05fr 1fr; gap: 18px; }
  .panel { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.10); border-radius: 16px; padding: 22px 24px; }
  .panel h3 { font-size: 14px; letter-spacing: 1.5px; color: #cfe0ff; font-weight: 800; text-transform: uppercase;
    display: flex; align-items: center; gap: 10px; }
  .panel h3 .ic { width: 30px; height: 30px; border-radius: 8px; background: #14336e; display: grid; place-items: center; font-size: 15px; }
  .hours-grid { display: flex; gap: 16px; margin-top: 18px; }
  .hstat { flex: 1; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 18px 20px; }
  .hstat .num { font-size: 46px; font-weight: 800; color: #ffffff; line-height: 1; }
  .hstat .lbl { font-size: 14px; color: #9fb3d8; margin-top: 8px; }
  .hstat.week .num { color: #6ee7a8; }
  .proof-note { font-size: 13.5px; color: #9fb3d8; margin-top: 16px; line-height: 1.45; }
  .chart { margin-top: 10px; background: rgba(255,255,255,0.04); border-radius: 12px; padding: 12px 10px 6px; }
  .chart .ct { font-size: 11px; letter-spacing: 1px; color: #8aa0c8; text-align: center; text-transform: uppercase; margin-bottom: 6px; }

  /* 3) Adocao — dois cartoes de numero. */
  .adopt { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }
  .astat { display: flex; align-items: center; gap: 18px; background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.10); border-radius: 16px; padding: 20px 24px; }
  .astat .ic { width: 60px; height: 60px; border-radius: 16px; background: #14336e; display: grid; place-items: center; font-size: 26px; flex: 0 0 auto; }
  .astat .num { font-size: 40px; font-weight: 800; color: #ffffff; line-height: 1; }
  .astat .lbl { font-size: 15px; color: #9fb3d8; margin-top: 6px; }

  /* 4) Saude — uma linha. */
  .health { margin-top: 18px; border-radius: 14px; padding: 16px 22px; font-size: 16px; font-weight: 600;
    display: flex; align-items: center; gap: 12px; }
  .health.ok { background: rgba(22,163,74,0.14); border: 1px solid rgba(22,163,74,0.35); color: #b7f7cf; }
  .health.warn { background: rgba(245,158,11,0.14); border: 1px solid rgba(245,158,11,0.35); color: #fde3ac; }
  .health .dot { width: 12px; height: 12px; border-radius: 50%; flex: 0 0 auto; }
  .health.ok .dot { background: #16a34a; } .health.warn .dot { background: #f59e0b; }

  .footer { display: flex; align-items: center; gap: 18px; margin-top: 24px; padding-top: 18px;
    border-top: 1px solid rgba(255,255,255,0.10); font-size: 13px; color: #9fb3d8; }
  .footer .fic { width: 42px; height: 42px; border-radius: 50%; background: #14336e; display: grid; place-items: center; font-size: 18px; flex: 0 0 auto; }
  .footer .fword { margin-left: auto; font-size: 18px; font-weight: 800; letter-spacing: 5px; color: #dbe6fb; }
</style>
"""


def _svg_line_chart(series: list[dict[str, Any]], width: int = 560, height: int = 200, pad: int = 32) -> str:
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
    # Em semanas de volume baixo (poucas horas) os rotulos inteiros colapsam (ex.: "4/4/3");
    # usa 1 casa decimal (pt-BR) quando a escala e pequena, inteiro quando ja e grande.
    axis_decimals = 1 if vmax < 20 else 0

    def _axis_label(value: float) -> str:
        return f"{value:.{axis_decimals}f}".replace(".", ",")

    grid = ""
    for frac in (0.0, 0.5, 1.0):
        v = vmin + span * frac
        yy = pad + plot_h * (1 - frac)
        grid += f'<line x1="{pad}" y1="{yy:.1f}" x2="{width - pad}" y2="{yy:.1f}" stroke="rgba(255,255,255,0.10)" stroke-width="1"/>'
        grid += f'<text x="{pad - 8}" y="{yy + 4:.1f}" font-size="11" fill="#8aa0c8" text-anchor="end">{_axis_label(v)}</text>'
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


def build_report_image_html(data: dict[str, Any]) -> str:
    """Monta o HTML do poster-convite a partir dos dados de compute_card_image_data.

    Os rotulos fixos do poster vem de `data["labels"]` (injetados por compute_card_image_data no
    idioma escolhido). Quando ausentes (ex.: dados montados a mao em testes), caem no dicionario
    PT de report_i18n -> saida em portugues identica ao comportamento historico.
    """
    hours = data.get("hours", {}) or {}
    adoption = data.get("adoption", {}) or {}
    health = data.get("health", {}) or {}
    chart = _svg_line_chart(data.get("hours_series", []))
    L = {**poster_labels("pt"), **(data.get("labels") or {})}
    lang_attr = str(L.get("lang") or "pt-br")

    health_items = int(health.get("items", 0) or 0)
    if health_items > 0:
        eta = str(health.get("eta", "")).strip()
        eta_txt = L["health_eta_prefix"].format(eta=eta) if eta else ""
        health_html = (
            f'<div class="health warn"><span class="dot"></span>'
            f'{escape(L["health_warn"].format(items=health_items, eta=eta_txt))}</div>'
        )
    else:
        health_html = (
            f'<div class="health ok"><span class="dot"></span>{escape(L["health_ok"])}</div>'
        )

    body = f"""
<div class="card">
  <div class="topbar">
    <div>
      <div class="brand">{escape(str(data.get("brand", "STELLANTIS AUTOMATION HUB")))}</div>
      <div class="brand-underline"></div>
      <div class="title">{escape(str(data.get("title", "CONVITE — AUTOMATION HUB")))}</div>
      <div class="period">{escape(str(data.get("period", "")))}</div>
    </div>
    <div>
      <div class="wordmark">STELLANTIS</div>
      <div class="gen-chip">
        <div class="ic">📅</div>
        <div class="txt">{L["gen_prefix"]}<br><b>{escape(str(data.get("generated_at", "")))}</b></div>
      </div>
    </div>
  </div>

  <div class="hero">
    <span class="hero-badge">{L["badge"]}</span>
    <h1>{escape(str(data.get("headline", "Seu ambiente já está pronto — entre e crie seu agente")))}</h1>
    <p>{escape(str(data.get("invite_body", "")))}</p>
    <div class="access">{escape(str(data.get("access_line", "")))}</div>
    <div class="cta">
      <div class="btn solid">{L["cta_playground"]}</div>
      <div class="btn ghost">{L["cta_download"]}</div>
    </div>
  </div>

  <div class="proof">
    <div class="panel">
      <h3><span class="ic">⏱️</span> {L["proof_title"]}</h3>
      <div class="hours-grid">
        <div class="hstat week"><div class="num">{escape(str(hours.get("week", "0 h")))}</div><div class="lbl">{L["this_week"]}</div></div>
        <div class="hstat"><div class="num">{escape(str(hours.get("total", "0 h")))}</div><div class="lbl">{L["total"]}</div></div>
      </div>
      <div class="proof-note">{L["proof_note"]}</div>
    </div>
    <div class="panel">
      <h3><span class="ic">📈</span> {L["chart_title"]}</h3>
      <div class="chart"><div class="ct">{L["chart_sub"]}</div>{chart}</div>
    </div>
  </div>

  <div class="adopt">
    <div class="astat">
      <div class="ic">👥</div>
      <div><div class="num">{escape(str(adoption.get("engineers", 0)))}</div><div class="lbl">{L["engineers"]}</div></div>
    </div>
    <div class="astat">
      <div class="ic">📋</div>
      <div><div class="num">{escape(str(adoption.get("specs_ready", 0)))}</div><div class="lbl">{L["specs"]}</div></div>
    </div>
  </div>

  {health_html}

  <div class="footer">
    <div class="fic">🚀</div>
    <div>{L["footer"]}</div>
    <div class="fword">STELLANTIS</div>
  </div>
</div>
"""
    return f'<!doctype html><html lang="{lang_attr}"><head><meta charset="utf-8">{_CSS}</head><body>{body}</body></html>'


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
