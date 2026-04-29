from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from pdi_projection.domain import (
    EstadoFuncionario,
    Funcionario,
    Grado,
    TipoEvento,
)
from pdi_projection.logs import LogsRegistry


ESTADO_RETIRADO = "retirado"
ESTADO_ACTIVO = "activo"


class CohorteCriterio(Enum):
    POR_AÑO_INGRESO = "por_año_ingreso"
    POR_GRADO_EN_AÑO_BASE = "por_grado_en_año_base"


@dataclass
class _EstadoIndividual:
    grado: Grado | None
    estado: str  # "activo" o nombre del causal de retiro
    causal: str | None = None


def construir_trayectorias(
    logs: LogsRegistry,
    funcionarios_iniciales: dict[str, Funcionario],
    año_base: int,
) -> dict[int, dict[str, _EstadoIndividual]]:
    """Reconstruye, año por año, el grado y estado de cada funcionario aplicando los eventos del log.

    Incluye funcionarios que ingresan durante la simulación (TipoEvento.INGRESO).
    """
    actual: dict[str, _EstadoIndividual] = {
        fid: _EstadoIndividual(grado=f.grado_actual, estado=ESTADO_ACTIVO)
        for fid, f in funcionarios_iniciales.items()
    }
    años = sorted(set(logs.eventos_por_año.keys()) | set(logs.snapshots.keys()) | {año_base})
    trayectorias: dict[int, dict[str, _EstadoIndividual]] = {}
    for año in años:
        for ev in logs.eventos_por_año.get(año, []):
            fid = ev.funcionario_id
            if ev.tipo == TipoEvento.INGRESO:
                actual[fid] = _EstadoIndividual(grado=ev.grado_destino, estado=ESTADO_ACTIVO)
            elif ev.tipo == TipoEvento.ASCENSO:
                if fid in actual:
                    actual[fid].grado = ev.grado_destino
            elif ev.tipo == TipoEvento.RETIRO:
                causal = ev.causal.value if ev.causal else "retirado"
                if fid not in actual:
                    actual[fid] = _EstadoIndividual(grado=ev.grado_origen, estado=ESTADO_RETIRADO, causal=causal)
                else:
                    actual[fid].estado = ESTADO_RETIRADO
                    actual[fid].causal = causal
        trayectorias[año] = {fid: _EstadoIndividual(grado=v.grado, estado=v.estado, causal=v.causal) for fid, v in actual.items()}
    return trayectorias


def miembros_cohorte(
    funcionarios_iniciales: dict[str, Funcionario],
    criterio: CohorteCriterio,
    *,
    años_ingreso: Iterable[int] | None = None,
    grado_objetivo: Grado | None = None,
) -> set[str]:
    """Devuelve el conjunto de IDs que pertenecen a la cohorte solicitada."""
    if criterio == CohorteCriterio.POR_AÑO_INGRESO:
        años = set(años_ingreso or [])
        return {fid for fid, f in funcionarios_iniciales.items() if f.fecha_ingreso_institucion.year in años}
    if criterio == CohorteCriterio.POR_GRADO_EN_AÑO_BASE:
        return {fid for fid, f in funcionarios_iniciales.items() if f.grado_actual == grado_objetivo}
    raise ValueError(f"Criterio desconocido: {criterio}")


def distribucion_cohorte_por_año(
    trayectorias: dict[int, dict[str, _EstadoIndividual]],
    cohorte_ids: set[str],
) -> list[dict]:
    """Para cada año, cuántos miembros de la cohorte están en cada (grado | retirado)."""
    rows = []
    for año in sorted(trayectorias.keys()):
        snap = trayectorias[año]
        for fid in cohorte_ids:
            est = snap.get(fid)
            if est is None:
                rows.append({"año": año, "estado": "no_aparece", "grado": None})
                continue
            if est.estado == ESTADO_RETIRADO:
                rows.append({"año": año, "estado": f"retirado:{est.causal or 'otro'}", "grado": int(est.grado) if est.grado else None})
            else:
                rows.append({"año": año, "estado": "activo", "grado": int(est.grado) if est.grado else None})
    return rows


def resumen_cohorte(
    trayectorias: dict[int, dict[str, _EstadoIndividual]],
    cohorte_ids: set[str],
) -> dict:
    """Métricas agregadas: tamaño, % retirado al final, distribución de grado final entre activos."""
    if not trayectorias:
        return {"tamaño": len(cohorte_ids), "activos_final": 0, "retirados_final": 0, "grado_final_activos": {}}
    último = max(trayectorias.keys())
    snap = trayectorias[último]
    activos = 0
    retirados = 0
    distribucion: dict[str, int] = {}
    for fid in cohorte_ids:
        est = snap.get(fid)
        if est is None or est.grado is None:
            continue
        if est.estado == ESTADO_ACTIVO:
            activos += 1
            nombre = est.grado.name
            distribucion[nombre] = distribucion.get(nombre, 0) + 1
        else:
            retirados += 1
    return {
        "tamaño": len(cohorte_ids),
        "activos_final": activos,
        "retirados_final": retirados,
        "grado_final_activos": distribucion,
    }
