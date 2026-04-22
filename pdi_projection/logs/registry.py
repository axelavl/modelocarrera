from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from pdi_projection.domain import (
    EligibilityTrace,
    EstadoEscalafon,
    EstadoFuncionario,
    EventoCarrera,
    Grado,
    PromotionDecisionTrace,
    RankingTrace,
)


@dataclass
class LogsRegistry:
    eventos_por_año: dict[int, list[EventoCarrera]] = field(default_factory=lambda: defaultdict(list))
    snapshots: dict[int, dict[Grado, int]] = field(default_factory=dict)
    elegibilidad_trazas: list[EligibilityTrace] = field(default_factory=list)
    ranking_trazas: list[RankingTrace] = field(default_factory=list)
    decision_trazas: list[PromotionDecisionTrace] = field(default_factory=list)

    def registrar(self, eventos: list[EventoCarrera], año: int) -> None:
        self.eventos_por_año[año].extend(eventos)

    def registrar_elegibilidad(self, trazas: list[EligibilityTrace]) -> None:
        self.elegibilidad_trazas.extend(trazas)

    def registrar_ranking(self, trazas: list[RankingTrace]) -> None:
        self.ranking_trazas.extend(trazas)

    def registrar_decisiones(self, trazas: list[PromotionDecisionTrace]) -> None:
        self.decision_trazas.extend(trazas)

    def snapshot(self, estado: EstadoEscalafon, año: int) -> None:
        self.snapshots[año] = {
            g: sum(1 for f in estado.funcionarios.values() if f.estado == EstadoFuncionario.ACTIVO and f.grado_actual == g)
            for g in estado.planta
        }
