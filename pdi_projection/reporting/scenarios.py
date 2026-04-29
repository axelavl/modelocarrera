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
