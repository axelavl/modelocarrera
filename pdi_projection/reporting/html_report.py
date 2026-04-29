from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

import altair as alt
import pandas as pd

from pdi_projection.domain import SECUENCIA_OPPL, Grado

GRADO_NOMBRE = {int(g): g.name for g in Grado}
ORDEN_JERARQUICO = [g.name for g in reversed(SECUENCIA_OPPL)]


_HTML_HEAD = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Informe OPPL/PDI</title>
<script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; margin: 32px; color: #1c1c1c; max-width: 1100px; }
  h1 { font-size: 26px; margin: 0 0 4px; }
  h2 { font-size: 18px; margin: 32px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #e0e0e0; }
  .meta { color: #666; font-size: 13px; margin-bottom: 24px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 16px 0 24px; }
  .kpi { background: #f5f6f8; border-radius: 6px; padding: 12px 16px; }
  .kpi .label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }
  .kpi .value { font-size: 22px; font-weight: 600; margin-top: 4px; }
  .kpi .delta { font-size: 12px; color: #2b7d3a; margin-top: 2px; }
  .kpi .delta.neg { color: #b22222; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0 16px; }
  th, td { border-bottom: 1px solid #eee; padding: 6px 10px; text-align: left; }
  th { background: #fafafa; font-weight: 600; }
  .footer { margin-top: 32px; color: #999; font-size: 11px; }
  @media print {
    body { margin: 16mm; max-width: none; }
    .chart { page-break-inside: avoid; }
  }
</style>
</head>
<body>
"""

_HTML_TAIL = """
<div class="footer">Generado por pdi_projection — informe auto-contenido (imprimir desde el navegador → PDF)</div>
</body>
</html>
"""


def _kpi_card(label: str, value: str, delta: str | None = None, delta_neg: bool = False) -> str:
    delta_html = f'<div class="delta{" neg" if delta_neg else ""}">{html.escape(delta)}</div>' if delta else ""
    return (
        f'<div class="kpi"><div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div>{delta_html}</div>'
    )


def _vega_div(div_id: str, chart: alt.Chart) -> str:
    spec = json.dumps(chart.to_dict())
    return (
        f'<div class="chart"><div id="{div_id}"></div>'
        f"<script>vegaEmbed('#{div_id}', {spec}, {{actions: false}});</script></div>"
    )


def _table_html(df: pd.DataFrame, max_rows: int = 50) -> str:
    if df.empty:
        return "<p><em>Sin datos.</em></p>"
    return df.head(max_rows).to_html(index=False, escape=True, border=0)


def _build_kpis(snapshots: dict, eventos_df: pd.DataFrame, planta: dict | None) -> str:
    años = sorted(snapshots.keys())
    if not años:
        return ""
    año_ini, año_fin = años[0], años[-1]
    dot_ini = sum(snapshots[año_ini].values())
    dot_fin = sum(snapshots[año_fin].values())
    planta_total = sum(p.vacantes_ley for p in planta.values()) if planta else 0
    cobertura_fin = (dot_fin / planta_total * 100) if planta_total else 0
    n_asc = int((eventos_df["tipo"] == "ascenso").sum()) if not eventos_df.empty else 0
    n_ret = int((eventos_df["tipo"] == "retiro").sum()) if not eventos_df.empty else 0
    n_post = int((eventos_df["tipo"] == "postergacion_vacante").sum()) if not eventos_df.empty else 0
    delta = dot_fin - dot_ini
    cards = [
        _kpi_card("Dotación inicial", f"{dot_ini:,}"),
        _kpi_card("Dotación final", f"{dot_fin:,}", f"{delta:+,}", delta_neg=delta < 0),
        _kpi_card("Cobertura planta (final)", f"{cobertura_fin:.1f}%"),
        _kpi_card(f"Ascensos {año_ini}–{año_fin}", f"{n_asc:,}"),
        _kpi_card(f"Retiros {año_ini}–{año_fin}", f"{n_ret:,}"),
        _kpi_card("Postergados (acum.)", f"{n_post:,}"),
    ]
    return f'<div class="kpi-grid">{"".join(cards)}</div>'


def _chart_evolucion(snapshots: dict) -> alt.Chart:
    rows = []
    for año, snap in sorted(snapshots.items()):
        for g, dot in snap.items():
            rows.append({"año": año, "grado": GRADO_NOMBRE[int(g)], "dotacion": dot})
    df = pd.DataFrame(rows)
    return (
        alt.Chart(df)
        .mark_area()
        .encode(
            x=alt.X("año:O", title="Año"),
            y=alt.Y("dotacion:Q", title="Dotación", stack="zero"),
            color=alt.Color("grado:N", sort=ORDEN_JERARQUICO, title="Grado"),
            tooltip=["año", "grado", "dotacion"],
        )
        .properties(width=820, height=320, title="Evolución de la dotación por grado")
    )


def _chart_piramide(snapshot: dict, planta: dict | None, año: int) -> alt.Chart:
    rows = []
    for g, dot in snapshot.items():
        plan = planta.get(g).vacantes_ley if planta and g in planta else 0
        rows.append({"grado": GRADO_NOMBRE[int(g)], "dotacion": dot, "planta": plan})
    df = pd.DataFrame(rows)
    base = alt.Chart(df).encode(y=alt.Y("grado:N", sort=ORDEN_JERARQUICO, title=None))
    barras_planta = base.mark_bar(color="#cfd8dc", size=22).encode(
        x=alt.X("planta:Q", title="Funcionarios"),
        tooltip=["grado", "planta"],
    )
    barras_dot = base.mark_bar(color="#1f77b4", size=14).encode(x="dotacion:Q", tooltip=["grado", "dotacion"])
    return (barras_planta + barras_dot).properties(width=820, height=300, title=f"Pirámide jerárquica — Año {año}")


def _chart_ascensos_via(eventos_df: pd.DataFrame) -> alt.Chart | None:
    asc = eventos_df[eventos_df["tipo"] == "ascenso"] if not eventos_df.empty else eventos_df
    if asc.empty:
        return None
    agg = asc.groupby(["año", "via"]).size().reset_index(name="n")
    return (
        alt.Chart(agg)
        .mark_bar()
        .encode(
            x=alt.X("año:O", title="Año"),
            y=alt.Y("n:Q", title="Ascensos"),
            color=alt.Color("via:N", title="Vía"),
            tooltip=["año", "via", "n"],
        )
        .properties(width=820, height=240, title="Ascensos por año y vía")
    )


def _chart_retiros_causal(eventos_df: pd.DataFrame) -> alt.Chart | None:
    ret = eventos_df[eventos_df["tipo"] == "retiro"] if not eventos_df.empty else eventos_df
    if ret.empty:
        return None
    agg = ret.groupby(["año", "causal"]).size().reset_index(name="n")
    return (
        alt.Chart(agg)
        .mark_bar()
        .encode(
            x=alt.X("año:O", title="Año"),
            y=alt.Y("n:Q", title="Retiros"),
            color=alt.Color("causal:N", title="Causal"),
            tooltip=["año", "causal", "n"],
        )
        .properties(width=820, height=240, title="Retiros por año y causal")
    )


def generar_informe_html(
    snapshots: dict,
    eventos_df: pd.DataFrame,
    planta: dict | None,
    validation_issues: list,
    config_resumen: dict[str, Any] | None = None,
    año_piramide: int | None = None,
) -> str:
    """Genera un informe HTML auto-contenido (imprimible a PDF desde el navegador)."""
    años = sorted(snapshots.keys())
    if año_piramide is None and años:
        año_piramide = años[-1]

    parts = [_HTML_HEAD]
    parts.append('<h1>Informe de proyección OPPL/PDI</h1>')
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    horizonte = f"{años[0]}–{años[-1]}" if años else "(sin años)"
    parts.append(f'<div class="meta">Generado {fecha} · Horizonte simulado: {horizonte}</div>')

    parts.append("<h2>Indicadores clave</h2>")
    parts.append(_build_kpis(snapshots, eventos_df, planta))

    if años:
        parts.append("<h2>Evolución de la dotación</h2>")
        parts.append(_vega_div("chart-evol", _chart_evolucion(snapshots)))

        parts.append(f"<h2>Pirámide jerárquica — año {año_piramide}</h2>")
        parts.append(_vega_div("chart-pir", _chart_piramide(snapshots[año_piramide], planta, año_piramide)))

    chart_via = _chart_ascensos_via(eventos_df)
    if chart_via is not None:
        parts.append("<h2>Ascensos por vía</h2>")
        parts.append(_vega_div("chart-via", chart_via))

    chart_ret = _chart_retiros_causal(eventos_df)
    if chart_ret is not None:
        parts.append("<h2>Retiros por causal</h2>")
        parts.append(_vega_div("chart-ret", chart_ret))

    if validation_issues:
        parts.append("<h2>Observaciones de validación</h2>")
        df_val = pd.DataFrame([vars(i) for i in validation_issues])
        parts.append(_table_html(df_val))
    else:
        parts.append("<h2>Observaciones de validación</h2><p><em>Sin observaciones.</em></p>")

    if config_resumen:
        parts.append("<h2>Configuración usada</h2>")
        df_cfg = pd.DataFrame(
            [{"parámetro": k, "valor": json.dumps(v, ensure_ascii=False, default=str)} for k, v in config_resumen.items()]
        )
        parts.append(_table_html(df_cfg, max_rows=200))

    parts.append(_HTML_TAIL)
    return "".join(parts)


def generar_informe_comparativo_html(resultados: list, año_piramide: int | None = None) -> str:
    """Informe HTML que compara N escenarios. ``resultados`` debe ser una lista
    de objetos con atributos ``nombre``, ``logs`` y ``estado_final.planta`` (los
    objetos producidos por ``correr_escenarios`` o equivalentes)."""
    parts = [_HTML_HEAD]
    parts.append('<h1>Informe comparativo OPPL/PDI</h1>')
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    nombres = " · ".join(r.nombre for r in resultados)
    parts.append(f'<div class="meta">Generado {fecha} · Escenarios: {html.escape(nombres)}</div>')

    rows_kpi = []
    for r in resultados:
        años = sorted(r.logs.snapshots.keys())
        if not años:
            continue
        dot_ini = sum(r.logs.snapshots[años[0]].values())
        dot_fin = sum(r.logs.snapshots[años[-1]].values())
        n_asc = sum(1 for evs in r.logs.eventos_por_año.values() for e in evs if e.tipo.value == "ascenso")
        n_ret = sum(1 for evs in r.logs.eventos_por_año.values() for e in evs if e.tipo.value == "retiro")
        n_post = sum(1 for evs in r.logs.eventos_por_año.values() for e in evs if e.tipo.value == "postergacion_vacante")
        rows_kpi.append({
            "escenario": r.nombre,
            "dotación_inicial": dot_ini,
            "dotación_final": dot_fin,
            "delta": dot_fin - dot_ini,
            "ascensos": n_asc,
            "retiros": n_ret,
            "postergados": n_post,
        })
    parts.append("<h2>KPIs comparativos</h2>")
    parts.append(_table_html(pd.DataFrame(rows_kpi), max_rows=10))

    rows_total = []
    for r in resultados:
        for año, snap in sorted(r.logs.snapshots.items()):
            rows_total.append({"escenario": r.nombre, "año": año, "total": sum(snap.values())})
    if rows_total:
        df = pd.DataFrame(rows_total)
        chart = (
            alt.Chart(df)
            .mark_line(point=True)
            .encode(
                x=alt.X("año:O", title="Año"),
                y=alt.Y("total:Q", title="Dotación total"),
                color=alt.Color("escenario:N", title="Escenario"),
                tooltip=["escenario", "año", "total"],
            )
            .properties(width=820, height=320, title="Evolución comparada de la dotación total")
        )
        parts.append("<h2>Dotación total por escenario</h2>")
        parts.append(_vega_div("chart-cmp-tot", chart))

    rows_grado = []
    for r in resultados:
        for año, snap in sorted(r.logs.snapshots.items()):
            for g, dot in snap.items():
                rows_grado.append({"escenario": r.nombre, "año": año, "grado": GRADO_NOMBRE[int(g)], "dotacion": dot})
    if rows_grado:
        df_g = pd.DataFrame(rows_grado)
        chart_g = (
            alt.Chart(df_g)
            .mark_line(point=True)
            .encode(
                x=alt.X("año:O", title="Año"),
                y=alt.Y("dotacion:Q", title="Dotación"),
                color=alt.Color("escenario:N", title="Escenario"),
                row=alt.Row("grado:N", sort=ORDEN_JERARQUICO, title="Grado"),
                tooltip=["escenario", "año", "grado", "dotacion"],
            )
            .properties(width=820, height=120)
        )
        parts.append("<h2>Evolución por grado</h2>")
        parts.append(_vega_div("chart-cmp-grado", chart_g))

    parts.append(_HTML_TAIL)
    return "".join(parts)
