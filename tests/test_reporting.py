from datetime import date

import pandas as pd
import pytest

from pdi_projection.config import AppConfig
from pdi_projection.domain import Calificacion, Funcionario, Grado
from pdi_projection.reporting import (
    CohorteCriterio,
    barrer_parametro,
    construir_trayectorias,
    correr_escenarios,
    distribucion_cohorte_por_año,
    generar_informe_html,
    miembros_cohorte,
    resumen_cohorte,
)


def mk_func(fid, grado, ingreso_inst_year=2010, ant=1, listas=None, cursos=None, retiro_vol=None):
    return Funcionario(
        id=fid,
        fecha_nacimiento=date(1985, 1, 1),
        sexo="M",
        fecha_ingreso_institucion=date(ingreso_inst_year, 1, 1),
        fecha_ingreso_grado_actual=date(2018, 1, 1),
        grado_actual=grado,
        antiguedad_escalafon=ant,
        cursos_aprobados=set(cursos or []),
        historico_calificaciones=listas or [Calificacion(2025, 1)],
        retiro_voluntario_fecha=retiro_vol,
    )


def _build_inputs():
    funcs = [
        mk_func("a", Grado.SUBPREFECTO, ingreso_inst_year=2010, ant=1, cursos=["COG"]),
        mk_func("b", Grado.SUBPREFECTO, ingreso_inst_year=2010, ant=2, cursos=["COG"]),
        mk_func("c", Grado.COMISARIO, ingreso_inst_year=2012, ant=1),
    ]
    return funcs


def test_correr_escenarios_aisla_inputs_entre_corridas():
    funcs = _build_inputs()
    base = AppConfig()
    alt = AppConfig()
    alt.policy.mandatory_career_years = 25
    resultados = correr_escenarios(
        [("Base", base), ("Alt", alt)],
        funcionarios=funcs,
        año_base=2026,
        horizonte=2,
        planta=None,
        transitorias=None,
        ingresos_por_año={},
    )
    # Ambas corridas tienen sus propios funcionarios — el original no fue mutado.
    assert funcs[0].grado_actual == Grado.SUBPREFECTO
    nombres = [r.nombre for r in resultados]
    assert nombres == ["Base", "Alt"]
    assert resultados[0].config is base
    assert resultados[1].config is alt
    # Logs distintos: cada uno tiene snapshots por año.
    for r in resultados:
        assert sorted(r.logs.snapshots.keys()) == [2026, 2027, 2028]


def test_construir_trayectorias_reconstruye_grado_y_estado():
    funcs = _build_inputs()
    base = AppConfig()
    res = correr_escenarios(
        [("S", base)],
        funcionarios=funcs,
        año_base=2026,
        horizonte=1,
        planta=None,
        transitorias=None,
        ingresos_por_año={},
    )[0]
    tray = construir_trayectorias(res.logs, res.funcionarios_iniciales, año_base=2026)
    assert 2026 in tray and 2027 in tray
    assert tray[2026]["a"].estado == "activo"
    assert tray[2026]["a"].grado is not None


def test_miembros_cohorte_por_año_ingreso_y_grado():
    funcs = _build_inputs()
    funcs_dict = {f.id: f for f in funcs}
    ids_2010 = miembros_cohorte(funcs_dict, CohorteCriterio.POR_AÑO_INGRESO, años_ingreso=[2010])
    assert ids_2010 == {"a", "b"}
    ids_subprefecto = miembros_cohorte(
        funcs_dict, CohorteCriterio.POR_GRADO_EN_AÑO_BASE, grado_objetivo=Grado.SUBPREFECTO
    )
    assert ids_subprefecto == {"a", "b"}


def test_distribucion_y_resumen_cohorte():
    funcs = _build_inputs()
    base = AppConfig()
    res = correr_escenarios(
        [("S", base)],
        funcionarios=funcs,
        año_base=2026,
        horizonte=1,
        planta=None,
        transitorias=None,
        ingresos_por_año={},
    )[0]
    tray = construir_trayectorias(res.logs, res.funcionarios_iniciales, año_base=2026)
    cohorte = miembros_cohorte(res.funcionarios_iniciales, CohorteCriterio.POR_AÑO_INGRESO, años_ingreso=[2010])
    rows = distribucion_cohorte_por_año(tray, cohorte)
    assert rows  # al menos una fila por miembro × año
    resumen = resumen_cohorte(tray, cohorte)
    assert resumen["tamaño"] == 2
    assert resumen["activos_final"] + resumen["retirados_final"] <= 2


def test_generar_informe_html_es_auto_contenido():
    funcs = _build_inputs()
    res = correr_escenarios(
        [("S", AppConfig())],
        funcionarios=funcs,
        año_base=2026,
        horizonte=1,
        planta=None,
        transitorias=None,
        ingresos_por_año={},
    )[0]
    eventos_rows = []
    for año, evs in res.logs.eventos_por_año.items():
        for e in evs:
            eventos_rows.append({
                "año": año,
                "tipo": e.tipo.value,
                "via": e.via.value if e.via else "",
                "causal": e.causal.value if e.causal else "",
                "grado_destino": e.grado_destino.name if e.grado_destino else "",
            })
    eventos_df = pd.DataFrame(eventos_rows)
    html = generar_informe_html(
        snapshots=res.logs.snapshots,
        eventos_df=eventos_df,
        planta=res.estado_final.planta,
        validation_issues=[],
        config_resumen={"mandatory_career_years": 30},
    )
    assert html.startswith("<!doctype html>")
    assert "Informe de proyección OPPL/PDI" in html
    assert "vega-embed" in html  # script CDN incluido
    assert "kpi-grid" in html


def test_barrer_parametro_genera_un_escenario_por_valor():
    funcs = [mk_func(f"f{i}", Grado.SUBPREFECTO, ant=i, cursos=["COG"]) for i in range(1, 4)]
    base = AppConfig()
    resultados = barrer_parametro(
        nombre_parametro="mandatory_career_years",
        valores=[28, 30, 32],
        base_config=base,
        funcionarios=funcs,
        año_base=2026,
        horizonte=2,
        planta=None,
        transitorias=None,
        ingresos_por_año={},
    )
    assert [r.nombre for r in resultados] == [
        "mandatory_career_years=28",
        "mandatory_career_years=30",
        "mandatory_career_years=32",
    ]
    assert resultados[0].config.policy.mandatory_career_years == 28
    assert resultados[2].config.policy.mandatory_career_years == 32
    # Cada escenario produce su propio log independiente
    años = sorted(resultados[0].logs.snapshots.keys())
    assert años == [2026, 2027, 2028]


def test_barrer_parametro_falla_con_atributo_inexistente():
    with pytest.raises(ValueError, match="no es un atributo"):
        barrer_parametro(
            nombre_parametro="parametro_inventado",
            valores=[1, 2],
            base_config=AppConfig(),
            funcionarios=[],
            año_base=2026,
            horizonte=0,
            planta=None,
            transitorias=None,
            ingresos_por_año={},
        )
