from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pdi_projection.config import AppConfig
from pdi_projection.domain import (
    Calificacion,
    CausalRetiro,
    Curso,
    Funcionario,
    Grado,
    Impedimento,
    Planta,
    TipoImpedimento,
    ValidationIssue,
)


@dataclass
class TabularInput:
    funcionarios: list[Funcionario]
    ingresos_por_año: dict[int, list[Funcionario]]
    planta: dict[Grado, Planta]
    transitorias: dict[tuple[int, Grado], int]
    validation_issues: list[ValidationIssue]


EXPECTED_COLUMNS: dict[str, set[str]] = {
    "funcionarios": {
        "id",
        "fecha_nacimiento",
        "sexo",
        "fecha_ingreso_institucion",
        "fecha_ingreso_grado_actual",
        "grado_actual",
        "antiguedad_escalafon",
        "abono_meses",
        "retiro_voluntario_fecha",
        "retiro_voluntario_causal",
    },
    "calificaciones": {"id", "año", "lista"},
    "cursos": {"id", "curso_id"},
    "impedimentos": {"id", "tipo", "fecha_inicio", "fecha_fin"},
    "planta_vacantes": {"grado", "vacantes_ley", "permanencia_min_años"},
    "transitorias": {"año", "grado", "delta"},
    "ingresos": {"id", "fecha_nombramiento", "fecha_nacimiento", "sexo"},
}

REQUIRED_FILES: set[str] = {"funcionarios", "planta_vacantes", "ingresos"}


def _must_columns(path: Path, cols: set[str], issues: list[ValidationIssue], strict: bool) -> bool:
    if not path.exists():
        issues.append(ValidationIssue("error", "FILE_MISSING", f"Archivo faltante: {path.name}"))
        return False
    with path.open(newline="", encoding="utf-8") as f:
        got = set(csv.DictReader(f).fieldnames or [])
    missing = cols - got
    if missing:
        sev = "error" if strict else "warning"
        issues.append(ValidationIssue(sev, "MISSING_COLUMNS", f"{path.name} columnas faltantes: {sorted(missing)}"))
    return not missing or not strict


def _parse_date(s: str, issues: list[ValidationIssue], row_ref: str) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        issues.append(ValidationIssue("error", "BAD_DATE", f"Fecha inválida: {s}", row_ref))
        return None


def _parse_grado(s: str, issues: list[ValidationIssue], row_ref: str) -> Grado | None:
    try:
        return Grado(int(s))
    except Exception:
        issues.append(ValidationIssue("error", "BAD_GRADO", f"Grado inválido: {s}", row_ref))
        return None


def cargar_tabular(base_dir: str, cfg: AppConfig | None = None) -> TabularInput:
    cfg = cfg or AppConfig()
    base = Path(base_dir)
    issues: list[ValidationIssue] = []

    files = {
        "funcionarios": base / "funcionarios.csv",
        "calificaciones": base / "calificaciones.csv",
        "cursos": base / "cursos.csv",
        "impedimentos": base / "impedimentos.csv",
        "planta_vacantes": base / "planta_vacantes.csv",
        "transitorias": base / "transitorias.csv",
        "ingresos": base / "ingresos.csv",
    }

    for k, p in files.items():
        if k == "funcionarios":
            _must_columns(p, EXPECTED_COLUMNS[k], issues, strict=True)
        elif k in REQUIRED_FILES:
            _must_columns(p, EXPECTED_COLUMNS[k], issues, strict=cfg.input.strict_required_files)
        elif p.exists() or cfg.input.strict_required_files:
            _must_columns(p, EXPECTED_COLUMNS.get(k, set()), issues, strict=cfg.input.strict_required_files)

    funcionarios_raw = {}
    if files["funcionarios"].exists():
        with files["funcionarios"].open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                rid = row.get("id", "").strip()
                if not rid:
                    issues.append(ValidationIssue("error", "ID_EMPTY", "ID vacío", f"funcionarios:{i}"))
                    continue
                if rid in funcionarios_raw:
                    issues.append(ValidationIssue("error", "ID_DUPLICATE", f"RUN/ID duplicado {rid}", f"funcionarios:{i}"))
                    continue
                grado = _parse_grado(row.get("grado_actual", ""), issues, f"funcionarios:{i}")
                finst = _parse_date(row.get("fecha_ingreso_institucion", ""), issues, f"funcionarios:{i}")
                fgrado = _parse_date(row.get("fecha_ingreso_grado_actual", ""), issues, f"funcionarios:{i}")
                fnac = _parse_date(row.get("fecha_nacimiento", ""), issues, f"funcionarios:{i}")
                if not all([grado, finst, fgrado, fnac]):
                    continue
                if fgrado < finst:
                    issues.append(ValidationIssue("error", "DATE_INCONSISTENT", "ingreso_grado < ingreso_institucion", f"funcionarios:{i}"))
                funcionarios_raw[rid] = {
                    "row": row,
                    "grado": grado,
                    "finst": finst,
                    "fgrado": fgrado,
                    "fnac": fnac,
                    "calificaciones": [],
                    "cursos": set(),
                    "impedimentos": [],
                }

    if files["calificaciones"].exists():
        with files["calificaciones"].open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                rid = row.get("id", "")
                if rid not in funcionarios_raw:
                    issues.append(ValidationIssue("warning", "ORPHAN_CAL", f"Calificación sin funcionario {rid}", f"calificaciones:{i}"))
                    continue
                try:
                    funcionarios_raw[rid]["calificaciones"].append(Calificacion(int(row["año"]), int(row["lista"])))
                except Exception:
                    issues.append(ValidationIssue("error", "BAD_CAL", "Calificación mal formada", f"calificaciones:{i}"))

    if files["cursos"].exists():
        with files["cursos"].open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                rid = row.get("id", "")
                curso_id = row.get("curso_id", "").strip()
                if not curso_id:
                    issues.append(ValidationIssue("error", "BAD_CURSO", "curso_id vacío", f"cursos:{i}"))
                    continue
                if rid in funcionarios_raw:
                    funcionarios_raw[rid]["cursos"].add(curso_id)

    if files["impedimentos"].exists():
        with files["impedimentos"].open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):
                rid = row.get("id", "")
                if rid not in funcionarios_raw:
                    continue
                try:
                    tipo = TipoImpedimento[row["tipo"].upper()]
                except Exception:
                    issues.append(ValidationIssue("error", "BAD_IMPEDIMENTO", f"Tipo inválido {row.get('tipo')}", f"impedimentos:{i}"))
                    continue
                inicio = _parse_date(row.get("fecha_inicio", ""), issues, f"impedimentos:{i}")
                fin = _parse_date(row.get("fecha_fin", ""), issues, f"impedimentos:{i}")
                if not inicio:
                    continue
                if fin and fin < inicio:
                    issues.append(ValidationIssue("error", "BAD_IMPEDIMENTO_DATES", "fin < inicio", f"impedimentos:{i}"))
                    continue
                funcionarios_raw[rid]["impedimentos"].append(Impedimento(tipo, inicio, fin))

    funcionarios = []
    for rid, v in funcionarios_raw.items():
        row = v["row"]
        if len(v["calificaciones"]) < cfg.input.min_calificaciones_for_merit:
            issues.append(ValidationIssue("warning", "LOW_CAL_HISTORY", f"Funcionario {rid} con pocas calificaciones", f"funcionarios:{rid}"))
        causal = row.get("retiro_voluntario_causal")
        retiro_causal = CausalRetiro[causal] if causal else None
        funcionarios.append(
            Funcionario(
                id=rid,
                fecha_nacimiento=v["fnac"],
                sexo=row["sexo"],
                fecha_ingreso_institucion=v["finst"],
                fecha_ingreso_grado_actual=v["fgrado"],
                grado_actual=v["grado"],
                antiguedad_escalafon=int(row["antiguedad_escalafon"]),
                cursos_aprobados=v["cursos"],
                historico_calificaciones=v["calificaciones"],
                abono_meses=int(row.get("abono_meses") or 0),
                impedimentos=v["impedimentos"],
                retiro_voluntario_fecha=_parse_date(row.get("retiro_voluntario_fecha", ""), issues, f"funcionarios:{rid}"),
                retiro_voluntario_causal=retiro_causal,
            )
        )

    planta = {}
    if files["planta_vacantes"].exists():
        with files["planta_vacantes"].open(newline="", encoding="utf-8") as f:
            for i, row in enumerate(csv.DictReader(f), start=2):
                g = _parse_grado(row.get("grado", ""), issues, f"planta:{i}")
                if not g:
                    continue
                planta[g] = Planta(g, int(row.get("vacantes_ley", 0)), int(row.get("permanencia_min_años", 1)))

    transitorias = {}
    if files["transitorias"].exists():
        with files["transitorias"].open(newline="", encoding="utf-8") as f:
            for i, row in enumerate(csv.DictReader(f), start=2):
                g = _parse_grado(row.get("grado", ""), issues, f"transitorias:{i}")
                if not g:
                    continue
                transitorias[(int(row["año"]), g)] = int(row["delta"])

    ingresos: dict[int, list[Funcionario]] = {}
    if files["ingresos"].exists():
        with files["ingresos"].open(newline="", encoding="utf-8") as f:
            for i, row in enumerate(csv.DictReader(f), start=2):
                fecha = _parse_date(row.get("fecha_nombramiento", ""), issues, f"ingresos:{i}")
                if not fecha:
                    continue
                fid = row["id"]
                ingresos.setdefault(fecha.year, []).append(
                    Funcionario(
                        id=fid,
                        fecha_nacimiento=_parse_date(row.get("fecha_nacimiento", ""), issues, f"ingresos:{i}") or date(2000, 1, 1),
                        sexo=row.get("sexo", "X"),
                        fecha_ingreso_institucion=fecha,
                        fecha_ingreso_grado_actual=fecha,
                        grado_actual=Grado.DETECTIVE,
                        antiguedad_escalafon=0,
                        cursos_aprobados=set(),
                        historico_calificaciones=[],
                    )
                )

    # Validación de inconsistencia planta vs dotación
    if planta:
        for g in planta:
            dot = sum(1 for f in funcionarios if f.grado_actual == g)
            if dot > planta[g].vacantes_ley:
                issues.append(ValidationIssue("warning", "DOTACION_SOBRE_PLANTA", f"Dotación {dot} > planta {planta[g].vacantes_ley} en grado {int(g)}"))

    return TabularInput(funcionarios, ingresos, planta, transitorias, issues)


# Compatibilidad legacy
from pdi_projection.domain import EstadoFuncionario


def cargar_dotacion(ruta: str) -> list[Funcionario]:
    issues: list[ValidationIssue] = []
    out = []
    with open(ruta, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(
                Funcionario(
                    id=row["id"],
                    fecha_nacimiento=date.fromisoformat(row["fecha_nacimiento"]),
                    sexo=row["sexo"],
                    fecha_ingreso_institucion=date.fromisoformat(row["fecha_ingreso_institucion"]),
                    fecha_ingreso_grado_actual=date.fromisoformat(row["fecha_ingreso_grado_actual"]),
                    grado_actual=Grado(int(row["grado_actual"])),
                    antiguedad_escalafon=int(row["antiguedad_escalafon"]),
                    cursos_aprobados=set(filter(None, row.get("cursos_aprobados", "").split("|"))),
                    historico_calificaciones=[],
                    abono_meses=int(row.get("abono_meses") or 0),
                    impedimentos=[],
                    estado=EstadoFuncionario.ACTIVO,
                    retiro_voluntario_fecha=_parse_date(row.get("retiro_voluntario_fecha", ""), issues, f"legacy:{row['id']}"),
                    retiro_voluntario_causal=CausalRetiro[row["retiro_voluntario_causal"]] if row.get("retiro_voluntario_causal") else None,
                )
            )
    return out


def cargar_ingresos(ruta: str) -> dict[int, list[Funcionario]]:
    data = cargar_tabular(str(Path(ruta).parent))
    return data.ingresos_por_año


def cargar_transitorias(ruta: str | None) -> dict[tuple[int, Grado], int]:
    if not ruta:
        return {}
    out = {}
    with open(ruta, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[(int(row["año"]), Grado(int(row["grado"])))] = int(row["delta"])
    return out
