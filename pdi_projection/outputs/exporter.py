from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

from pdi_projection.domain import TipoEvento


EVALUADOS_FIELDS = [
    "funcionario_id",
    "año",
    "grado_origen",
    "grado_destino",
    "cumple_lista",
    "lista_valor",
    "cumple_impedimento",
    "impedimento_activo",
    "cumple_tiempo",
    "tiempo_en_grado",
    "cumple_curso",
    "elegible",
    "estado",
    "motivo",
]
ASCENSOS_FIELDS = ["funcionario_id", "año", "origen", "destino", "via", "motivo"]
RETIROS_FIELDS = ["funcionario_id", "año", "grado", "causal"]
POSTERGACIONES_FIELDS = ["funcionario_id", "año", "origen", "destino", "motivo"]
RESULTADOS_FIELDS = ["año", "grado", "dotacion"]
INDICADORES_FIELDS = ["año", "grado_destino", "vacantes_iniciales", "vacantes_finales"]
VALIDACION_FIELDS = ["severity", "code", "message", "row_ref"]
RESUMEN_FIELDS = ["escenario", "año", "total_activos"]
DECISIONES_FIELDS = [
    "año",
    "grado_destino",
    "grado_origen",
    "vacantes_iniciales",
    "vacantes_finales",
    "cycle_counter_inicial",
    "cycle_counter_final",
    "pos",
    "funcionario",
    "via",
    "resultado",
]
RANKING_FIELDS = [
    "año",
    "funcionario_id",
    "grado_destino",
    "puntaje_merito",
    "ranking_merito",
    "ranking_antiguedad",
]


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _json_default(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "value"):
        return obj.value
    return str(obj)


def exportar_resultados(logs, validation_issues: list, outdir: str, cfg=None) -> None:
    base = Path(outdir)
    all_events = [e for y in logs.eventos_por_año.values() for e in y]

    evaluados = [
        {
            "funcionario_id": t.funcionario_id,
            "año": t.año,
            "grado_origen": int(t.grado_origen),
            "grado_destino": int(t.grado_destino),
            "cumple_lista": t.cumple_lista,
            "lista_valor": t.lista_valor,
            "cumple_impedimento": t.cumple_impedimento,
            "impedimento_activo": t.impedimento_activo or "",
            "cumple_tiempo": t.cumple_tiempo,
            "tiempo_en_grado": t.tiempo_en_grado,
            "cumple_curso": t.cumple_curso,
            "elegible": t.elegible,
            "estado": t.estado.value,
            "motivo": t.motivo,
        }
        for t in logs.elegibilidad_trazas
    ]
    _write_csv(base / "funcionarios_evaluados.csv", evaluados, EVALUADOS_FIELDS)

    asc = [
        {
            "funcionario_id": e.funcionario_id,
            "año": e.año,
            "origen": int(e.grado_origen) if e.grado_origen is not None else "",
            "destino": int(e.grado_destino) if e.grado_destino is not None else "",
            "via": e.via.value if e.via else "",
            "motivo": e.motivo or "",
        }
        for e in all_events
        if e.tipo == TipoEvento.ASCENSO
    ]
    _write_csv(base / "ascensos.csv", asc, ASCENSOS_FIELDS)

    retiros = [
        {
            "funcionario_id": e.funcionario_id,
            "año": e.año,
            "grado": int(e.grado_origen) if e.grado_origen is not None else "",
            "causal": e.causal.value if e.causal else "",
        }
        for e in all_events
        if e.tipo == TipoEvento.RETIRO
    ]
    _write_csv(base / "retiros.csv", retiros, RETIROS_FIELDS)

    post = [
        {
            "funcionario_id": e.funcionario_id,
            "año": e.año,
            "origen": int(e.grado_origen) if e.grado_origen is not None else "",
            "destino": int(e.grado_destino) if e.grado_destino is not None else "",
            "motivo": e.motivo or "",
        }
        for e in all_events
        if e.tipo == TipoEvento.POSTERGACION_VACANTE
    ]
    _write_csv(base / "postergaciones.csv", post, POSTERGACIONES_FIELDS)

    resultados = []
    for año, snapshot in sorted(logs.snapshots.items()):
        for grado, dot in snapshot.items():
            resultados.append({"año": año, "grado": int(grado), "dotacion": dot})
    _write_csv(base / "resultados_proyeccion.csv", resultados, RESULTADOS_FIELDS)

    indicadores = [
        {
            "año": d.año,
            "grado_destino": int(d.grado_destino),
            "vacantes_iniciales": d.vacantes_iniciales,
            "vacantes_finales": d.vacantes_finales,
        }
        for d in logs.decision_trazas
    ]
    _write_csv(base / "indicadores.csv", indicadores, INDICADORES_FIELDS)

    val = [
        {"severity": i.severity, "code": i.code, "message": i.message, "row_ref": i.row_ref or ""}
        for i in validation_issues
    ]
    _write_csv(base / "reporte_validacion.csv", val, VALIDACION_FIELDS)

    resumen = []
    for y in sorted(logs.snapshots.keys()):
        resumen.append({"escenario": "base", "año": y, "total_activos": sum(logs.snapshots[y].values())})
    _write_csv(base / "resumen_escenarios.csv", resumen, RESUMEN_FIELDS)

    decisiones = []
    for d in logs.decision_trazas:
        if not d.decisiones:
            decisiones.append(
                {
                    "año": d.año,
                    "grado_destino": int(d.grado_destino),
                    "grado_origen": int(d.grado_origen),
                    "vacantes_iniciales": d.vacantes_iniciales,
                    "vacantes_finales": d.vacantes_finales,
                    "cycle_counter_inicial": d.cycle_counter_inicial,
                    "cycle_counter_final": d.cycle_counter_final,
                    "pos": "",
                    "funcionario": "",
                    "via": "",
                    "resultado": "",
                }
            )
            continue
        for item in d.decisiones:
            decisiones.append(
                {
                    "año": d.año,
                    "grado_destino": int(d.grado_destino),
                    "grado_origen": int(d.grado_origen),
                    "vacantes_iniciales": d.vacantes_iniciales,
                    "vacantes_finales": d.vacantes_finales,
                    "cycle_counter_inicial": d.cycle_counter_inicial,
                    "cycle_counter_final": d.cycle_counter_final,
                    "pos": item.get("pos", ""),
                    "funcionario": item.get("funcionario", ""),
                    "via": item.get("via", ""),
                    "resultado": item.get("resultado", ""),
                }
            )
    _write_csv(base / "decisiones_promocion.csv", decisiones, DECISIONES_FIELDS)

    ranking = [
        {
            "año": getattr(r, "año", ""),
            "funcionario_id": r.funcionario_id,
            "grado_destino": int(r.grado_destino),
            "puntaje_merito": r.puntaje_merito,
            "ranking_merito": r.ranking_merito,
            "ranking_antiguedad": r.ranking_antiguedad,
        }
        for r in logs.ranking_trazas
    ]
    _write_csv(base / "ranking.csv", ranking, RANKING_FIELDS)

    if cfg is not None:
        manifest = {"config": asdict(cfg) if is_dataclass(cfg) else cfg}
        (base / "manifest.json").parent.mkdir(parents=True, exist_ok=True)
        (base / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, default=_json_default),
            encoding="utf-8",
        )
