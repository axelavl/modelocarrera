from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from pdi_projection.config import AppConfig
from pdi_projection.data_loader import cargar_tabular
from pdi_projection.domain import Grado, construir_estado_inicial
from pdi_projection.outputs import exportar_resultados
from pdi_projection.simulator import simular

REQUIRED_FILES = [
    "funcionarios.csv",
    "planta_vacantes.csv",
    "ingresos.csv",
]
OPTIONAL_FILES = [
    "calificaciones.csv",
    "cursos.csv",
    "impedimentos.csv",
    "transitorias.csv",
    "ascensos_hist.csv",
]


@st.cache_data(show_spinner=False)
def read_csv_safe(path: str):
    return pd.read_csv(path)


def _save_uploaded_files(uploaded: list, tmpdir: Path) -> None:
    for f in uploaded:
        (tmpdir / f.name).write_bytes(f.getbuffer())


def _build_config() -> AppConfig:
    st.sidebar.header("Parámetros de simulación")
    cfg = AppConfig()
    cfg.policy.mandatory_career_years = st.sidebar.number_input("Retiro obligatorio (años)", min_value=20, max_value=40, value=30)
    cfg.policy.health_blocks_promotion = st.sidebar.checkbox("Salud bloquea ascenso", value=True)
    cfg.policy.accumulate_unfilled_vacancies = st.sidebar.checkbox("Acumular vacantes no provistas", value=True)
    cfg.policy.enforce_batch_cutoff_on_missing_lane_candidate = st.sidebar.checkbox("Aplicar corte de tanda (R12)", value=True)
    cfg.policy.allow_lane_fallback = st.sidebar.checkbox("Permitir fallback entre vías", value=False)
    cfg.policy.enable_sobredotacion_absorption = st.sidebar.checkbox("Permitir sobredotación con absorción", value=True)
    cfg.policy.treat_missing_calificacion_as_lista2 = st.sidebar.checkbox("Sin calificación -> lista 2", value=True)

    st.sidebar.subheader("Fórmula de mérito")
    cfg.merit.config["ventana_años"] = st.sidebar.slider("Ventana años", 1, 5, 3)
    cfg.merit.config["ponderadores_temporales"] = [0.5, 0.3, 0.2]
    return cfg


def main() -> None:
    st.set_page_config(page_title="OPPL/PDI Proyección", layout="wide")
    st.title("Sistema de Proyección OPPL/PDI — UI rápida")
    st.caption("Carga CSV, ajusta parámetros y ejecuta simulación anual.")

    cfg = _build_config()

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("1) Cargar archivos")
        uploaded = st.file_uploader(
            "Sube los archivos CSV de entrada",
            type=["csv"],
            accept_multiple_files=True,
        )

        if uploaded:
            uploaded_names = sorted([f.name for f in uploaded])
            st.write("Archivos cargados:", uploaded_names)
            missing = [f for f in REQUIRED_FILES if f not in uploaded_names]
            if missing:
                st.error(f"Faltan archivos requeridos: {missing}")
            else:
                st.success("Archivos requeridos presentes")

    with col2:
        st.subheader("2) Horizonte")
        año_base = st.number_input("Año base", min_value=2000, max_value=2100, value=2026)
        horizonte = st.number_input("Horizonte (años)", min_value=0, max_value=50, value=5)

    run = st.button("Ejecutar simulación", type="primary", disabled=not uploaded)

    if not run:
        return

    uploaded_names = sorted([f.name for f in uploaded])
    missing = [f for f in REQUIRED_FILES if f not in uploaded_names]
    if missing:
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
        logs = simular(
            estado,
            año_base=año_base,
            horizonte=horizonte,
            ingresos_por_año=data.ingresos_por_año,
            config=cfg,
        )

        outdir = tmpdir / "outputs"
        exportar_resultados(logs, data.validation_issues, str(outdir))

        st.subheader("3) Validación")
        if data.validation_issues:
            val_df = pd.DataFrame([vars(i) for i in data.validation_issues])
            st.dataframe(val_df, use_container_width=True)
        else:
            st.success("Sin observaciones de validación")

        st.subheader("4) Resultados")
        resultados_path = outdir / "resultados_proyeccion.csv"
        if resultados_path.exists():
            res_df = read_csv_safe(str(resultados_path))
            st.dataframe(res_df.head(1000), use_container_width=True)

            pivot = res_df.pivot_table(index="año", columns="grado", values="dotacion", aggfunc="sum")
            st.line_chart(pivot)

        indicadores_path = outdir / "indicadores.csv"
        if indicadores_path.exists():
            ind_df = read_csv_safe(str(indicadores_path))
            st.dataframe(ind_df.head(1000), use_container_width=True)

        st.subheader("5) Descargas")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in outdir.glob("*.csv"):
                zf.write(p, arcname=p.name)
        buffer.seek(0)

        st.download_button(
            label="Descargar outputs (ZIP)",
            data=buffer,
            file_name="outputs_oppl_pdi.zip",
            mime="application/zip",
        )


if __name__ == "__main__":
    main()
