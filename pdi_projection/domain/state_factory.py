from __future__ import annotations

from dataclasses import replace

from pdi_projection.domain import CURSOS_OPPL, PLANTA_OPPL_2025, EstadoEscalafon, Grado


def construir_estado_inicial(funcionarios: list, año_base: int, planta=None, transitorias=None, planta_override=None) -> EstadoEscalafon:
    fuente = planta or PLANTA_OPPL_2025
    base_planta = {g: replace(p) for g, p in fuente.items()}
    if planta_override:
        for g, vac in planta_override.items():
            base_planta[g].vacantes_ley = vac
    transitorias = transitorias or {}
    grados = list(base_planta.keys())
    return EstadoEscalafon(
        año_actual=año_base,
        funcionarios={f.id: f for f in funcionarios},
        planta=base_planta,
        transitorias=transitorias,
        vacantes_no_provistas={g: 0 for g in grados},
        cycle_counter={g: 0 for g in grados if g != Grado.DETECTIVE},
        cursos=CURSOS_OPPL.copy(),
        vacancy_age={g: 0 for g in grados},
    )
