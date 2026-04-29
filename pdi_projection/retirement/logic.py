from __future__ import annotations

from pdi_projection.config import AppConfig
from pdi_projection.domain import CausalRetiro, EstadoEscalafon, EstadoFuncionario, EventoCarrera, TipoEvento
from pdi_projection.eligibility import años_carrera, lista_ultima


def procesar_retiros(estado: EstadoEscalafon, t: int, cfg: AppConfig) -> list[EventoCarrera]:
    eventos = []
    for f in list(estado.funcionarios.values()):
        if f.estado != EstadoFuncionario.ACTIVO:
            continue
        if f.retiro_voluntario_fecha and f.retiro_voluntario_fecha.year == t:
            f.estado = EstadoFuncionario.RETIRADO_VOLUNTARIO
            causal = f.retiro_voluntario_causal or CausalRetiro.VOLUNTARIO
        elif lista_ultima(f, t) == 4:
            f.estado = EstadoFuncionario.RETIRADO_LISTA_4
            causal = CausalRetiro.LISTA_4
        elif años_carrera(f, t) >= cfg.policy.mandatory_career_years:
            f.estado = EstadoFuncionario.RETIRADO_CARRERA_30
            causal = CausalRetiro.CARRERA_30
        else:
            continue
        eventos.append(EventoCarrera(f.id, t, TipoEvento.RETIRO, grado_origen=f.grado_actual, causal=causal))
    return eventos
