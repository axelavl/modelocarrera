# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (Python >=3.11 required)
python -m venv .venv && source .venv/bin/activate
pip install -e .                 # installs pdi-projection + pandas + streamlit

# Run the test suite
pytest -q
pytest tests/test_oppl_rules.py::test_ciclo_5_1_respeta_proporción_en_ejecuciones_largas   # single test

# Run the Streamlit UI (alternative entry point to the simulator)
streamlit run streamlit_app.py
```

There is no batch CLI; the canonical programmatic entry point is shown in `README.md` §3.4 (a one-off `run_model.py` calling `cargar_tabular` → `construir_estado_inicial` → `simular` → `exportar_resultados`). The Streamlit app wires the same pipeline behind a UI.

`pyproject.toml` sets `pythonpath = ["."]` for pytest, so tests import `pdi_projection.*` directly without installation.

## Architecture

This is an annual simulator for the Chilean PDI's OPPL career-progression rules. The codebase is organized around **traceability**: every decision (eligibility check, ranking position, promotion outcome, validation issue) is recorded as a structured trace and exported to CSV.

### Pipeline

`pdi_projection.simulator.run.simular` is the single orchestrator. For each year `t` in `[año_base, año_base + horizonte]` it runs phases **in this fixed order**, mutating `EstadoEscalafon` in place:

1. `retirement.procesar_retiros` — voluntary, lista-4, and 30-year-career retirements
2. `ingress.procesar_ingresos` — admits new DETECTIVES up to DTV vacancies + (optional) absorption capacity from higher grades
3. `promotion_engine.ejecutar_ascensos` — cascading top-down promotions
4. `LogsRegistry.snapshot` — records dotación per grade

Reordering these phases breaks the cascade (retirements must free vacancies before promotions compute them).

### Domain model (`pdi_projection/domain/models.py`)

- `Grado` is an `IntEnum` where **lower integer = higher rank** (PREFECTO=5 is the top, DETECTIVE=13 is entry). `SECUENCIA_OPPL` is ordered from low rank to high rank, so `grado_siguiente` walks toward higher rank. Don't sort `Grado` numerically expecting hierarchical order.
- `EstadoEscalafon` is the mutable in-memory state passed through the pipeline. Key fields: `funcionarios` (dict by id), `planta` (vacancies-by-law per grade), `transitorias` (year/grade overrides), `vacantes_no_provistas` (carried-over unfilled slots), `cycle_counter` (per-grade 5:1 mérito/antigüedad rotation index), `vacancy_age` (TTL clock).
- Trace dataclasses: `EligibilityTrace`, `RankingTrace`, `PromotionDecisionTrace`, `ValidationIssue`, `EventoCarrera`. These are the canonical outputs — exporters read from them, not from the engine.

### Promotion engine (the core algorithm)

`promotion_engine.engine.ejecutar_ascensos` walks `[PREFECTO, SUBPREFECTO, COMISARIO, SUBCOMISARIO, INSPECTOR, SUBINSPECTOR]` (top-down) so that promoting a SUBPREFECTO into a PREFECTO vacancy frees a SUBPREFECTO slot before COMISARIO promotions are computed.

For each target grade:
1. `calcular_vacantes` = `planta_ley + transitoria - dotacion_actual + vacantes_no_provistas` (the last term is gated by `accumulate_unfilled_vacancies`).
2. `get_elegibles` filters `grado_origen` actives through `evaluar_elegibilidad` (lista → impedimento → permanencia → curso, in that short-circuit order).
3. **5:1 lane rotation**: `seleccionar_candidato` uses `pos = cycle_counter + 1`; `pos <= 5` picks from the mérito list, `pos == 6` picks from the antigüedad list. Counter advances as `pos % 6` after every selection.
4. If a lane has no candidate and `enforce_batch_cutoff_on_missing_lane_candidate` is true (the default — rule R12), the entire batch for that grade stops. Set `allow_lane_fallback=True` to swap to the other lane instead.
5. Unfilled vacancies feed `vacantes_no_provistas` (capped by `unfilled_vacancy_ttl_years` if set).

When extending the engine, preserve the trace contract: every elegible must produce one `EligibilityTrace`, every batch must produce one `PromotionDecisionTrace` containing per-position `decisiones`, and every elegible-not-promoted must produce a `POSTERGACION_VACANTE` event.

### Configuration boundary

`pdi_projection/config.py` defines the **only** sanctioned dial. Hard normative rules (`NORMATIVE_HARD_RULES` R1/R2/R4) are baked into engine code and must NOT be made configurable without explicit instruction. The four discretionary supuestos that the model must answer are resolved in `NORMATIVE_DECISIONS` (see `README.md` §8) and exposed as defaults of `SimulationPolicy`:

- §8.1 Fallback 5:1 → corte estricto (`enforce_batch_cutoff_on_missing_lane_candidate=True`, `allow_lane_fallback=False`)
- §8.2 TTL vacantes → acumulación indefinida (`accumulate_unfilled_vacancies=True`, `unfilled_vacancy_ttl_years=None`)
- §8.3 Calificación faltante → no elegible (`treat_missing_calificacion_as_lista2=False`)
- §8.4 Salud → no bloquea ni retira (`health_blocks_promotion=False`)

Soft assumptions live in `SimulationPolicy`, `MeritPolicy.config`, `InputPolicy`, `OutputPolicy`. When adding new behaviour that affects outcomes, expose it via `AppConfig` rather than hardcoding it. Each run's full config is exported to `manifest.json` for reproducibility.

### Data loading and validation

`data_loader.csv_loader.cargar_tabular` returns a `TabularInput` with `validation_issues: list[ValidationIssue]`. The loader is **lenient** by default: missing optional files and malformed rows produce issues but don't abort. Always pass `validation_issues` through to `exportar_resultados` so they reach `reporte_validacion.csv`.

Required files: `funcionarios.csv`, `planta_vacantes.csv`, `ingresos.csv`. Optional: `calificaciones.csv`, `cursos.csv`, `impedimentos.csv`, `transitorias.csv`. Schemas are in `README.md` §4.

The legacy helpers at the bottom of `csv_loader.py` (`cargar_dotacion`, `cargar_ingresos`, `cargar_transitorias`) exist for backwards compatibility — prefer `cargar_tabular` for all new code.

### Conventions

- Domain identifiers, enums, file names, and validation messages are in **Spanish** (`Funcionario`, `EstadoEscalafon`, `procesar_ascensos`); type infrastructure (`AppConfig`, `IntEnum`, `dataclass`) is in **English**. Match the existing language when naming.
- Mutate `EstadoEscalafon` in place; do not return new state objects from the phase functions — `simular` and the registry assume the same instance flows through.
- Tests use the `mk_func` factory in `tests/test_oppl_rules.py` to construct `Funcionario` fixtures with sensible defaults; reuse it when adding tests.

### Reporting layer (`pdi_projection/reporting`)

Higher-level analyses that compose the simulator's outputs without modifying the engine:

- `scenarios.correr_escenarios([(nombre, AppConfig), ...], ...)` runs N isolated simulations from the same input data. Inputs (`funcionarios`, `ingresos_por_año`) are deep-copied per scenario because the simulator mutates `Funcionario` in place — sharing references would cross-contaminate runs.
- `scenarios.barrer_parametro(...)` automates a sensitivity sweep over a single `SimulationPolicy` field; returns the same `ResultadoEscenario` list as `correr_escenarios` for charting.
- `cohorts.construir_trayectorias(logs, funcionarios_iniciales, año_base)` reconstructs each funcionario's grade and status year by year by replaying events from the log. Used to compute cohort distributions (`miembros_cohorte` + `distribucion_cohorte_por_año` + `resumen_cohorte`).
- `backtesting.comparar_ascensos(eventos_simulados, ascensos_historicos, ...)` produces a `ResultadoBacktest` with precision/recall/F1 globally, by year and by grade. Loaded automatically when `ascensos_hist.csv` is present in the input directory.
- `html_report.generar_informe_html(...)` and `html_report.generar_informe_comparativo_html(...)` produce self-contained HTML (Vega-Lite charts hydrated from CDN, KPIs, validation tables) that can be printed to PDF from any browser. No headless rendering deps required.

The Streamlit app (`streamlit_app.py`) wires both modes — single simulation and scenario comparator — over the reporting layer. It also surfaces tabs for traceability (per-funcionario eligibility + ranking history), cohorts, validation issues and (when `ascensos_hist.csv` is uploaded) backtesting.
