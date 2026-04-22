from __future__ import annotations

from pdi_projection.config import AppConfig
from pdi_projection.domain import EstadoEscalafon, EstadoFuncionario, EventoCarrera, Grado, TipoEvento
from pdi_projection.promotion_engine import calcular_vacantes, siguiente_numero_escalafon


def procesar_ingresos(estado: EstadoEscalafon, t: int, nuevos: list, cfg: AppConfig) -> tuple[list[EventoCarrera], list[EventoCarrera]]:
    """Regla configurable de sobredotación DTV y capacidad de absorción."""
    eventos_ingreso = []
    eventos_rechazo = []
    vacantes_dtv = calcular_vacantes(Grado.DETECTIVE, t, estado, cfg)

    if cfg.policy.enable_sobredotacion_absorption:
        capacidad_absorcion = sum(
            calcular_vacantes(g, t, estado, cfg)
            for g in [Grado.SUBINSPECTOR, Grado.INSPECTOR, Grado.SUBCOMISARIO, Grado.COMISARIO, Grado.SUBPREFECTO, Grado.PREFECTO]
        )
    else:
        capacidad_absorcion = 0

    capacidad_total = vacantes_dtv + capacidad_absorcion
    aceptados = nuevos[:capacidad_total]
    rechazados = nuevos[capacidad_total:]

    for f in aceptados:
        f.grado_actual = Grado.DETECTIVE
        f.fecha_ingreso_grado_actual = f.fecha_ingreso_institucion
        f.antiguedad_escalafon = siguiente_numero_escalafon(estado, Grado.DETECTIVE)
        f.estado = EstadoFuncionario.ACTIVO
        estado.funcionarios[f.id] = f
        if estado.vacantes_no_provistas[Grado.DETECTIVE] > 0:
            estado.vacantes_no_provistas[Grado.DETECTIVE] -= 1
        eventos_ingreso.append(EventoCarrera(f.id, t, TipoEvento.INGRESO, grado_destino=Grado.DETECTIVE))

    for f in rechazados:
        eventos_rechazo.append(
            EventoCarrera(f.id, t, TipoEvento.INGRESO_RECHAZADO, motivo="sobredotacion_sin_absorcion")
        )
    return eventos_ingreso, eventos_rechazo
