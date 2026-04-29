from __future__ import annotations

import io
import json
import tempfile
import zipfile
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from pdi_projection.config import AppConfig
from pdi_projection.data_loader import cargar_tabular
from pdi_projection.domain import Grado, SECUENCIA_OPPL, construir_estado_inicial
from pdi_projection.outputs import exportar_resultados
from pdi_projection.reporting import (
    CohorteCriterio,
    construir_trayectorias,
    correr_escenarios,
    distribucion_cohorte_por_año,
    generar_informe_html,
    miembros_cohorte,
    resumen_cohorte,
)
from pdi_projection.simulator import simular


REQUIRED_FILES = ["funcionarios.csv", "planta_vacantes.csv", "ingresos.csv"]
GRADO_NOMBRE = {int(g): g.name for g in Grado}
ORDEN_JERARQUICO = [g.name for g in reversed(SECUENCIA_OPPL)]


def _save_uploaded_files(uploaded: list, tmpdir: Path) -> None:
    for f in uploaded:
        (tmpdir / f.name).write_bytes(f.getbuffer())


def _config_widgets(prefix: str, defaults: AppConfig | None = None) -> AppConfig:
    cfg = AppConfig()
    base = defaults or AppConfig()
    cfg.policy.mandatory_career_years = st.number_input(
        "Retiro obligatorio (años de carrera)", min_value=20, max_value=40,
        value=base.policy.mandatory_career_years, key=f"{prefix}_career",
    )
    cfg.policy.health_blocks_promotion = st.checkbox(
        "Salud bloquea ascenso", value=base.policy.health_blocks_promotion, key=f"{prefix}_salud"
    )
    cfg.policy.accumulate_unfilled_vacancies = st.checkbox(
        "Acumular vacantes no provistas", value=base.policy.accumulate_unfilled_vacancies, key=f"{prefix}_acum"
    )
    ttl_default = base.policy.unfilled_vacancy_ttl_years or 0
    ttl = st.number_input(
        "TTL vacantes no provistas (años, 0 = sin TTL)", min_value=0, max_value=20, value=ttl_default, key=f"{prefix}_ttl"
    )
    cfg.policy.unfilled_vacancy_ttl_years = ttl if ttl > 0 else None
    cfg.policy.enforce_batch_cutoff_on_missing_lane_candidate = st.checkbox(
        "Aplicar corte de tanda (R12)",
        value=base.policy.enforce_batch_cutoff_on_missing_lane_candidate, key=f"{prefix}_r12",
    )
    cfg.policy.allow_lane_fallback = st.checkbox(
        "Permitir fallback entre vías", value=base.policy.allow_lane_fallback, key=f"{prefix}_fb"
    )
    cfg.policy.enable_sobredotacion_absorption = st.checkbox(
        "Permitir sobredotación con absorción",
        value=base.policy.enable_sobredotacion_absorption, key=f"{prefix}_sobre",
    )
    cfg.policy.treat_missing_calificacion_as_lista2 = st.checkbox(
        "Sin calificación → lista 2",
        value=base.policy.treat_missing_calificacion_as_lista2, key=f"{prefix}_l2",
    )
    cfg.merit.config["ventana_años"] = st.slider("Ventana mérito (años)", 1, 5, base.merit.config.get("ventana_años", 3), key=f"{prefix}_vent")
    return cfg


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


def _kpis(snapshots: dict, eventos: pd.DataFrame, planta: dict) -> None:
    años = sorted(snapshots.keys())
    año_ini, año_fin = años[0], años[-1]
    dot_ini = sum(snapshots[año_ini].values())
    dot_fin = sum(snapshots[año_fin].values())
    planta_total = sum(p.vacantes_ley for p in planta.values()) if planta else 0
    cobertura_fin = (dot_fin / planta_total * 100) if planta_total else 0
    n_asc = int((eventos["tipo"] == "ascenso").sum()) if not eventos.empty else 0
    n_ret = int((eventos["tipo"] == "retiro").sum()) if not eventos.empty else 0
    n_post = int((eventos["tipo"] == "postergacion_vacante").sum()) if not eventos.empty else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Dotación inicial", f"{dot_ini:,}")
    c2.metric("Dotación final", f"{dot_fin:,}", delta=f"{dot_fin - dot_ini:+,}")
    c3.metric("Cobertura planta (final)", f"{cobertura_fin:.1f}%")
    c4.metric(f"Ascensos {año_ini}–{año_fin}", f"{n_asc:,}")
    c5.metric(f"Retiros {año_ini}–{año_fin}", f"{n_ret:,}",
              delta=f"-{n_post} post." if n_post else None, delta_color="off")


def _tab_resumen(snapshots: dict, eventos: pd.DataFrame, planta: dict) -> None:
    _kpis(snapshots, eventos, planta)
    st.divider()
    rows = [
        {"año": año, "grado": GRADO_NOMBRE[int(g)], "dotacion": dot}
        for año, snap in sorted(snapshots.items())
        for g, dot in snap.items()
    ]
    df = pd.DataFrame(rows)
    st.markdown("**Evolución de la dotación por grado**")
    chart = (
        alt.Chart(df).mark_area().encode(
            x=alt.X("año:O", title="Año"),
            y=alt.Y("dotacion:Q", title="Dotación", stack="zero"),
            color=alt.Color("grado:N", sort=ORDEN_JERARQUICO, title="Grado"),
            tooltip=["año", "grado", "dotacion"],
        ).properties(height=380)
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
        plan = planta.get(g).vacantes_ley if planta and g in planta else 0
        rows.append({"grado": GRADO_NOMBRE[int(g)], "dotacion": dot, "planta": plan, "brecha": plan - dot})
    df = pd.DataFrame(rows)
    df["grado"] = pd.Categorical(df["grado"], categories=ORDEN_JERARQUICO, ordered=True)
    df = df.sort_values("grado")
    base = alt.Chart(df).encode(y=alt.Y("grado:N", sort=ORDEN_JERARQUICO, title=None))
    barras_planta = base.mark_bar(color="#cfd8dc", size=22).encode(x=alt.X("planta:Q", title="Funcionarios"), tooltip=["grado", "planta"])
    barras_dot = base.mark_bar(color="#1f77b4", size=14).encode(x="dotacion:Q", tooltip=["grado", "dotacion"])
    st.markdown(f"**Pirámide jerárquica — Año {año}** (gris = planta de ley · azul = dotación efectiva)")
    st.altair_chart((barras_planta + barras_dot).properties(height=320), use_container_width=True)
    df_view = df.copy()
    df_view["cobertura_%"] = df_view.apply(lambda r: round(100 * r["dotacion"] / r["planta"], 1) if r["planta"] else None, axis=1)
    st.dataframe(df_view[["grado", "dotacion", "planta", "brecha", "cobertura_%"]], use_container_width=True, hide_index=True)


def _tab_flujo(eventos: pd.DataFrame) -> None:
    if eventos.empty:
        st.info("Sin eventos en el horizonte simulado.")
        return
    asc = eventos[eventos["tipo"] == "ascenso"]
    if not asc.empty:
        st.markdown("**Ascensos por año y vía**")
        agg = asc.groupby(["año", "via"]).size().reset_index(name="n")
        st.altair_chart(
            alt.Chart(agg).mark_bar().encode(x="año:O", y="n:Q", color="via:N", tooltip=["año", "via", "n"]).properties(height=240),
            use_container_width=True,
        )
        st.markdown("**Ascensos por grado destino**")
        agg2 = asc.groupby(["año", "grado_destino"]).size().reset_index(name="n")
        st.altair_chart(
            alt.Chart(agg2).mark_bar().encode(
                x="año:O", y="n:Q",
                color=alt.Color("grado_destino:N", sort=ORDEN_JERARQUICO),
                tooltip=["año", "grado_destino", "n"],
            ).properties(height=240),
            use_container_width=True,
        )
    ret = eventos[eventos["tipo"] == "retiro"]
    if not ret.empty:
        st.markdown("**Retiros por año y causal**")
        agg = ret.groupby(["año", "causal"]).size().reset_index(name="n")
        st.altair_chart(
            alt.Chart(agg).mark_bar().encode(x="año:O", y="n:Q", color="causal:N", tooltip=["año", "causal", "n"]).properties(height=240),
            use_container_width=True,
        )
    post = eventos[eventos["tipo"] == "postergacion_vacante"]
    if not post.empty:
        st.markdown("**Postergaciones por año y grado destino**")
        agg = post.groupby(["año", "grado_destino"]).size().reset_index(name="n")
        st.altair_chart(
            alt.Chart(agg).mark_bar().encode(
                x="año:O", y="n:Q",
                color=alt.Color("grado_destino:N", sort=ORDEN_JERARQUICO),
                tooltip=["año", "grado_destino", "n"],
            ).properties(height=240),
            use_container_width=True,
        )


def _tab_trazabilidad(eventos: pd.DataFrame, evaluados_df: pd.DataFrame) -> None:
    ids = sorted(eventos["funcionario_id"].unique()) if not eventos.empty else []
    if not ids:
        st.info("Sin funcionarios con eventos.")
        return
    fid = st.selectbox("Funcionario", ids)
    st.markdown("**Línea de eventos**")
    st.dataframe(eventos[eventos["funcionario_id"] == fid].sort_values("año"), use_container_width=True, hide_index=True)
    if not evaluados_df.empty:
        st.markdown("**Evaluaciones de elegibilidad**")
        st.dataframe(
            evaluados_df[evaluados_df["funcionario_id"] == fid].sort_values(["año", "grado_destino"]),
            use_container_width=True, hide_index=True,
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


def _tab_cohortes(resultado, año_base: int) -> None:
    funcs_iniciales = resultado.funcionarios_iniciales
    if not funcs_iniciales:
        st.info("No hay funcionarios para construir cohortes.")
        return
    criterio_label = st.radio(
        "Criterio de cohorte",
        ["Año de ingreso a la institución", "Grado en año base"],
        horizontal=True,
    )
    if criterio_label.startswith("Año"):
        años_disp = sorted({f.fecha_ingreso_institucion.year for f in funcs_iniciales.values()})
        seleccion = st.multiselect("Años de ingreso", años_disp, default=años_disp[:1] if años_disp else [])
        cohorte = miembros_cohorte(funcs_iniciales, CohorteCriterio.POR_AÑO_INGRESO, años_ingreso=seleccion)
    else:
        grado = st.selectbox("Grado", list(SECUENCIA_OPPL), format_func=lambda g: g.name)
        cohorte = miembros_cohorte(funcs_iniciales, CohorteCriterio.POR_GRADO_EN_AÑO_BASE, grado_objetivo=grado)

    if not cohorte:
        st.warning("La cohorte seleccionada está vacía.")
        return

    tray = construir_trayectorias(resultado.logs, funcs_iniciales, año_base=año_base)
    rows = distribucion_cohorte_por_año(tray, cohorte)
    df = pd.DataFrame(rows)
    df["categoria"] = df.apply(
        lambda r: r["estado"] if r["estado"].startswith("retirado") else (GRADO_NOMBRE.get(r["grado"], "—") if r["grado"] else "—"),
        axis=1,
    )
    agg = df.groupby(["año", "categoria"]).size().reset_index(name="n")

    resumen = resumen_cohorte(tray, cohorte)
    c1, c2, c3 = st.columns(3)
    c1.metric("Tamaño cohorte", resumen["tamaño"])
    c2.metric("Activos al final", resumen["activos_final"])
    c3.metric("Retirados al final", resumen["retirados_final"])

    st.markdown("**Distribución por año**")
    chart = (
        alt.Chart(agg).mark_area().encode(
            x="año:O", y=alt.Y("n:Q", stack="zero"),
            color=alt.Color("categoria:N", title="Categoría"),
            tooltip=["año", "categoria", "n"],
        ).properties(height=320)
    )
    st.altair_chart(chart, use_container_width=True)

    if resumen["grado_final_activos"]:
        st.markdown("**Distribución de grado al final del horizonte (solo activos)**")
        df_g = pd.DataFrame(
            [{"grado": k, "n": v} for k, v in resumen["grado_final_activos"].items()]
        )
        df_g["grado"] = pd.Categorical(df_g["grado"], categories=ORDEN_JERARQUICO, ordered=True)
        df_g = df_g.sort_values("grado")
        st.dataframe(df_g, use_container_width=True, hide_index=True)


def _tab_descargas(outdir: Path, html_report: str) -> None:
    csvs = sorted(outdir.glob("*.csv"))
    manifest = outdir / "manifest.json"
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
    c1, c2 = st.columns(2)
    c1.download_button("Descargar CSVs (ZIP)", data=buffer, file_name="outputs_oppl_pdi.zip", mime="application/zip")
    c2.download_button(
        "Descargar informe (HTML, imprimible a PDF)",
        data=html_report.encode("utf-8"),
        file_name="informe_oppl_pdi.html",
        mime="text/html",
    )
    if manifest.exists():
        with st.expander("Ver manifest.json"):
            st.code(manifest.read_text(encoding="utf-8"), language="json")


# ---------- modo comparador ----------

def _kpis_comparativos(resultados: list) -> None:
    rows = []
    for r in resultados:
        años = sorted(r.logs.snapshots.keys())
        año_ini, año_fin = años[0], años[-1]
        dot_ini = sum(r.logs.snapshots[año_ini].values())
        dot_fin = sum(r.logs.snapshots[año_fin].values())
        n_asc = sum(1 for evs in r.logs.eventos_por_año.values() for e in evs if e.tipo.value == "ascenso")
        n_ret = sum(1 for evs in r.logs.eventos_por_año.values() for e in evs if e.tipo.value == "retiro")
        n_post = sum(1 for evs in r.logs.eventos_por_año.values() for e in evs if e.tipo.value == "postergacion_vacante")
        rows.append({
            "escenario": r.nombre,
            "dotacion_inicial": dot_ini,
            "dotacion_final": dot_fin,
            "delta_dotacion": dot_fin - dot_ini,
            "ascensos": n_asc,
            "retiros": n_ret,
            "postergados": n_post,
        })
    df = pd.DataFrame(rows)
    st.markdown("**KPIs comparativos**")
    st.dataframe(df, use_container_width=True, hide_index=True)


def _tab_comparador(resultados: list) -> None:
    _kpis_comparativos(resultados)
    st.divider()

    rows = []
    for r in resultados:
        for año, snap in sorted(r.logs.snapshots.items()):
            rows.append({"escenario": r.nombre, "año": año, "total": sum(snap.values())})
    df = pd.DataFrame(rows)
    st.markdown("**Dotación total — comparación**")
    st.altair_chart(
        alt.Chart(df).mark_line(point=True).encode(
            x="año:O", y=alt.Y("total:Q", title="Dotación total"),
            color=alt.Color("escenario:N", title="Escenario"),
            tooltip=["escenario", "año", "total"],
        ).properties(height=320),
        use_container_width=True,
    )

    rows_g = []
    for r in resultados:
        for año, snap in sorted(r.logs.snapshots.items()):
            for g, dot in snap.items():
                rows_g.append({"escenario": r.nombre, "año": año, "grado": GRADO_NOMBRE[int(g)], "dotacion": dot})
    df_g = pd.DataFrame(rows_g)
    grado_sel = st.selectbox("Ver evolución por grado", ORDEN_JERARQUICO, index=0)
    sub = df_g[df_g["grado"] == grado_sel]
    st.altair_chart(
        alt.Chart(sub).mark_line(point=True).encode(
            x="año:O", y=alt.Y("dotacion:Q", title=f"Dotación {grado_sel}"),
            color=alt.Color("escenario:N", title="Escenario"),
            tooltip=["escenario", "año", "dotacion"],
        ).properties(height=280),
        use_container_width=True,
    )

    st.markdown("**Eventos acumulados por escenario**")
    ev_rows = []
    for r in resultados:
        for año, evs in r.logs.eventos_por_año.items():
            for e in evs:
                ev_rows.append({"escenario": r.nombre, "tipo": e.tipo.value})
    if ev_rows:
        df_ev = pd.DataFrame(ev_rows)
        agg = df_ev.groupby(["escenario", "tipo"]).size().reset_index(name="n")
        st.altair_chart(
            alt.Chart(agg).mark_bar().encode(
                x="tipo:N", y="n:Q",
                color="escenario:N",
                column="escenario:N",
                tooltip=["escenario", "tipo", "n"],
            ).properties(height=240),
            use_container_width=True,
        )


# ---------- main ----------

def _run_simulacion(uploaded, año_base: int, horizonte: int, cfg: AppConfig, tmpdir: Path):
    _save_uploaded_files(uploaded, tmpdir)
    data = cargar_tabular(str(tmpdir), cfg)
    funcs = deepcopy(data.funcionarios)
    estado = construir_estado_inicial(funcs, año_base=año_base, planta=data.planta, transitorias=data.transitorias)
    funcs_iniciales = deepcopy(estado.funcionarios)
    logs = simular(estado, año_base=año_base, horizonte=horizonte, ingresos_por_año=deepcopy(data.ingresos_por_año), config=cfg)
    return data, estado, logs, funcs_iniciales


class _SimResult:
    def __init__(self, nombre, config, logs, estado_final, funcionarios_iniciales):
        self.nombre = nombre
        self.config = config
        self.logs = logs
        self.estado_final = estado_final
        self.funcionarios_iniciales = funcionarios_iniciales


def main() -> None:
    st.set_page_config(page_title="OPPL/PDI Proyección", layout="wide")
    st.title("Sistema de Proyección OPPL/PDI")
    st.caption("Simulador anual con trazabilidad de cada decisión.")

    modo = st.sidebar.radio("Modo", ["Simulación única", "Comparador de escenarios"])

    with st.sidebar.expander("Horizonte", expanded=True):
        año_base = st.number_input("Año base", min_value=2000, max_value=2100, value=2026)
        horizonte = st.number_input("Horizonte (años)", min_value=0, max_value=50, value=5)

    st.subheader("1) Cargar archivos de entrada")
    uploaded = st.file_uploader("CSV de entrada (drag & drop)", type=["csv"], accept_multiple_files=True)
    if uploaded:
        nombres = sorted([f.name for f in uploaded])
        faltantes = [f for f in REQUIRED_FILES if f not in nombres]
        c1, c2 = st.columns([3, 1])
        c1.write(f"Archivos cargados: {', '.join(nombres)}")
        if faltantes:
            c2.error(f"Faltan: {faltantes}")
        else:
            c2.success("Requeridos OK")

    if modo == "Simulación única":
        _modo_simple(uploaded, año_base, horizonte)
    else:
        _modo_comparador(uploaded, año_base, horizonte)


def _modo_simple(uploaded, año_base, horizonte):
    with st.sidebar.expander("Configuración", expanded=True):
        cfg = _config_widgets("single")

    run = st.button("Ejecutar simulación", type="primary", disabled=not uploaded)
    if not run:
        st.info("Cargue los CSV y presione **Ejecutar simulación** para ver el dashboard.")
        return
    nombres = sorted([f.name for f in uploaded])
    if any(f not in nombres for f in REQUIRED_FILES):
        st.stop()

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        data, estado, logs, funcs_iniciales = _run_simulacion(uploaded, año_base, horizonte, cfg, tmpdir)
        outdir = tmpdir / "outputs"
        exportar_resultados(logs, data.validation_issues, str(outdir), cfg=cfg)

        eventos = _eventos_df(logs)
        evaluados_df = pd.read_csv(outdir / "funcionarios_evaluados.csv") if (outdir / "funcionarios_evaluados.csv").exists() else pd.DataFrame()
        config_resumen = asdict(cfg.policy)
        html_report = generar_informe_html(
            snapshots=logs.snapshots, eventos_df=eventos, planta=data.planta,
            validation_issues=data.validation_issues, config_resumen=config_resumen,
        )

        result = _SimResult("Base", cfg, logs, estado, funcs_iniciales)

        st.subheader("2) Resultados")
        tabs = st.tabs(["Resumen", "Pirámide", "Flujo anual", "Cohortes", "Trazabilidad", "Validación", "Descargas"])
        with tabs[0]:
            _tab_resumen(logs.snapshots, eventos, data.planta)
        with tabs[1]:
            _tab_piramide(logs.snapshots, data.planta)
        with tabs[2]:
            _tab_flujo(eventos)
        with tabs[3]:
            _tab_cohortes(result, año_base)
        with tabs[4]:
            _tab_trazabilidad(eventos, evaluados_df)
        with tabs[5]:
            _tab_validacion(data.validation_issues)
        with tabs[6]:
            _tab_descargas(outdir, html_report)


def _modo_comparador(uploaded, año_base, horizonte):
    n_esc = st.sidebar.number_input("Cantidad de escenarios", min_value=2, max_value=4, value=2)
    escenarios_def: list[tuple[str, AppConfig]] = []
    for i in range(int(n_esc)):
        with st.sidebar.expander(f"Escenario {i+1}", expanded=(i == 0)):
            nombre = st.text_input("Nombre", value=f"Escenario {chr(65+i)}", key=f"esc_{i}_nombre")
            cfg = _config_widgets(f"esc_{i}")
            escenarios_def.append((nombre, cfg))

    run = st.button("Ejecutar comparador", type="primary", disabled=not uploaded)
    if not run:
        st.info("Defina los escenarios en la sidebar y presione **Ejecutar comparador**.")
        return
    nombres = sorted([f.name for f in uploaded])
    if any(f not in nombres for f in REQUIRED_FILES):
        st.stop()

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        _save_uploaded_files(uploaded, tmpdir)
        data = cargar_tabular(str(tmpdir), AppConfig())
        resultados = correr_escenarios(
            escenarios_def,
            funcionarios=data.funcionarios,
            año_base=año_base,
            horizonte=horizonte,
            planta=data.planta,
            transitorias=data.transitorias,
            ingresos_por_año=data.ingresos_por_año,
        )

        st.subheader("2) Comparación")
        tab_comp, *tabs_det = st.tabs(["Comparación"] + [r.nombre for r in resultados])
        with tab_comp:
            _tab_comparador(resultados)
        for tab, r in zip(tabs_det, resultados):
            with tab:
                eventos = _eventos_df(r.logs)
                outdir = tmpdir / f"outputs_{r.nombre.replace(' ', '_')}"
                exportar_resultados(r.logs, data.validation_issues, str(outdir), cfg=r.config)
                evaluados_df = pd.read_csv(outdir / "funcionarios_evaluados.csv") if (outdir / "funcionarios_evaluados.csv").exists() else pd.DataFrame()
                html_report = generar_informe_html(
                    snapshots=r.logs.snapshots, eventos_df=eventos, planta=r.estado_final.planta,
                    validation_issues=data.validation_issues, config_resumen=asdict(r.config.policy),
                )
                sub = st.tabs(["Resumen", "Pirámide", "Flujo", "Cohortes", "Validación", "Descargas"])
                with sub[0]:
                    _tab_resumen(r.logs.snapshots, eventos, r.estado_final.planta)
                with sub[1]:
                    _tab_piramide(r.logs.snapshots, r.estado_final.planta)
                with sub[2]:
                    _tab_flujo(eventos)
                with sub[3]:
                    _tab_cohortes(r, año_base)
                with sub[4]:
                    _tab_validacion(data.validation_issues)
                with sub[5]:
                    _tab_descargas(outdir, html_report)


if __name__ == "__main__":
    main()
