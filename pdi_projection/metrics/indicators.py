from __future__ import annotations

from collections import defaultdict

from pdi_projection.domain import Grado, TipoEvento, Via


def elegibles_por_grado(logs, año: int) -> dict[Grado, int]:
    # Proxy usando postergados+ascensos observados como elegibles efectivos.
    out = defaultdict(int)
    for ev in logs.eventos_por_año.get(año, []):
        if ev.tipo in {TipoEvento.ASCENSO, TipoEvento.POSTERGACION_VACANTE} and ev.grado_origen:
            out[ev.grado_origen] += 1
    return dict(out)


def presion_ascenso(logs, año: int) -> dict[Grado, float]:
    return {g: float(v) for g, v in elegibles_por_grado(logs, año).items()}


def tiempo_espera_promedio(logs) -> dict[Grado, float]:
    return {}


def vacantes_no_provistas(logs) -> dict[tuple[int, Grado], int]:
    return {}


def cuello_botella(logs) -> list[tuple[int, Grado, float]]:
    return []


def tasa_postergacion(logs, año: int) -> dict[Grado, float]:
    return {}


def edad_promedio_ascenso(logs) -> dict[Grado, float]:
    return {}


def distribucion_via(logs) -> dict[Grado, tuple[float, float]]:
    acc = defaultdict(lambda: [0, 0])
    for eventos in logs.eventos_por_año.values():
        for ev in eventos:
            if ev.tipo == TipoEvento.ASCENSO and ev.grado_destino:
                if ev.via == Via.MERITO:
                    acc[ev.grado_destino][0] += 1
                elif ev.via == Via.ANTIGUEDAD:
                    acc[ev.grado_destino][1] += 1
    out = {}
    for g, (m, a) in acc.items():
        total = m + a
        out[g] = (m / total if total else 0.0, a / total if total else 0.0)
    return out


def dotacion_por_grado(logs, año: int) -> dict[Grado, int]:
    return logs.snapshots.get(año, {})


def trayectoria_individual(logs, f_id: str) -> list[tuple[int, Grado]]:
    out = []
    for año, eventos in sorted(logs.eventos_por_año.items()):
        for ev in eventos:
            if ev.funcionario_id == f_id and ev.tipo == TipoEvento.ASCENSO and ev.grado_destino:
                out.append((año, ev.grado_destino))
    return out


def sobredotacion_por_grado(logs) -> dict[tuple[int, Grado], int]:
    return {}
