# Sistema de Proyección de Carrera OPPL / PDI

Refactor incremental del modelo de proyección OPPL con foco en **auditabilidad**, **configuración explícita** y **validaciones**.

## Estructura

- `pdi_projection/domain`: entidades, enums, trazas y estado.
- `pdi_projection/config.py`: separación entre reglas duras y supuestos configurables.
- `pdi_projection/data_loader`: carga tabular normalizada + validaciones.
- `pdi_projection/eligibility`: evaluación trazable funcionario-a-funcionario.
- `pdi_projection/promotion_engine`: ranking, selección, asignación y trazas de decisión.
- `pdi_projection/retirement`: retiros con políticas configurables.
- `pdi_projection/ingress`: ingresos y sobredotación configurable.
- `pdi_projection/simulator`: orquestación anual.
- `pdi_projection/outputs`: exportación CSV institucional.

## Entradas esperadas (preferidas)

Directorio tabular con archivos:

- `funcionarios.csv`
- `calificaciones.csv`
- `cursos.csv`
- `impedimentos.csv`
- `ascensos_hist.csv` (opcional para futuras iteraciones)
- `planta_vacantes.csv`
- `transitorias.csv`
- `ingresos.csv`

Se mantiene compatibilidad parcial con cargas legacy compuestas.

## Reglas normativas duras vs configurables

### Duras
- Secuencia de grados OPPL y cascada top-down anual.
- Permanencia mínima por grado definida en planta.
- Lista 4 retira y lista 3 posterga.

### Configurables (`AppConfig`)
- Años de retiro obligatorio (`mandatory_career_years`).
- Salud como impedimento (`health_blocks_promotion`).
- Acumulación y vencimiento de vacantes no provistas (`accumulate_unfilled_vacancies`, `unfilled_vacancy_ttl_years`).
- Corte de tanda y fallback de vía 5:1 (`enforce_batch_cutoff_on_missing_lane_candidate`, `allow_lane_fallback`).
- Fórmula de mérito (`merit.config`).
- Sobredotación y absorción en ingresos (`enable_sobredotacion_absorption`).
- Momento del año de eventos (`event_month_day`).
- Supuestos por falta de calificación (`treat_missing_calificacion_as_lista2`).

## Ejecución

```python
from pdi_projection.config import AppConfig
from pdi_projection.data_loader import cargar_tabular
from pdi_projection.domain import construir_estado_inicial
from pdi_projection.simulator import simular
from pdi_projection.outputs import exportar_resultados

cfg = AppConfig()
data = cargar_tabular("./datos", cfg)
estado = construir_estado_inicial(data.funcionarios, 2026, planta=data.planta, transitorias=data.transitorias)
logs = simular(estado, año_base=2026, horizonte=5, ingresos_por_año=data.ingresos_por_año, config=cfg)
exportar_resultados(logs, data.validation_issues, "./outputs")
```

## Outputs mínimos

- `funcionarios_evaluados.csv`
- `ascensos.csv`
- `retiros.csv`
- `postergaciones.csv`
- `resultados_proyeccion.csv`
- `indicadores.csv`
- `reporte_validacion.csv`
- `resumen_escenarios.csv`

## Supuestos pendientes por validar

- Formalización jurídica exacta de fallback entre vías 5:1.
- Regla oficial para caducidad (o no) de vacantes no provistas.
- Tratamiento definitivo de calificaciones faltantes en año t.
- Alcance normativo de salud como impedimento temporal/permanente.
