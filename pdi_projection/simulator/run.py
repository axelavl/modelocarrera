from __future__ import annotations

from pdi_projection import ingress, retirement
from pdi_projection.config import AppConfig
from pdi_projection.logs import LogsRegistry
from pdi_projection.promotion_engine import ejecutar_ascensos


def simular(
    estado_inicial,
    año_base: int,
    horizonte: int,
    ingresos_por_año: dict[int, list],
    config: AppConfig | None = None,
) -> LogsRegistry:
    """Simulación anual orquestada con políticas configurables."""
    estado = estado_inicial
    logs = LogsRegistry()
    cfg = config or AppConfig()

    for t in range(año_base, año_base + horizonte + 1):
        estado.año_actual = t
        retiros = retirement.procesar_retiros(estado, t, cfg)
        logs.registrar(retiros, t)

        ingresos_evt, rechazos_evt = ingress.procesar_ingresos(estado, t, ingresos_por_año.get(t, []), cfg)
        logs.registrar(ingresos_evt, t)
        logs.registrar(rechazos_evt, t)

        ascensos, postergados, eleg_trazas, rank_trazas, dec_trazas = ejecutar_ascensos(estado, t, cfg)
        logs.registrar(ascensos, t)
        logs.registrar(postergados, t)
        logs.registrar_elegibilidad(eleg_trazas)
        logs.registrar_ranking(rank_trazas)
        logs.registrar_decisiones(dec_trazas)

        logs.snapshot(estado, t)

    return logs
