from datetime import date
from pathlib import Path

from pdi_projection.config import AppConfig
from pdi_projection.data_loader import cargar_tabular
from pdi_projection.domain import (
    Calificacion,
    EstadoFuncionario,
    Funcionario,
    Grado,
    TipoEvento,
)
from pdi_projection.domain.state_factory import construir_estado_inicial
from pdi_projection.ingress import procesar_ingresos
from pdi_projection.outputs import exportar_resultados
from pdi_projection.promotion_engine import ejecutar_ascensos
from pdi_projection.retirement import procesar_retiros
from pdi_projection.simulator import simular


def mk_func(fid, grado, ingreso_grado_year=2020, ingreso_inst_year=2010, ant=1, listas=None, cursos=None, abono=0, retiro_vol=None):
    return Funcionario(
        id=fid,
        fecha_nacimiento=date(1985, 1, 1),
        sexo="M",
        fecha_ingreso_institucion=date(ingreso_inst_year, 1, 1),
        fecha_ingreso_grado_actual=date(ingreso_grado_year, 1, 1),
        grado_actual=grado,
        antiguedad_escalafon=ant,
        cursos_aprobados=set(cursos or []),
        historico_calificaciones=listas if listas is not None else [Calificacion(2025, 1)],
        abono_meses=abono,
        retiro_voluntario_fecha=retiro_vol,
    )


def test_cascada_multianual_libera_vacantes_progresivamente():
    cfg = AppConfig()
    pft = mk_func("pft", Grado.PREFECTO, ingreso_grado_year=2020, ingreso_inst_year=2000, ant=1, retiro_vol=date(2027, 1, 1))
    spt = mk_func("spt", Grado.SUBPREFECTO, ingreso_grado_year=2018, ant=1, cursos=["COG"])
    cms = mk_func("cms", Grado.COMISARIO, ingreso_grado_year=2015, ant=1)
    estado = construir_estado_inicial([pft, spt, cms], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    estado.planta[Grado.SUBPREFECTO].vacantes_ley = 1
    estado.planta[Grado.COMISARIO].vacantes_ley = 1

    logs = simular(estado, 2026, 2, ingresos_por_año={}, config=cfg)

    # 2027: PFT retira, SPT debe ascender a PFT y CMS a SPT.
    eventos_2027 = logs.eventos_por_año[2027]
    ascensos_2027 = [e for e in eventos_2027 if e.tipo == TipoEvento.ASCENSO]
    destinos = {(e.funcionario_id, e.grado_destino) for e in ascensos_2027}
    assert ("spt", Grado.PREFECTO) in destinos
    assert ("cms", Grado.SUBPREFECTO) in destinos


def test_vacantes_no_provistas_caducan_con_ttl():
    cfg = AppConfig()
    cfg.policy.unfilled_vacancy_ttl_years = 1
    estado = construir_estado_inicial([], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 3
    ejecutar_ascensos(estado, 2026, cfg)
    assert estado.vacantes_no_provistas[Grado.PREFECTO] == 3
    # Segundo año sin elegibles: vacancy_age supera TTL y se resetea.
    ejecutar_ascensos(estado, 2027, cfg)
    assert estado.vacantes_no_provistas[Grado.PREFECTO] == 0


def test_ingreso_aprovecha_capacidad_de_absorcion():
    cfg = AppConfig()  # enable_sobredotacion_absorption=True por default
    estado = construir_estado_inicial([], 2026)
    for g in estado.planta:
        estado.planta[g].vacantes_ley = 0
    estado.planta[Grado.PREFECTO].vacantes_ley = 2  # capacidad superior abierta
    nuevos = [mk_func(f"n{i}", Grado.DETECTIVE, ingreso_inst_year=2026) for i in range(2)]
    ing, rej = procesar_ingresos(estado, 2026, nuevos, cfg)
    assert len(ing) == 2
    assert len(rej) == 0


def test_retiro_voluntario_dispara_en_año_indicado():
    f = mk_func("v1", Grado.INSPECTOR, retiro_vol=date(2027, 6, 1))
    estado = construir_estado_inicial([f], 2026)
    ev_2026 = procesar_retiros(estado, 2026, AppConfig())
    assert ev_2026 == []
    assert estado.funcionarios["v1"].estado == EstadoFuncionario.ACTIVO
    estado.año_actual = 2027
    ev_2027 = procesar_retiros(estado, 2027, AppConfig())
    assert len(ev_2027) == 1
    assert estado.funcionarios["v1"].estado == EstadoFuncionario.RETIRADO_VOLUNTARIO


def test_postergacion_lista3_no_cambia_estado_pero_excluye_de_elegibles():
    cfg = AppConfig()
    f = mk_func("p3", Grado.SUBPREFECTO, cursos=["COG"], listas=[Calificacion(2025, 3)])
    estado = construir_estado_inicial([f], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    asc, post, eleg, rank, dec = ejecutar_ascensos(estado, 2026, cfg)
    assert estado.funcionarios["p3"].estado == EstadoFuncionario.ACTIVO
    assert all(not t.elegible for t in eleg if t.funcionario_id == "p3")
    assert not any(e.funcionario_id == "p3" for e in asc)


def test_loader_reporta_columnas_faltantes_como_warning(tmp_path: Path):
    # funcionarios.csv válido pero planta_vacantes sin columna requerida
    (tmp_path / "funcionarios.csv").write_text(
        "id,fecha_nacimiento,sexo,fecha_ingreso_institucion,fecha_ingreso_grado_actual,grado_actual,"
        "antiguedad_escalafon,abono_meses,retiro_voluntario_fecha,retiro_voluntario_causal\n",
        encoding="utf-8",
    )
    (tmp_path / "planta_vacantes.csv").write_text("grado,vacantes_ley\n5,10\n", encoding="utf-8")
    (tmp_path / "ingresos.csv").write_text("id,fecha_nombramiento,fecha_nacimiento,sexo\n", encoding="utf-8")
    data = cargar_tabular(str(tmp_path), AppConfig())
    codes = {(i.code, i.severity) for i in data.validation_issues}
    assert any(code == "MISSING_COLUMNS" for code, _ in codes)


def test_exportar_resultados_genera_decisiones_y_ranking_y_manifest(tmp_path: Path):
    cfg = AppConfig()
    funcs = [mk_func(f"e{i}", Grado.SUBPREFECTO, ant=i, cursos=["COG"]) for i in range(1, 4)]
    estado = construir_estado_inicial(funcs, 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 2
    logs = simular(estado, 2026, 0, {}, cfg)
    outdir = tmp_path / "out"
    exportar_resultados(logs, [], str(outdir), cfg=cfg)
    nombres = {p.name for p in outdir.iterdir()}
    assert "decisiones_promocion.csv" in nombres
    assert "ranking.csv" in nombres
    assert "manifest.json" in nombres

    ranking_csv = (outdir / "ranking.csv").read_text(encoding="utf-8").splitlines()
    assert ranking_csv[0].split(",")[0] == "año"
    decisiones_csv = (outdir / "decisiones_promocion.csv").read_text(encoding="utf-8").splitlines()
    assert decisiones_csv[0].startswith("año,grado_destino")


def test_exportar_resultados_genera_csv_con_headers_aunque_esten_vacios(tmp_path: Path):
    estado = construir_estado_inicial([], 2026)
    logs = simular(estado, 2026, 0, {}, AppConfig())
    outdir = tmp_path / "out"
    exportar_resultados(logs, [], str(outdir))
    contenido = (outdir / "ascensos.csv").read_text(encoding="utf-8").strip()
    assert contenido == "funcionario_id,año,origen,destino,via,motivo"
    contenido_val = (outdir / "reporte_validacion.csv").read_text(encoding="utf-8").strip()
    assert contenido_val == "severity,code,message,row_ref"


# ----------------------------------------------------------------------------
# Decisiones normativas (README §8). Cada test fija explícitamente la decisión
# en el AppConfig para que un cambio de default no pase silenciosamente.
# ----------------------------------------------------------------------------


def test_decision_3B_sin_calificacion_posterga_y_no_asciende():
    """Decisión 3.B: un funcionario sin calificación reportada queda postergado."""
    cfg = AppConfig()
    assert cfg.policy.treat_missing_calificacion_as_lista2 is False
    f = mk_func("sin_cal", Grado.SUBPREFECTO, ant=1, cursos=["COG"], listas=[])
    estado = construir_estado_inicial([f], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    asc, post, eleg, _, _ = ejecutar_ascensos(estado, 2026, cfg)
    # No es ascendido y queda con motivo "sin_calificacion".
    assert not any(e.funcionario_id == "sin_cal" for e in asc)
    trazas = [t for t in eleg if t.funcionario_id == "sin_cal"]
    assert trazas
    assert all(not t.elegible for t in trazas)
    assert any(t.motivo == "sin_calificacion" for t in trazas)


def test_decision_3B_se_puede_invertir_con_dial():
    """El comportamiento histórico (asumir lista 2) sigue disponible vía toggle."""
    cfg = AppConfig()
    cfg.policy.treat_missing_calificacion_as_lista2 = True
    f = mk_func("sin_cal", Grado.SUBPREFECTO, ant=1, cursos=["COG"], listas=[])
    estado = construir_estado_inicial([f], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    asc, _, _, _, _ = ejecutar_ascensos(estado, 2026, cfg)
    assert any(e.funcionario_id == "sin_cal" for e in asc)


def test_decision_4C_salud_no_bloquea_ascenso_por_default():
    """Decisión 4.C: salud no bloquea ni causa retiro."""
    from pdi_projection.domain import Impedimento, TipoImpedimento
    cfg = AppConfig()
    assert cfg.policy.health_blocks_promotion is False
    f = mk_func("salud", Grado.SUBPREFECTO, ant=1, cursos=["COG"])
    f.impedimentos = [Impedimento(TipoImpedimento.SALUD, date(2025, 1, 1), None)]
    estado = construir_estado_inicial([f], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    asc, _, _, _, _ = ejecutar_ascensos(estado, 2026, cfg)
    # Salud no bloquea: el funcionario asciende.
    assert any(e.funcionario_id == "salud" for e in asc)
    # Y tampoco se retira.
    eventos_ret = procesar_retiros(estado, 2026, cfg)
    assert not any(e.funcionario_id == "salud" for e in eventos_ret)
