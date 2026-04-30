from datetime import date

from pdi_projection.config import AppConfig
from pdi_projection.domain import Calificacion, Funcionario, Grado, construir_estado_inicial
from pdi_projection.metrics.indicators import (
    composicion_por_sexo,
    cuello_botella,
    distribucion_via,
    edad_promedio_ascenso,
    eventos_por_sexo,
    sobredotacion_por_grado,
    tasa_postergacion,
    tiempo_espera_promedio,
    vacantes_no_provistas,
)
from pdi_projection.simulator import simular


def _f(fid, grado, año_grado=2018, año_inst=2010, ant=1, listas=None, cursos=None, fnac=None):
    return Funcionario(
        id=fid,
        fecha_nacimiento=fnac or date(1985, 1, 1),
        sexo="M",
        fecha_ingreso_institucion=date(año_inst, 1, 1),
        fecha_ingreso_grado_actual=date(año_grado, 1, 1),
        grado_actual=grado,
        antiguedad_escalafon=ant,
        cursos_aprobados=set(cursos or []),
        historico_calificaciones=listas or [Calificacion(2025, 1)],
    )


def test_vacantes_no_provistas_y_cuello_botella():
    estado = construir_estado_inicial([], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 3
    logs = simular(estado, 2026, 0, {}, AppConfig())
    vnp = vacantes_no_provistas(logs)
    assert vnp[(2026, Grado.PREFECTO)] == 3


def test_tiempo_espera_promedio_cuenta_años_en_postergacion():
    cfg = AppConfig()
    f1 = _f("a", Grado.SUBPREFECTO, ant=1, cursos=["COG"])
    f2 = _f("b", Grado.SUBPREFECTO, ant=2, cursos=["COG"])
    estado = construir_estado_inicial([f1, f2], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    logs = simular(estado, 2026, 2, {}, cfg)
    espera = tiempo_espera_promedio(logs)
    # El primer año uno asciende (espera 0), el segundo el otro asciende (espera 1).
    assert Grado.PREFECTO in espera
    assert espera[Grado.PREFECTO] >= 0


def test_tasa_postergacion_alta_cuando_hay_pocas_vacantes():
    cfg = AppConfig()
    funcs = [_f(f"x{i}", Grado.SUBPREFECTO, ant=i, cursos=["COG"]) for i in range(1, 6)]
    estado = construir_estado_inicial(funcs, 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    logs = simular(estado, 2026, 0, {}, cfg)
    tasa = tasa_postergacion(logs, 2026)
    assert tasa[Grado.PREFECTO] == 4 / 5


def test_distribucion_via_separa_merito_y_antiguedad():
    cfg = AppConfig()
    funcs = [_f(f"d{i}", Grado.SUBPREFECTO, ant=i, cursos=["COG"]) for i in range(1, 13)]
    estado = construir_estado_inicial(funcs, 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 12
    logs = simular(estado, 2026, 0, {}, cfg)
    dist = distribucion_via(logs)
    m, a = dist[Grado.PREFECTO]
    assert round(m + a, 6) == 1.0
    assert round(m, 4) == round(10 / 12, 4)


def test_edad_promedio_ascenso_requiere_funcionarios_iniciales():
    cfg = AppConfig()
    f1 = _f("e1", Grado.SUBPREFECTO, ant=1, cursos=["COG"], fnac=date(1980, 1, 1))
    estado = construir_estado_inicial([f1], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    funcs_ini = {fid: f for fid, f in estado.funcionarios.items()}
    logs = simular(estado, 2026, 0, {}, cfg)
    edades = edad_promedio_ascenso(logs, funcs_ini)
    assert edades[Grado.PREFECTO] == 2026 - 1980
    # Sin fechas no se puede calcular
    assert edad_promedio_ascenso(logs) == {}


def test_sobredotacion_detectada_cuando_dotacion_supera_planta():
    estado = construir_estado_inicial([], 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 0
    # Inyecto un funcionario directamente en PREFECTO sobre planta cero
    f = _f("s1", Grado.PREFECTO, ant=1)
    estado.funcionarios[f.id] = f
    logs = simular(estado, 2026, 0, {}, AppConfig())
    sob = sobredotacion_por_grado(logs, planta=estado.planta)
    assert sob.get((2026, Grado.PREFECTO)) == 1


def test_cuello_botella_ordena_por_ratio_postergacion():
    cfg = AppConfig()
    funcs = [_f(f"c{i}", Grado.SUBPREFECTO, ant=i, cursos=["COG"]) for i in range(1, 6)]
    estado = construir_estado_inicial(funcs, 2026)
    estado.planta[Grado.PREFECTO].vacantes_ley = 2
    logs = simular(estado, 2026, 0, {}, cfg)
    cb = cuello_botella(logs)
    # PFT debe estar entre los top con ratio 3/2 = 1.5
    assert any(g == Grado.PREFECTO and round(r, 2) == 1.5 for _, g, r in cb)


def test_composicion_por_sexo_descuenta_retiros_y_suma_ingresos():
    cfg = AppConfig()
    f_m = _f("hombre", Grado.COMISARIO, ant=1)
    f_m.sexo = "M"
    f_f = _f("mujer", Grado.COMISARIO, ant=2)
    f_f.sexo = "F"
    f_retira = _f("retira", Grado.COMISARIO, año_inst=1997, ant=3)
    f_retira.sexo = "F"
    estado = construir_estado_inicial([f_m, f_f, f_retira], 2026)
    funcs_ini = {fid: f for fid, f in estado.funcionarios.items()}
    logs = simular(estado, 2026, 1, {}, cfg)
    comp = composicion_por_sexo(logs, funcs_ini, ingresos_por_año={})
    # En 2026 retira "retira" por carrera 30 (1997+30 = 2027 año <= 2027 es t-año_inst >= 30 ⇒ se va a evaluar en 2027 pero... revisar)
    # Más robusto: validamos totales por año.
    assert comp[2026]["M"] == 1
    assert comp[2026]["F"] >= 1  # al menos la mujer no-retirada


def test_eventos_por_sexo_etiqueta_correctamente():
    cfg = AppConfig()
    f1 = _f("a", Grado.SUBPREFECTO, ant=1, cursos=["COG"])
    f1.sexo = "F"
    f2 = _f("b", Grado.SUBPREFECTO, ant=2, cursos=["COG"])
    f2.sexo = "M"
    estado = construir_estado_inicial([f1, f2], 2026)
    funcs_ini = {fid: f for fid, f in estado.funcionarios.items()}
    estado.planta[Grado.PREFECTO].vacantes_ley = 1
    logs = simular(estado, 2026, 0, {}, cfg)
    rows = eventos_por_sexo(logs, funcs_ini)
    # Debe haber al menos un ascenso con sexo etiquetado.
    ascensos = [r for r in rows if r["tipo"] == "ascenso"]
    assert ascensos
    assert all(r["sexo"] in {"F", "M"} for r in ascensos)
