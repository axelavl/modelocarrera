"""Ejemplo runnable del pipeline OPPL/PDI.

Carga los CSV de ``examples/datos/``, ejecuta una simulación a 5 años y
exporta los resultados a ``examples/outputs/``. Utilizado también como
smoke-test del pipeline completo.

Uso:
    python examples/run_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Permite ejecutar el ejemplo sin `pip install -e .`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdi_projection.config import AppConfig  # noqa: E402
from pdi_projection.data_loader import cargar_tabular  # noqa: E402
from pdi_projection.domain import construir_estado_inicial  # noqa: E402
from pdi_projection.outputs import exportar_resultados  # noqa: E402
from pdi_projection.simulator import simular  # noqa: E402


def main() -> None:
    base = Path(__file__).resolve().parent
    cfg = AppConfig()
    data = cargar_tabular(str(base / "datos"), cfg)

    estado = construir_estado_inicial(
        data.funcionarios,
        año_base=2026,
        planta=data.planta,
        transitorias=data.transitorias,
    )

    logs = simular(
        estado_inicial=estado,
        año_base=2026,
        horizonte=5,
        ingresos_por_año=data.ingresos_por_año,
        config=cfg,
    )

    outdir = base / "outputs"
    exportar_resultados(logs, data.validation_issues, str(outdir), cfg=cfg)
    print(f"Listo. {len(list(outdir.glob('*')))} archivos generados en {outdir}")


if __name__ == "__main__":
    main()
