from datetime import date

from pdi_projection.config import AppConfig
from pdi_projection.domain import (
    PLANTA_OPPL_2025,
    Calificacion,
    EstadoFuncionario,
    Funcionario,
    Grado,
    Impedimento,
    TipoEvento,
    TipoImpedimento,
    Via,
)
from pdi_projection.domain.state_factory import construir_estado_inicial
from pdi_projection.eligibility import check_curso, check_lista, check_permanencia, get_elegibles, tiempo_en_grado
from pdi_projection.ingress import procesar_ingresos
from pdi_projection.promotion_engine import calcular_vacantes, ejecutar_ascensos
from pdi_projection.retirement import procesar_retiros


def mk_func(fid: str, grado: Grado, ingreso_grado_year=2020, ingreso_inst_year=2010, ant=1, listas=None, cursos=None, abono=0):
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
    )


def test_planta_coincide_con_csv_dotación_agregada():
    assert PLANTA_OPPL_2025[Grado.PREFECTO].vacantes_ley == 59
    assert PLANTA_OPPL_2025[Grado.SUBPREFECTO].vacantes_ley == 321


def test_cascada_libera_vacantes_correctamente():
    cfg = AppConfig()
    p1 = mk_func("p1", Grado.SUBPREFECTO, ant=1, cursos=["COG"])
    p2 = mk_func("p2", Grado.COMISARIO, ant=1)
    estado = construir_estado_inicial([p1, p2], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    estado.planta[Grado.SUBPREFECTO].vacantes_ley = 1
    estado.planta[Grado.COMISARIO].vacantes_ley = 1
    asc, _, _, _, decisiones = ejecutar_ascensos(estado, 2026, cfg)
    assert any(e.grado_destino == Grado.PREFECTO for e in asc)
    assert any(e.grado_destino == Grado.SUBPREFECTO for e in asc)
    assert len(decisiones) >= 2


def test_ciclo_5_1_respeta_proporción_en_ejecuciones_largas():
    cfg = AppConfig()
    funcs = [mk_func(f"f{i}", Grado.SUBPREFECTO, ant=i, cursos=["COG"]) for i in range(1, 13)]
    estado = construir_estado_inicial(funcs, 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 12
    asc, *_ = ejecutar_ascensos(estado, 2026, cfg)
    vias = [e.via for e in asc if e.grado_destino == Grado.PREFECTO]
    assert vias.count(Via.ANTIGUEDAD) == 2
    assert vias.count(Via.MERITO) == 10


def test_vacantes_no_provistas_acumulan_correctamente():
    cfg = AppConfig()
    estado = construir_estado_inicial([], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 3
    ejecutar_ascensos(estado, 2026, cfg)
    assert estado.vacantes_no_provistas[Grado.PREFECTO] == 3


def test_retiro_30_años_dispara_en_año_correcto():
    f = mk_func("r1", Grado.COMISARIO, ingreso_inst_year=1996)
    estado = construir_estado_inicial([f], 2026)
    ev = procesar_retiros(estado, 2026, AppConfig())
    assert len(ev) == 1
    assert estado.funcionarios["r1"].estado == EstadoFuncionario.RETIRADO_CARRERA_30


def test_sobredotacion_dtv_rechaza_cuando_no_hay_absorción():
    cfg = AppConfig()
    estado = construir_estado_inicial([], 2026)
    for g in estado.planta:
        estado.planta[g].vacantes_ley = 0
    nuevos = [mk_func(f"n{i}", Grado.DETECTIVE, ingreso_inst_year=2026) for i in range(3)]
    ing, rej = procesar_ingresos(estado, 2026, nuevos, cfg)
    assert len(ing) == 0
    assert len(rej) == 3


def test_lista_4_retira_inmediatamente():
    f = mk_func("l4", Grado.INSPECTOR, listas=[Calificacion(2025, 4)])
    estado = construir_estado_inicial([f], 2026)
    ev = procesar_retiros(estado, 2026, AppConfig())
    assert len(ev) == 1
    assert ev[0].tipo == TipoEvento.RETIRO


def test_lista_3_posterga_sin_retirar():
    f = mk_func("l3", Grado.INSPECTOR, listas=[Calificacion(2025, 3)])
    status, _ = check_lista(f, 2026, AppConfig())
    assert status.value == "postergado_lista"


def test_abono_meses_adelanta_elegibilidad_temporal():
    f = mk_func("ab", Grado.SUBINSPECTOR, ingreso_grado_year=2024, abono=12)
    estado = construir_estado_inicial([f], 2026)
    assert tiempo_en_grado(f, 2026) == 3
    assert check_permanencia(f, 2026, estado.planta)


def test_ascensos_no_exceden_vacantes_disponibles():
    cfg = AppConfig()
    funcs = [mk_func(f"x{i}", Grado.SUBPREFECTO, ant=i, cursos=["COG"]) for i in range(1, 10)]
    estado = construir_estado_inicial(funcs, 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 2
    asc, _p, _e, _r, _d = ejecutar_ascensos(estado, 2026, cfg)
    assert len([e for e in asc if e.grado_destino == Grado.PREFECTO]) == 2


def test_funcionario_postergado_conserva_antiguedad():
    cfg = AppConfig()
    f1 = mk_func("a", Grado.SUBPREFECTO, ant=1, cursos=["COG"])
    f2 = mk_func("b", Grado.SUBPREFECTO, ant=2, cursos=["COG"])
    estado = construir_estado_inicial([f1, f2], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    ejecutar_ascensos(estado, 2026, cfg)
    assert estado.funcionarios["b"].antiguedad_escalafon == 2


def test_curso_cog_obligatorio_solo_para_pft():
    f = mk_func("c1", Grado.SUBPREFECTO, cursos=[])
    assert not check_curso(f, Grado.PREFECTO)
    assert check_curso(f, Grado.SUBPREFECTO)


def test_config_cambia_retiro_obligatorio():
    f = mk_func("r2", Grado.COMISARIO, ingreso_inst_year=1997)
    estado = construir_estado_inicial([f], 2026)
    cfg = AppConfig()
    cfg.policy.mandatory_career_years = 31
    ev = procesar_retiros(estado, 2026, cfg)
    assert len(ev) == 0


def test_config_salud_no_bloquea_si_policy_false():
    f = mk_func("s1", Grado.SUBPREFECTO, cursos=["COG"])
    f.impedimentos = [Impedimento(TipoImpedimento.SALUD, date(2025, 1, 1), None)]
    estado = construir_estado_inicial([f], 2026)
    cfg = AppConfig()
    cfg.policy.health_blocks_promotion = False
    elegibles, traces = get_elegibles(estado, Grado.SUBPREFECTO, 2026, Grado.PREFECTO, cfg)
    assert len(elegibles) == 1
    assert traces[0].cumple_impedimento


def test_trazabilidad_ranking_y_elegibilidad():
    cfg = AppConfig()
    funcs = [mk_func("t1", Grado.SUBPREFECTO, ant=2, cursos=["COG"]), mk_func("t2", Grado.SUBPREFECTO, ant=1, cursos=["COG"])]
    estado = construir_estado_inicial(funcs, 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    _asc, _post, e_traces, r_traces, d_traces = ejecutar_ascensos(estado, 2026, cfg)
    eleg_pft = [t for t in e_traces if t.grado_destino == Grado.PREFECTO]
    rank_pft = [r for r in r_traces if r.grado_destino == Grado.PREFECTO]
    dec_pft = [d for d in d_traces if d.grado_destino == Grado.PREFECTO]
    assert len(eleg_pft) == 2
    assert len(rank_pft) == 2
    assert len(dec_pft) == 1
    assert dec_pft[0].decisiones


def test_transitoria_incrementa_vacante():
    cfg = AppConfig()
    estado = construir_estado_inicial([], 2027, transitorias={(2027, Grado.PREFECTO): 2})
    estado.planta[Grado.PREFECTO].vacantes_ley = 0
    assert calcular_vacantes(Grado.PREFECTO, 2027, estado, cfg) == 2


def test_fallback_habilita_ascenso_cuando_falla_lane():
    cfg = AppConfig()
    cfg.policy.allow_lane_fallback = True
    cfg.merit.config["mapeo_lista_puntaje"] = {1: 0, 2: 0, 3: 0, 4: None}
    f = mk_func("fb", Grado.SUBPREFECTO, ant=1, cursos=["COG"], listas=[Calificacion(2025, 1)])
    estado = construir_estado_inicial([f], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    asc, *_ = ejecutar_ascensos(estado, 2026, cfg)
    assert len(asc) == 1
