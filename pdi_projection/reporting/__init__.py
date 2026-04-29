from .scenarios import ResultadoEscenario, correr_escenario, correr_escenarios
from .cohorts import (
    CohorteCriterio,
    construir_trayectorias,
    distribucion_cohorte_por_año,
    miembros_cohorte,
    resumen_cohorte,
)
from .html_report import generar_informe_html

__all__ = [
    "ResultadoEscenario",
    "correr_escenario",
    "correr_escenarios",
    "CohorteCriterio",
    "construir_trayectorias",
    "distribucion_cohorte_por_año",
    "miembros_cohorte",
    "resumen_cohorte",
    "generar_informe_html",
]
