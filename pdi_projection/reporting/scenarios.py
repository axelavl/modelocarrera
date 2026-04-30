from __future__ import annotations

import copy
from dataclasses import dataclass

from pdi_projection.config import AppConfig
from pdi_projection.domain import EstadoEscalafon, Funcionario, construir_estado_inicial
from pdi_projection.logs import LogsRegistry
from pdi_projection.simulator import simular


@dataclass
class ResultadoEscenario:
    nombre: str
    config: AppConfig
    logs: LogsRegistry
    estado_final: EstadoEscalafon
    funcionarios_iniciales: dict[str, Funcionario]


def correr_escenario(
    nombre: str,
    config: AppConfig,
    funcionarios: list[Funcionario],
    año_base: int,
    horizonte: int,
    planta: dict | None,
    transitorias: dict | None,
    ingresos_por_año: dict[int, list[Funcionario]],
) -> ResultadoEscenario:
    """Ejecuta una corrida aislada — copia profunda de los inputs para no contaminar otros escenarios."""
    funcs_copy = copy.deepcopy(funcionarios)
    ingresos_copy = copy.deepcopy(ingresos_por_año or {})
    estado = construir_estado_inicial(
        funcs_copy,
        año_base=año_base,
        planta=planta,
        transitorias=transitorias,
    )
    funcs_iniciales = copy.deepcopy(estado.funcionarios)
    logs = simular(
        estado_inicial=estado,
        año_base=año_base,
        horizonte=horizonte,
        ingresos_por_año=ingresos_copy,
        config=config,
    )
    return ResultadoEscenario(
        nombre=nombre,
        config=config,
        logs=logs,
        estado_final=estado,
        funcionarios_iniciales=funcs_iniciales,
    )


def correr_escenarios(
    escenarios: list[tuple[str, AppConfig]],
    funcionarios: list[Funcionario],
    año_base: int,
    horizonte: int,
    planta: dict | None,
    transitorias: dict | None,
    ingresos_por_año: dict[int, list[Funcionario]],
) -> list[ResultadoEscenario]:
    return [
        correr_escenario(nombre, cfg, funcionarios, año_base, horizonte, planta, transitorias, ingresos_por_año)
        for nombre, cfg in escenarios
    ]


def barrer_parametro(
    nombre_parametro: str,
    valores: list,
    base_config: AppConfig,
    funcionarios: list[Funcionario],
    año_base: int,
    horizonte: int,
    planta: dict | None,
    transitorias: dict | None,
    ingresos_por_año: dict[int, list[Funcionario]],
) -> list[ResultadoEscenario]:
    """Análisis de sensibilidad: corre N escenarios variando un único atributo
    de ``base_config.policy``, dejando todo lo demás constante.

    Útil para responder preguntas como "¿qué pasa si la carrera obligatoria fuera
    de 28, 29, 30, 31 o 32 años?". Devuelve una lista de ``ResultadoEscenario``
    compatible con ``html_report.generar_informe_comparativo_html`` y los
    helpers de comparación del Streamlit.
    """
    if not hasattr(base_config.policy, nombre_parametro):
        raise ValueError(
            f"'{nombre_parametro}' no es un atributo de SimulationPolicy. "
            f"Atributos disponibles: {sorted(vars(base_config.policy).keys())}"
        )
    escenarios: list[tuple[str, AppConfig]] = []
    for valor in valores:
        cfg = copy.deepcopy(base_config)
        setattr(cfg.policy, nombre_parametro, valor)
        escenarios.append((f"{nombre_parametro}={valor}", cfg))
    return correr_escenarios(
        escenarios, funcionarios, año_base, horizonte, planta, transitorias, ingresos_por_año
    )
