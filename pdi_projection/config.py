from __future__ import annotations

from dataclasses import dataclass, field

from pdi_projection.domain.models import MERITO_CONFIG_DEFAULT, Grado

NORMATIVE_HARD_RULES = {
    "R1": "Permanencia mínima por grado según planta vigente.",
    "R2": "Secuencia de grados OPPL y resolución de ascensos top-down con cascada anual.",
    "R4": "Lista 4 produce retiro; lista 3 posterga elegibilidad.",
}

# Decisiones normativas tomadas (ver README §8). Los defaults de
# SimulationPolicy reflejan estas decisiones. Cambiarlos sin justificación
# normativa altera el sentido del modelo.
NORMATIVE_DECISIONS = {
    "fallback_5_1": "Corte estricto de tanda: si una vía no tiene candidato, "
                    "el grado se procesa parcialmente y el resto queda sin proveer.",
    "ttl_vacantes": "Acumulación indefinida: las vacantes no provistas se "
                    "arrastran sin caducidad mientras dure la simulación.",
    "calificacion_faltante": "No elegible por dato faltante: un funcionario "
                             "sin calificación reportada al año t queda postergado, "
                             "no asciende.",
    "salud_impedimento": "Salud no bloquea ascenso: los impedimentos de tipo "
                         "SALUD quedan registrados pero no impiden la promoción "
                         "(ni causan retiro).",
}


@dataclass
class SimulationPolicy:
    mandatory_career_years: int = 30
    health_blocks_promotion: bool = False
    accumulate_unfilled_vacancies: bool = True
    unfilled_vacancy_ttl_years: int | None = None
    enforce_batch_cutoff_on_missing_lane_candidate: bool = True
    allow_lane_fallback: bool = False
    fallback_order: tuple[str, str] = ("merito", "antiguedad")
    event_month_day: tuple[int, int] = (1, 1)
    enable_sobredotacion_absorption: bool = True
    postergacion_conserva_antiguedad: bool = True
    treat_missing_calificacion_as_lista2: bool = False


@dataclass
class MeritPolicy:
    config: dict = field(default_factory=lambda: MERITO_CONFIG_DEFAULT.copy())


@dataclass
class InputPolicy:
    strict_required_files: bool = False
    allow_legacy_compound_fields: bool = True
    min_calificaciones_for_merit: int = 1


@dataclass
class OutputPolicy:
    write_excel: bool = False


@dataclass
class AppConfig:
    policy: SimulationPolicy = field(default_factory=SimulationPolicy)
    merit: MeritPolicy = field(default_factory=MeritPolicy)
    input: InputPolicy = field(default_factory=InputPolicy)
    output: OutputPolicy = field(default_factory=OutputPolicy)
    planta_override: dict[Grado, int] | None = None
