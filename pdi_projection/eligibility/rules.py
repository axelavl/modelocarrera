from __future__ import annotations

from datetime import date

from pdi_projection.config import AppConfig
from pdi_projection.domain import (
    CURSOS_REQUERIDOS_POR_GRADO,
    EligibilityTrace,
    EstadoElegibilidad,
    EstadoEscalafon,
    EstadoFuncionario,
    Funcionario,
    Grado,
    TipoImpedimento,
)


def tiempo_en_grado(f: Funcionario, t: int) -> float:
    return (t - f.fecha_ingreso_grado_actual.year) + f.abono_meses / 12


def años_carrera(f: Funcionario, t: int) -> int:
    return t - f.fecha_ingreso_institucion.year


def lista_ultima(f: Funcionario, t: int) -> int | None:
    relevantes = [c for c in f.historico_calificaciones if c.año < t]
    if not relevantes:
        return None
    return max(relevantes, key=lambda c: c.año).lista


def check_permanencia(f: Funcionario, t: int, planta: dict) -> bool:
    return tiempo_en_grado(f, t) >= planta[f.grado_actual].permanencia_min_años


def check_curso(f: Funcionario, grado_destino: Grado, cursos_requeridos: dict[Grado, set[str]] | None = None) -> bool:
    cursos_requeridos = cursos_requeridos if cursos_requeridos is not None else CURSOS_REQUERIDOS_POR_GRADO
    if grado_destino not in cursos_requeridos:
        return True
    return cursos_requeridos[grado_destino].issubset(f.cursos_aprobados)


def check_impedimento(f: Funcionario, t: int, cfg: AppConfig) -> tuple[bool, str | None]:
    fecha_t = date(t, cfg.policy.event_month_day[0], cfg.policy.event_month_day[1])
    for i in f.impedimentos:
        if i.tipo == TipoImpedimento.SALUD and not cfg.policy.health_blocks_promotion:
            continue
        if i.fecha_inicio <= fecha_t and (i.fecha_fin is None or fecha_t <= i.fecha_fin):
            return True, i.tipo.value
    return False, None


def check_lista(f: Funcionario, t: int, cfg: AppConfig) -> tuple[EstadoElegibilidad, int | None]:
    l = lista_ultima(f, t)
    if l is None:
        if cfg.policy.treat_missing_calificacion_as_lista2:
            l = 2
        else:
            # Decisión 3.B: sin calificación → no elegible (postergado).
            return EstadoElegibilidad.POSTERGADO_LISTA, None
    if l == 4:
        return EstadoElegibilidad.RETIRADO, l
    if l == 3:
        return EstadoElegibilidad.POSTERGADO_LISTA, l
    return EstadoElegibilidad.ELEGIBLE, l


def evaluar_elegibilidad(f: Funcionario, estado: EstadoEscalafon, t: int, grado_destino: Grado, cfg: AppConfig) -> EligibilityTrace:
    status_lista, lista_valor = check_lista(f, t, cfg)
    if status_lista == EstadoElegibilidad.RETIRADO:
        return EligibilityTrace(f.id, t, f.grado_actual, grado_destino, False, lista_valor, False, None, False, tiempo_en_grado(f, t), False, False, status_lista, "lista_4")
    if status_lista == EstadoElegibilidad.POSTERGADO_LISTA:
        motivo = "sin_calificacion" if lista_valor is None else "lista_3"
        return EligibilityTrace(f.id, t, f.grado_actual, grado_destino, False, lista_valor, False, None, False, tiempo_en_grado(f, t), False, False, status_lista, motivo)

    impedido, tipo_impedimento = check_impedimento(f, t, cfg)
    cumple_tiempo = check_permanencia(f, t, estado.planta)
    cumple_curso = check_curso(f, grado_destino)

    estado_eleg = EstadoElegibilidad.ELEGIBLE
    motivo = "ok"
    if impedido:
        estado_eleg = EstadoElegibilidad.NO_ELEGIBLE_IMPEDIMENTO
        motivo = f"impedimento_{tipo_impedimento}"
    elif not cumple_tiempo:
        estado_eleg = EstadoElegibilidad.NO_ELEGIBLE_TIEMPO
        motivo = "permanencia_insuficiente"
    elif not cumple_curso:
        estado_eleg = EstadoElegibilidad.NO_ELEGIBLE_CURSO
        motivo = "curso_no_cumplido"

    return EligibilityTrace(
        funcionario_id=f.id,
        año=t,
        grado_origen=f.grado_actual,
        grado_destino=grado_destino,
        cumple_lista=True,
        lista_valor=lista_valor,
        cumple_impedimento=not impedido,
        impedimento_activo=tipo_impedimento,
        cumple_tiempo=cumple_tiempo,
        tiempo_en_grado=tiempo_en_grado(f, t),
        cumple_curso=cumple_curso,
        elegible=estado_eleg == EstadoElegibilidad.ELEGIBLE,
        estado=estado_eleg,
        motivo=motivo,
    )


def get_elegibles(
    estado: EstadoEscalafon,
    grado_origen: Grado,
    t: int,
    grado_destino: Grado,
    cfg: AppConfig,
) -> tuple[list[Funcionario], list[EligibilityTrace]]:
    elegibles = []
    trazas = []
    for f in estado.funcionarios.values():
        if f.estado != EstadoFuncionario.ACTIVO or f.grado_actual != grado_origen:
            continue
        trace = evaluar_elegibilidad(f, estado, t, grado_destino, cfg)
        trazas.append(trace)
        if trace.elegible:
            elegibles.append(f)
    return elegibles, trazas
