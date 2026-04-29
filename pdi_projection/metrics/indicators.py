from __future__ import annotations

from collections import defaultdict

from pdi_projection.domain import Grado, Planta, TipoEvento, Via


def elegibles_por_grado(logs, año: int) -> dict[Grado, int]:
    """Elegibles efectivos por grado de origen en el año (proxy:
    ascensos + postergaciones observados)."""
    out: dict[Grado, int] = defaultdict(int)
    for ev in logs.eventos_por_año.get(año, []):
        if ev.tipo in {TipoEvento.ASCENSO, TipoEvento.POSTERGACION_VACANTE} and ev.grado_origen:
            out[ev.grado_origen] += 1
    return dict(out)


def presion_ascenso(logs, año: int) -> dict[Grado, float]:
    """Cantidad de elegibles por grado en el año (mismo cálculo que
    elegibles_por_grado, expuesto como float para gráficos)."""
    return {g: float(v) for g, v in elegibles_por_grado(logs, año).items()}


def tiempo_espera_promedio(logs) -> dict[Grado, float]:
    """Para cada grado de destino, tiempo promedio (en años) entre la
    primera vez que un funcionario apareció como elegible y el año en
    que efectivamente fue ascendido. Postergados se descartan."""
    primer_eleg: dict[tuple[str, Grado], int] = {}
    for trace in logs.elegibilidad_trazas:
        if not trace.elegible:
            continue
        key = (trace.funcionario_id, trace.grado_destino)
        primer_eleg[key] = min(primer_eleg.get(key, trace.año), trace.año)

    esperas: dict[Grado, list[int]] = defaultdict(list)
    for evs in logs.eventos_por_año.values():
        for e in evs:
            if e.tipo != TipoEvento.ASCENSO or e.grado_destino is None:
                continue
            key = (e.funcionario_id, e.grado_destino)
            if key in primer_eleg:
                esperas[e.grado_destino].append(e.año - primer_eleg[key])
    return {g: sum(v) / len(v) for g, v in esperas.items() if v}


def vacantes_no_provistas(logs) -> dict[tuple[int, Grado], int]:
    """Vacantes que quedaron sin proveer al cierre de cada (año, grado)."""
    return {(d.año, d.grado_destino): d.vacantes_finales for d in logs.decision_trazas if d.vacantes_finales > 0}


def cuello_botella(logs) -> list[tuple[int, Grado, float]]:
    """Lista (año, grado, ratio) ordenada descendente por presión sobre la
    cascada: ratio = postergados / vacantes_iniciales por grado/año.
    Solo se reportan grados con vacantes_iniciales > 0."""
    out: list[tuple[int, Grado, float]] = []
    postergados_por_clave: dict[tuple[int, Grado], int] = defaultdict(int)
    for año, evs in logs.eventos_por_año.items():
        for e in evs:
            if e.tipo == TipoEvento.POSTERGACION_VACANTE and e.grado_destino:
                postergados_por_clave[(año, e.grado_destino)] += 1
    for d in logs.decision_trazas:
        if d.vacantes_iniciales <= 0:
            continue
        post = postergados_por_clave.get((d.año, d.grado_destino), 0)
        out.append((d.año, d.grado_destino, post / d.vacantes_iniciales))
    return sorted(out, key=lambda r: r[2], reverse=True)


def tasa_postergacion(logs, año: int) -> dict[Grado, float]:
    """% de elegibles que quedaron postergados por grado destino en el año."""
    elegibles_por_destino: dict[Grado, int] = defaultdict(int)
    for trace in logs.elegibilidad_trazas:
        if trace.año == año and trace.elegible:
            elegibles_por_destino[trace.grado_destino] += 1
    postergados: dict[Grado, int] = defaultdict(int)
    for ev in logs.eventos_por_año.get(año, []):
        if ev.tipo == TipoEvento.POSTERGACION_VACANTE and ev.grado_destino:
            postergados[ev.grado_destino] += 1
    return {
        g: (postergados.get(g, 0) / total) if total else 0.0
        for g, total in elegibles_por_destino.items()
    }


def edad_promedio_ascenso(logs, funcionarios_iniciales: dict | None = None) -> dict[Grado, float]:
    """Edad promedio (en años) al momento del ascenso por grado destino.
    Requiere ``funcionarios_iniciales`` (dict id→Funcionario) para conocer
    la fecha de nacimiento. Sin ese dato no se puede calcular y se devuelve
    un dict vacío."""
    if not funcionarios_iniciales:
        return {}
    edades: dict[Grado, list[float]] = defaultdict(list)
    for evs in logs.eventos_por_año.values():
        for e in evs:
            if e.tipo != TipoEvento.ASCENSO or e.grado_destino is None:
                continue
            f = funcionarios_iniciales.get(e.funcionario_id)
            if f is None or f.fecha_nacimiento is None:
                continue
            edades[e.grado_destino].append(e.año - f.fecha_nacimiento.year)
    return {g: sum(v) / len(v) for g, v in edades.items() if v}


def distribucion_via(logs) -> dict[Grado, tuple[float, float]]:
    """Para cada grado destino, proporción (mérito, antigüedad) de los ascensos."""
    acc: dict[Grado, list[int]] = defaultdict(lambda: [0, 0])
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


def sobredotacion_por_grado(logs, planta: dict[Grado, Planta] | None = None,
                            transitorias: dict[tuple[int, Grado], int] | None = None) -> dict[tuple[int, Grado], int]:
    """Cantidad de funcionarios sobre la planta (incluyendo transitorias)
    por (año, grado). Solo se reportan claves con valor > 0. Si no se pasa
    ``planta``, devuelve un dict vacío."""
    if not planta:
        return {}
    transitorias = transitorias or {}
    out: dict[tuple[int, Grado], int] = {}
    for año, snap in logs.snapshots.items():
        for g, dot in snap.items():
            cap = planta[g].vacantes_ley + transitorias.get((año, g), 0) if g in planta else 0
            sobre = dot - cap
            if sobre > 0:
                out[(año, g)] = sobre
    return out
