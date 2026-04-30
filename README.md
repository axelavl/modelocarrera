# Sistema de Proyección de Carrera OPPL / PDI

Modelo de proyección OPPL con foco en **auditabilidad**, **configuración explícita** y **validaciones**.

---

## 1) Estructura del proyecto

- `pdi_projection/domain`: entidades, enums, trazas y estado.
- `pdi_projection/config.py`: separación entre reglas duras y supuestos configurables.
- `pdi_projection/data_loader`: carga tabular normalizada + validaciones.
- `pdi_projection/eligibility`: evaluación trazable funcionario-a-funcionario.
- `pdi_projection/promotion_engine`: ranking, selección, asignación y trazas de decisión.
- `pdi_projection/retirement`: retiros con políticas configurables.
- `pdi_projection/ingress`: ingresos y sobredotación configurable.
- `pdi_projection/simulator`: orquestación anual.
- `pdi_projection/outputs`: exportación CSV institucional.

---

## 2) Requisitos

- Python `>=3.11`
- CSV de entrada en formato tabular

`pyproject.toml`:

```toml
[project]
requires-python = ">=3.11"
```

---

## 3) Tutorial paso a paso (ejecución)

### Paso 1 — Crear entorno

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip pytest
```

### Paso 2 — Crear directorios de trabajo

```bash
mkdir -p datos outputs
```

### Paso 3 — Crear archivos de entrada en `datos/`

Archivos esperados por el flujo principal:

- `funcionarios.csv`
- `calificaciones.csv`
- `cursos.csv`
- `impedimentos.csv`
- `planta_vacantes.csv`
- `transitorias.csv`
- `ingresos.csv`
- `ascensos_hist.csv` (opcional, reservado para iteraciones futuras)

### Paso 4 — Crear script `run_model.py`

```python
from pdi_projection.config import AppConfig
from pdi_projection.data_loader import cargar_tabular
from pdi_projection.domain import construir_estado_inicial
from pdi_projection.simulator import simular
from pdi_projection.outputs import exportar_resultados

cfg = AppConfig()
data = cargar_tabular("./datos", cfg)

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

exportar_resultados(logs, data.validation_issues, "./outputs")
print("Ejecución OK. Revisar carpeta outputs/")
```

### Paso 5 — Ejecutar simulación

```bash
python run_model.py
```

### Paso 6 — Verificar resultados

Se generan los siguientes archivos en `outputs/`:

- `funcionarios_evaluados.csv` — traza de elegibilidad por funcionario/año/grado-destino
- `ascensos.csv` — ascensos efectivos
- `retiros.csv` — retiros con causal
- `postergaciones.csv` — elegibles que no fueron ascendidos
- `resultados_proyeccion.csv` — dotación por año y grado (insumo principal de gráficos)
- `indicadores.csv` — vacantes iniciales/finales por grado/año
- `decisiones_promocion.csv` — traza posición a posición del ciclo 5:1
- `ranking.csv` — posición mérito y antigüedad por candidato
- `reporte_validacion.csv` — issues de validación de los CSV de entrada
- `resumen_escenarios.csv` — agregado anual
- `manifest.json` — `AppConfig` usado (reproducibilidad)

### Paso 7 — Ejemplo runnable

Para correr el pipeline con datos de muestra:

```bash
python examples/run_model.py
```

Los CSV de entrada están en `examples/datos/` y los outputs van a `examples/outputs/` (ignorado por git).

---

## 4) Estructura de datos de entrada (plantillas)

### 4.1 `funcionarios.csv`

Columnas requeridas:

```csv
id,fecha_nacimiento,sexo,fecha_ingreso_institucion,fecha_ingreso_grado_actual,grado_actual,antiguedad_escalafon,abono_meses,retiro_voluntario_fecha,retiro_voluntario_causal
```

Ejemplo:

```csv
id,fecha_nacimiento,sexo,fecha_ingreso_institucion,fecha_ingreso_grado_actual,grado_actual,antiguedad_escalafon,abono_meses,retiro_voluntario_fecha,retiro_voluntario_causal
PDI-0001,1985-04-10,M,2010-01-15,2021-01-01,7,1,0,,
PDI-0002,1987-09-01,F,2011-03-01,2022-01-01,7,2,0,,
```

### 4.2 `calificaciones.csv`

```csv
id,año,lista
PDI-0001,2024,1
PDI-0001,2025,2
PDI-0002,2024,2
PDI-0002,2025,1
```

### 4.3 `cursos.csv`

```csv
id,curso_id
PDI-0001,COG
```

### 4.4 `impedimentos.csv`

`tipo`: `SUMARIO`, `SANCION`, `SALUD`.

```csv
id,tipo,fecha_inicio,fecha_fin
PDI-0002,SUMARIO,2026-01-01,2026-12-31
```

### 4.5 `planta_vacantes.csv`

```csv
grado,vacantes_ley,permanencia_min_años
13,300,1
12,1351,3
11,1955,5
9,1609,6
8,711,5
7,321,5
5,59,5
```

### 4.6 `transitorias.csv`

```csv
año,grado,delta
2027,7,100
2027,5,10
```

### 4.7 `ingresos.csv`

```csv
id,fecha_nombramiento,fecha_nacimiento,sexo
PDI-9001,2026-01-01,2001-03-22,M
PDI-9002,2026-01-01,2002-08-10,F
```

### 4.8 `ascensos_hist.csv` (opcional, para backtesting)

Si se proporciona, el sistema permite comparar los ascensos producidos por el modelo
contra el registro histórico real, reportando precision/recall por año y por grado:

```csv
funcionario_id,año,grado_origen,grado_destino,via
PDI-0001,2024,8,7,merito
PDI-0002,2024,7,5,antiguedad
```

`via` es opcional (`merito`, `antiguedad`, o vacío). El módulo
`pdi_projection.reporting.comparar_ascensos` genera el `ResultadoBacktest`.

---

## 5) Reglas normativas duras vs configurables

### Reglas duras

- Secuencia de grados OPPL y cascada top-down anual.
- Permanencia mínima por grado según planta cargada.
- Lista 4 retira y lista 3 posterga.

### Supuestos configurables (`AppConfig`)

| Dial | Default | Decisión normativa (§8) |
|---|---|---|
| `mandatory_career_years` | 30 | — |
| `health_blocks_promotion` | `False` | §8.4 (salud no bloquea) |
| `accumulate_unfilled_vacancies` | `True` | §8.2 (acumulación indefinida) |
| `unfilled_vacancy_ttl_years` | `None` | §8.2 (sin TTL) |
| `enforce_batch_cutoff_on_missing_lane_candidate` | `True` | §8.1 (corte estricto) |
| `allow_lane_fallback` | `False` | §8.1 |
| `treat_missing_calificacion_as_lista2` | `False` | §8.3 (sin calificación posterga) |
| `enable_sobredotacion_absorption` | `True` | — |
| `event_month_day` | `(1, 1)` | — |
| `merit.config` | ver `MERITO_CONFIG_DEFAULT` | — |

---

## 6) Validaciones que realiza el loader

- archivo faltante;
- columnas faltantes;
- RUN/ID duplicado;
- grado inválido;
- fechas inválidas/inconsistentes;
- calificaciones huérfanas;
- curso mal codificado/vacío;
- impedimentos mal estructurados;
- dotación observada superior a planta.

Estas alertas quedan en `reporte_validacion.csv`.

---

## 7) Ejecutar pruebas

```bash
pytest -q
```

---

## 8) Decisiones normativas tomadas

Los cuatro supuestos discutibles del modelo están resueltos. Cada decisión está
expuesta como dial en `AppConfig` para poder revisarse sin tocar código del motor.

### 8.1 Fallback entre vías 5:1 — **Corte estricto**

Si en una posición del ciclo (1-5 mérito, 6 antigüedad) no hay candidato, el
grado se procesa parcialmente y las vacantes restantes quedan sin proveer ese
año. No se sustituye por la otra vía ni se salta la posición.

```python
cfg.policy.enforce_batch_cutoff_on_missing_lane_candidate = True   # default
cfg.policy.allow_lane_fallback = False                              # default
```

### 8.2 TTL de vacantes no provistas — **Acumulación indefinida**

Una vacante creada en `t` que no se cubre se arrastra al pool del año siguiente
hasta que sea provista. No caduca.

```python
cfg.policy.accumulate_unfilled_vacancies = True   # default
cfg.policy.unfilled_vacancy_ttl_years = None      # default (sin TTL)
```

### 8.3 Calificación faltante en año t — **No elegible (postergado)**

Un funcionario sin calificación reportada en el año previo queda postergado por
dato faltante (motivo `sin_calificacion` en `funcionarios_evaluados.csv`). No
asciende hasta que el dato se regularice.

```python
cfg.policy.treat_missing_calificacion_as_lista2 = False   # default
```

### 8.4 Salud como impedimento — **No bloquea ascenso ni causa retiro**

Los impedimentos de tipo `SALUD` quedan registrados en el roster pero no
afectan la elegibilidad ni emiten retiro. Solo `SUMARIO` y `SANCION` siguen
bloqueando ascenso.

```python
cfg.policy.health_blocks_promotion = False   # default
```

> Las decisiones también quedan reflejadas en
> `pdi_projection.config.NORMATIVE_DECISIONS` y se exportan en cada corrida
> como parte de `manifest.json` (reproducibilidad).

---


## 9) Interfaz UI rápida (Streamlit)

Se incluye una interfaz web liviana en `streamlit_app.py` para análisis más amigable.

### Ejecutar UI

```bash
pip install streamlit pandas
streamlit run streamlit_app.py
```

### Qué permite la UI

- cargar CSV de entrada (drag & drop);
- ajustar parámetros de simulación (`AppConfig`) desde barra lateral;
- ejecutar simulación y ver tabla + gráfico de dotación por año/grado;
- revisar validaciones;
- descargar outputs en ZIP.

