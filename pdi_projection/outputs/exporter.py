from __future__ import annotations

import csv
from pathlib import Path

from pdi_projection.domain import TipoEvento


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def exportar_resultados(logs, validation_issues: list, outdir: str) -> None:
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
            "cumple_tiempo": t.cumple_tiempo,
            "cumple_curso": t.cumple_curso,
            "elegible": t.elegible,
            "estado": t.estado.value,
            "motivo": t.motivo,
        }
        for t in logs.elegibilidad_trazas
    ]
    _write_csv(base / "funcionarios_evaluados.csv", evaluados, list(evaluados[0].keys()) if evaluados else ["funcionario_id"])

    asc = [
        {"funcionario_id": e.funcionario_id, "año": e.año, "origen": int(e.grado_origen), "destino": int(e.grado_destino), "via": e.via.value if e.via else "", "motivo": e.motivo or ""}
        for e in all_events
        if e.tipo == TipoEvento.ASCENSO
    ]
    _write_csv(base / "ascensos.csv", asc, list(asc[0].keys()) if asc else ["funcionario_id"])

    retiros = [
        {"funcionario_id": e.funcionario_id, "año": e.año, "grado": int(e.grado_origen), "causal": e.causal.value if e.causal else ""}
        for e in all_events
        if e.tipo == TipoEvento.RETIRO
    ]
    _write_csv(base / "retiros.csv", retiros, list(retiros[0].keys()) if retiros else ["funcionario_id"])

    post = [
        {"funcionario_id": e.funcionario_id, "año": e.año, "origen": int(e.grado_origen), "destino": int(e.grado_destino), "motivo": e.motivo or ""}
        for e in all_events
        if e.tipo == TipoEvento.POSTERGACION_VACANTE
    ]
    _write_csv(base / "postergaciones.csv", post, list(post[0].keys()) if post else ["funcionario_id"])

    resultados = []
    for año, snapshot in sorted(logs.snapshots.items()):
        for grado, dot in snapshot.items():
            resultados.append({"año": año, "grado": int(grado), "dotacion": dot})
    _write_csv(base / "resultados_proyeccion.csv", resultados, list(resultados[0].keys()) if resultados else ["año", "grado", "dotacion"])

    indicadores = []
    for d in logs.decision_trazas:
        indicadores.append({"año": d.año, "grado_destino": int(d.grado_destino), "vacantes_iniciales": d.vacantes_iniciales, "vacantes_finales": d.vacantes_finales})
    _write_csv(base / "indicadores.csv", indicadores, list(indicadores[0].keys()) if indicadores else ["año"])

    val = [{"severity": i.severity, "code": i.code, "message": i.message, "row_ref": i.row_ref or ""} for i in validation_issues]
    _write_csv(base / "reporte_validacion.csv", val, list(val[0].keys()) if val else ["severity"])

    resumen = []
    by_year = sorted(logs.snapshots.keys())
    for y in by_year:
        resumen.append({"escenario": "base", "año": y, "total_activos": sum(logs.snapshots[y].values())})
    _write_csv(base / "resumen_escenarios.csv", resumen, list(resumen[0].keys()) if resumen else ["escenario", "año", "total_activos"])
