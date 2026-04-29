from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from pdi_projection.domain import AscensoHistorico, EventoCarrera, Grado, TipoEvento, Via


@dataclass
class ResultadoBacktest:
    """Resultado de comparar ascensos simulados contra ascensos históricos.

    Cada item es una tupla (funcionario_id, año, grado_destino) salvo
    `via_mismatches`, que añade ambas vías para inspección.
    """

    matches: list[tuple[str, int, Grado]] = field(default_factory=list)
    falsos_positivos: list[tuple[str, int, Grado]] = field(default_factory=list)
    falsos_negativos: list[tuple[str, int, Grado]] = field(default_factory=list)
    via_mismatches: list[tuple[str, int, Grado, Via | None, Via | None]] = field(default_factory=list)
    metricas_globales: dict[str, float] = field(default_factory=dict)
    metricas_por_año: dict[int, dict[str, float]] = field(default_factory=dict)


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _metricas(matches: int, fp: int, fn: int) -> dict[str, float]:
    pred = matches + fp
    real = matches + fn
    precision = matches / pred if pred else 0.0
    recall = matches / real if real else 0.0
    return {
        "matches": matches,
        "falsos_positivos": fp,
        "falsos_negativos": fn,
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
        "soporte_simulado": pred,
        "soporte_historico": real,
    }


def comparar_ascensos(
    eventos_simulados: list[EventoCarrera],
    historico: list[AscensoHistorico],
    año_desde: int | None = None,
    año_hasta: int | None = None,
) -> ResultadoBacktest:
    """Compara los ascensos del log de simulación contra el registro histórico.

    Una coincidencia se define por la tripleta (funcionario_id, año, grado_destino).
    Si ambos coinciden pero la vía difiere, se reporta en ``via_mismatches``.
    """

    def en_rango(año: int) -> bool:
        if año_desde is not None and año < año_desde:
            return False
        if año_hasta is not None and año > año_hasta:
            return False
        return True

    sim: dict[tuple[str, int, Grado], EventoCarrera] = {}
    for e in eventos_simulados:
        if e.tipo != TipoEvento.ASCENSO or e.grado_destino is None:
            continue
        if not en_rango(e.año):
            continue
        sim[(e.funcionario_id, e.año, e.grado_destino)] = e

    hist: dict[tuple[str, int, Grado], AscensoHistorico] = {}
    for h in historico:
        if not en_rango(h.año):
            continue
        hist[(h.funcionario_id, h.año, h.grado_destino)] = h

    keys_sim = set(sim.keys())
    keys_hist = set(hist.keys())
    keys_match = keys_sim & keys_hist

    matches = sorted(keys_match)
    falsos_positivos = sorted(keys_sim - keys_hist)
    falsos_negativos = sorted(keys_hist - keys_sim)

    via_mismatches: list[tuple[str, int, Grado, Via | None, Via | None]] = []
    for k in matches:
        via_sim = sim[k].via
        via_hist = hist[k].via
        if via_hist is not None and via_sim != via_hist:
            via_mismatches.append((k[0], k[1], k[2], via_sim, via_hist))

    metricas_globales = _metricas(len(matches), len(falsos_positivos), len(falsos_negativos))

    años = sorted({k[1] for k in keys_sim | keys_hist})
    metricas_por_año: dict[int, dict[str, float]] = {}
    for año in años:
        m = sum(1 for k in matches if k[1] == año)
        fp = sum(1 for k in falsos_positivos if k[1] == año)
        fn = sum(1 for k in falsos_negativos if k[1] == año)
        metricas_por_año[año] = _metricas(m, fp, fn)

    return ResultadoBacktest(
        matches=matches,
        falsos_positivos=falsos_positivos,
        falsos_negativos=falsos_negativos,
        via_mismatches=via_mismatches,
        metricas_globales=metricas_globales,
        metricas_por_año=metricas_por_año,
    )


def metricas_por_grado_destino(resultado: ResultadoBacktest) -> dict[Grado, dict[str, float]]:
    """Desglose de métricas por grado de destino, útil para identificar
    grados donde el modelo discrepa más con el histórico."""
    por_grado: dict[Grado, dict[str, int]] = defaultdict(lambda: {"matches": 0, "fp": 0, "fn": 0})
    for _, _, g in resultado.matches:
        por_grado[g]["matches"] += 1
    for _, _, g in resultado.falsos_positivos:
        por_grado[g]["fp"] += 1
    for _, _, g in resultado.falsos_negativos:
        por_grado[g]["fn"] += 1
    return {g: _metricas(v["matches"], v["fp"], v["fn"]) for g, v in por_grado.items()}
