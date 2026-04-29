from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from pdi_projection.config import AppConfig
from pdi_projection.data_loader import cargar_tabular
from pdi_projection.domain import Grado, SECUENCIA_OPPL, construir_estado_inicial
from pdi_projection.outputs import exportar_resultados
from pdi_projection.simulator import simular


REQUIRED_FILES = ["funcionarios.csv", "planta_vacantes.csv", "ingresos.csv"]
OPTIONAL_FILES = [
    "calificaciones.csv",
    "cursos.csv",
    "impedimentos.csv",
    "transitorias.csv",
    "ascensos_hist.csv",
]

GRADO_NOMBRE = {int(g): g.name for g in Grado}
ORDEN_JERARQUICO = [g.name for g in reversed(SECUENCIA_OPPL)]  # PFT arriba, DTV abajo


def _save_uploaded_files(uploaded: list, tmpdir: Path) -> None:
    for f in uploaded:
        (tmpdir / f.name).write_bytes(f.getbuffer())


def _build_config() -> AppConfig:
    st.sidebar.header("Parámetros")
    cfg = AppConfig()

    with st.sidebar.expander("Reglas configurables", expanded=True):
        cfg.policy.mandatory_career_years = st.number_input(
            "Retiro obligatorio (años de carrera)", min_value=20, max_value=40, value=30
        )
        cfg.policy.health_blocks_promotion = st.checkbox("Salud bloquea ascenso", value=True)
        cfg.policy.accumulate_unfilled_vacancies = st.checkbox("Acumular vacantes no provistas", value=True)
        ttl = st.number_input("TTL vacantes no provistas (años, 0 = sin TTL)", min_value=0, max_value=20, value=0)
        cfg.policy.unfilled_vacancy_ttl_years = ttl if ttl > 0 else None
        cfg.policy.enforce_batch_cutoff_on_missing_lane_candidate = st.checkbox(
            "Aplicar corte de tanda (R12)", value=True
        )
        cfg.policy.allow_lane_fallback = st.checkbox("Permitir fallback entre vías", value=False)
        cfg.policy.enable_sobredotacion_absorption = st.checkbox(
            "Permitir sobredotación con absorción", value=True
        )
        cfg.policy.treat_missing_calificacion_as_lista2 = st.checkbox(
            "Sin calificación → lista 2", value=True
        )

    with st.sidebar.expander("Fórmula de mérito"):
        cfg.merit.config["ventana_años"] = st.slider("Ventana años", 1, 5, 3)
        p1 = st.number_input("Puntaje lista 1", value=100)
        p2 = st.number_input("Puntaje lista 2", value=70)
        p3 = st.number_input("Puntaje lista 3", value=0)
        cfg.merit.config["mapeo_lista_puntaje"] = {1: p1, 2: p2, 3: p3, 4: None}
        cfg.merit.config["ponderadores_temporales"] = [0.5, 0.3, 0.2]

    return cfg


def _kpis(snapshots: dict, all_events: pd.DataFrame, planta: dict) -> None:
    años = sorted(snapshots.keys())
    año_ini, año_fin = años[0], años[-1]
    dot_ini = sum(snapshots[año_ini].values())
    dot_fin = sum(snapshots[año_fin].values())

    planta_total = sum(p.vacantes_ley for p in planta.values()) if planta else 0
    cobertura_fin = (dot_fin / planta_total * 100) if planta_total else 0

    n_ascensos = int((all_events["tipo"] == "ascenso").sum())
    n_retiros = int((all_events["tipo"] == "retiro").sum())
    n_postergados = int((all_events["tipo"] == "postergacion_vacante").sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Dotación inicial", f"{dot_ini:,}")
    c2.metric("Dotación final", f"{dot_fin:,}", delta=f"{dot_fin - dot_ini:+,}")
    c3.metric("Cobertura planta (final)", f"{cobertura_fin:.1f}%")
    c4.metric(f"Ascensos {año_ini}–{año_fin}", f"{n_ascensos:,}")
    c5.metric(f"Retiros {año_ini}–{año_fin}", f"{n_retiros:,}",
              delta=f"-{n_postergados} post." if n_postergados else None,
              delta_color="off")


def _eventos_df(logs) -> pd.DataFrame:
    rows = []
    for año, evs in logs.eventos_por_año.items():
        for e in evs:
            rows.append({
                "año": año,
                "funcionario_id": e.funcionario_id,
                "tipo": e.tipo.value,
                "grado_origen": GRADO_NOMBRE.get(int(e.grado_origen)) if e.grado_origen else "",
                "grado_destino": GRADO_NOMBRE.get(int(e.grado_destino)) if e.grado_destino else "",
                "via": e.via.value if e.via else "",
                "causal": e.causal.value if e.causal else "",
                "motivo": e.motivo or "",
            })
    if not rows:
        return pd.DataFrame(columns=["año", "funcionario_id", "tipo", "grado_origen", "grado_destino", "via", "causal", "motivo"])
    return pd.DataFrame(rows)


def _tab_resumen(snapshots: dict, eventos: pd.DataFrame, planta: dict) -> None:
    _kpis(snapshots, eventos, planta)
    st.divider()

    rows = []
    for año, snap in sorted(snapshots.items()):
        for g, dot in snap.items():
            rows.append({"año": año, "grado": GRADO_NOMBRE[int(g)], "dotacion": dot})
    df = pd.DataFrame(rows)

    st.markdown("**Evolución de la dotación por grado**")
    chart = (
        alt.Chart(df)
        .mark_area()
        .encode(
            x=alt.X("año:O", title="Año"),
            y=alt.Y("dotacion:Q", title="Dotación", stack="zero"),
            color=alt.Color("grado:N", sort=ORDEN_JERARQUICO, title="Grado"),
            tooltip=["año", "grado", "dotacion"],
        )
        .properties(height=380)
    )
    st.altair_chart(chart, use_container_width=True)

    st.markdown("**Total activos por año**")
    totales = df.groupby("año", as_index=False)["dotacion"].sum()
    st.line_chart(totales.set_index("año"))


def _tab_piramide(snapshots: dict, planta: dict) -> None:
    años = sorted(snapshots.keys())
    año = st.select_slider("Año", options=años, value=años[-1])

    rows = []
    for g, dot in snapshots[año].items():
        nombre = GRADO_NOMBRE[int(g)]
        plan = planta.get(g).vacantes_ley if planta and g in planta else 0
        rows.append({"grado": nombre, "dotacion": dot, "planta": plan, "brecha": plan - dot})
    df = pd.DataFrame(rows)
    df["grado"] = pd.Categorical(df["grado"], categories=ORDEN_JERARQUICO, ordered=True)
    df = df.sort_values("grado")

    base = alt.Chart(df).encode(y=alt.Y("grado:N", sort=ORDEN_JERARQUICO, title=None))
    barras_planta = base.mark_bar(color="#cfd8dc", size=22).encode(
        x=alt.X("planta:Q", title="Funcionarios"),
        tooltip=["grado", "planta"],
    )
    barras_dot = base.mark_bar(color="#1f77b4", size=14).encode(
        x="dotacion:Q",
        tooltip=["grado", "dotacion"],
    )
    st.markdown(f"**Pirámide jerárquica — Año {año}** (gris = planta de ley · azul = dotación efectiva)")
    st.altair_chart((barras_planta + barras_dot).properties(height=320), use_container_width=True)

    df_view = df.copy()
    df_view["cobertura_%"] = df_view.apply(
        lambda r: round(100 * r["dotacion"] / r["planta"], 1) if r["planta"] else None, axis=1
    )
    st.dataframe(df_view[["grado", "dotacion", "planta", "brecha", "cobertura_%"]], use_container_width=True, hide_index=True)


def _tab_flujo(eventos: pd.DataFrame) -> None:
    if eventos.empty:
        st.info("Sin eventos en el horizonte simulado.")
        return

    asc = eventos[eventos["tipo"] == "ascenso"]
    if not asc.empty:
        st.markdown("**Ascensos por año y vía**")
        agg = asc.groupby(["año", "via"]).size().reset_index(name="n")
        chart = alt.Chart(agg).mark_bar().encode(
            x=alt.X("año:O", title="Año"),
            y=alt.Y("n:Q", title="Ascensos"),
            color=alt.Color("via:N", title="Vía"),
            tooltip=["año", "via", "n"],
        ).properties(height=260)
        st.altair_chart(chart, use_container_width=True)

        st.markdown("**Ascensos por grado destino**")
        agg2 = asc.groupby(["año", "grado_destino"]).size().reset_index(name="n")
        chart2 = alt.Chart(agg2).mark_bar().encode(
            x=alt.X("año:O", title="Año"),
            y=alt.Y("n:Q", title="Ascensos"),
            color=alt.Color("grado_destino:N", sort=ORDEN_JERARQUICO, title="Grado destino"),
            tooltip=["año", "grado_destino", "n"],
        ).properties(height=260)
        st.altair_chart(chart2, use_container_width=True)

    ret = eventos[eventos["tipo"] == "retiro"]
    if not ret.empty:
        st.markdown("**Retiros por año y causal**")
        agg = ret.groupby(["año", "causal"]).size().reset_index(name="n")
        chart = alt.Chart(agg).mark_bar().encode(
            x=alt.X("año:O", title="Año"),
            y=alt.Y("n:Q", title="Retiros"),
            color=alt.Color("causal:N", title="Causal"),
            tooltip=["año", "causal", "n"],
        ).properties(height=260)
        st.altair_chart(chart, use_container_width=True)

    post = eventos[eventos["tipo"] == "postergacion_vacante"]
    if not post.empty:
        st.markdown("**Postergaciones por año y grado destino**")
        agg = post.groupby(["año", "grado_destino"]).size().reset_index(name="n")
        chart = alt.Chart(agg).mark_bar().encode(
            x=alt.X("año:O", title="Año"),
            y=alt.Y("n:Q", title="Postergaciones"),
            color=alt.Color("grado_destino:N", sort=ORDEN_JERARQUICO, title="Grado destino"),
            tooltip=["año", "grado_destino", "n"],
        ).properties(height=260)
        st.altair_chart(chart, use_container_width=True)


def _tab_trazabilidad(eventos: pd.DataFrame, evaluados_df: pd.DataFrame) -> None:
    ids = sorted(eventos["funcionario_id"].unique()) if not eventos.empty else []
    if not ids:
        st.info("Sin funcionarios con eventos.")
        return
    fid = st.selectbox("Funcionario", ids)
    st.markdown("**Línea de eventos**")
    st.dataframe(
        eventos[eventos["funcionario_id"] == fid].sort_values("año"),
        use_container_width=True,
        hide_index=True,
    )
    if not evaluados_df.empty:
        st.markdown("**Evaluaciones de elegibilidad**")
        st.dataframe(
            evaluados_df[evaluados_df["funcionario_id"] == fid].sort_values(["año", "grado_destino"]),
            use_container_width=True,
            hide_index=True,
        )


def _tab_validacion(issues: list) -> None:
    if not issues:
        st.success("Sin observaciones de validación")
        return
    df = pd.DataFrame([vars(i) for i in issues])
    sev_counts = df["severity"].value_counts()
    cols = st.columns(len(sev_counts))
    for col, (sev, n) in zip(cols, sev_counts.items()):
        col.metric(sev.capitalize(), int(n))
    st.dataframe(df, use_container_width=True, hide_index=True)


def _tab_descargas(outdir: Path) -> None:
    csvs = sorted(outdir.glob("*.csv"))
    manifest = outdir / "manifest.json"

    st.markdown("**Archivos generados**")
    rows = [{"archivo": p.name, "tamaño_bytes": p.stat().st_size} for p in csvs]
    if manifest.exists():
        rows.append({"archivo": manifest.name, "tamaño_bytes": manifest.stat().st_size})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in csvs:
            zf.write(p, arcname=p.name)
        if manifest.exists():
            zf.write(manifest, arcname=manifest.name)
    buffer.seek(0)
    st.download_button(
        label="Descargar todo (ZIP)",
        data=buffer,
        file_name="outputs_oppl_pdi.zip",
        mime="application/zip",
    )

    if manifest.exists():
        with st.expander("Ver manifest.json (config usada)"):
            st.code(manifest.read_text(encoding="utf-8"), language="json")


def main() -> None:
    st.set_page_config(page_title="OPPL/PDI Proyección", layout="wide")
    st.title("Sistema de Proyección OPPL/PDI")
    st.caption("Simulador anual con trazabilidad de cada decisión.")

    cfg = _build_config()

    with st.sidebar.expander("Horizonte", expanded=True):
        año_base = st.number_input("Año base", min_value=2000, max_value=2100, value=2026)
        horizonte = st.number_input("Horizonte (años)", min_value=0, max_value=50, value=5)

    st.subheader("1) Cargar archivos de entrada")
    uploaded = st.file_uploader(
        "CSV de entrada (drag & drop)",
        type=["csv"],
        accept_multiple_files=True,
    )

    if uploaded:
        nombres = sorted([f.name for f in uploaded])
        faltantes = [f for f in REQUIRED_FILES if f not in nombres]
        c1, c2 = st.columns([3, 1])
        c1.write(f"Archivos cargados: {', '.join(nombres)}")
        if faltantes:
            c2.error(f"Faltan: {faltantes}")
        else:
            c2.success("Requeridos OK")

    run = st.button("Ejecutar simulación", type="primary", disabled=not uploaded)
    if not run:
        st.info("Cargue los CSV y presione **Ejecutar simulación** para ver el dashboard.")
        return

    nombres = sorted([f.name for f in uploaded])
    if any(f not in nombres for f in REQUIRED_FILES):
        st.stop()

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        _save_uploaded_files(uploaded, tmpdir)
        data = cargar_tabular(str(tmpdir), cfg)
        estado = construir_estado_inicial(
            data.funcionarios,
            año_base=año_base,
            planta=data.planta,
            transitorias=data.transitorias,
        )
        logs = simular(estado, año_base=año_base, horizonte=horizonte,
                       ingresos_por_año=data.ingresos_por_año, config=cfg)

        outdir = tmpdir / "outputs"
        exportar_resultados(logs, data.validation_issues, str(outdir), cfg=cfg)

        eventos = _eventos_df(logs)
        evaluados_df = pd.read_csv(outdir / "funcionarios_evaluados.csv") if (outdir / "funcionarios_evaluados.csv").exists() else pd.DataFrame()

        st.subheader("2) Resultados")
        tabs = st.tabs(["Resumen", "Pirámide", "Flujo anual", "Trazabilidad", "Validación", "Descargas"])
        with tabs[0]:
            _tab_resumen(logs.snapshots, eventos, data.planta)
        with tabs[1]:
            _tab_piramide(logs.snapshots, data.planta)
        with tabs[2]:
            _tab_flujo(eventos)
        with tabs[3]:
            _tab_trazabilidad(eventos, evaluados_df)
        with tabs[4]:
            _tab_validacion(data.validation_issues)
        with tabs[5]:
            _tab_descargas(outdir)


if __name__ == "__main__":
    main()
