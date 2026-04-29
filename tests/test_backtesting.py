from pathlib import Path

from pdi_projection.config import AppConfig
from pdi_projection.data_loader import cargar_tabular
from pdi_projection.domain import AscensoHistorico, EventoCarrera, Grado, TipoEvento, Via
from pdi_projection.reporting import comparar_ascensos, metricas_por_grado_destino


def _ev(fid, año, gd, go=Grado.SUBPREFECTO, via=Via.MERITO):
    return EventoCarrera(funcionario_id=fid, año=año, tipo=TipoEvento.ASCENSO,
                         grado_origen=go, grado_destino=gd, via=via)


def _hist(fid, año, gd, go=Grado.SUBPREFECTO, via=Via.MERITO):
    return AscensoHistorico(funcionario_id=fid, año=año, grado_origen=go, grado_destino=gd, via=via)


def test_match_perfecto_da_precision_y_recall_uno():
    sim = [_ev("a", 2024, Grado.PREFECTO), _ev("b", 2025, Grado.PREFECTO)]
    hist = [_hist("a", 2024, Grado.PREFECTO), _hist("b", 2025, Grado.PREFECTO)]
    r = comparar_ascensos(sim, hist)
    assert len(r.matches) == 2
    assert not r.falsos_positivos
    assert not r.falsos_negativos
    assert r.metricas_globales["precision"] == 1.0
    assert r.metricas_globales["recall"] == 1.0
    assert r.metricas_globales["f1"] == 1.0


def test_falso_positivo_y_falso_negativo_se_separan():
    sim = [_ev("a", 2024, Grado.PREFECTO), _ev("c", 2024, Grado.PREFECTO)]
    hist = [_hist("a", 2024, Grado.PREFECTO), _hist("b", 2024, Grado.PREFECTO)]
    r = comparar_ascensos(sim, hist)
    assert len(r.matches) == 1
    assert r.falsos_positivos == [("c", 2024, Grado.PREFECTO)]
    assert r.falsos_negativos == [("b", 2024, Grado.PREFECTO)]
    assert r.metricas_globales["precision"] == 0.5
    assert r.metricas_globales["recall"] == 0.5


def test_via_mismatch_no_es_falso_positivo_pero_se_reporta():
    sim = [_ev("a", 2024, Grado.PREFECTO, via=Via.MERITO)]
    hist = [_hist("a", 2024, Grado.PREFECTO, via=Via.ANTIGUEDAD)]
    r = comparar_ascensos(sim, hist)
    assert len(r.matches) == 1
    assert not r.falsos_positivos
    assert r.via_mismatches == [("a", 2024, Grado.PREFECTO, Via.MERITO, Via.ANTIGUEDAD)]


def test_via_no_informada_en_historico_no_genera_mismatch():
    sim = [_ev("a", 2024, Grado.PREFECTO, via=Via.MERITO)]
    hist = [_hist("a", 2024, Grado.PREFECTO, via=None)]
    r = comparar_ascensos(sim, hist)
    assert len(r.matches) == 1
    assert not r.via_mismatches


def test_filtro_de_rango_de_años():
    sim = [_ev("a", 2024, Grado.PREFECTO), _ev("b", 2026, Grado.PREFECTO)]
    hist = [_hist("a", 2024, Grado.PREFECTO), _hist("b", 2026, Grado.PREFECTO)]
    r = comparar_ascensos(sim, hist, año_desde=2025, año_hasta=2026)
    keys = {(m[0], m[1]) for m in r.matches}
    assert keys == {("b", 2026)}


def test_metricas_por_año_y_por_grado():
    sim = [_ev("a", 2024, Grado.PREFECTO), _ev("b", 2025, Grado.SUBPREFECTO)]
    hist = [_hist("a", 2024, Grado.PREFECTO), _hist("c", 2025, Grado.SUBPREFECTO)]
    r = comparar_ascensos(sim, hist)
    assert 2024 in r.metricas_por_año
    assert r.metricas_por_año[2024]["precision"] == 1.0
    assert r.metricas_por_año[2025]["matches"] == 0
    pg = metricas_por_grado_destino(r)
    assert pg[Grado.PREFECTO]["matches"] == 1
    assert pg[Grado.SUBPREFECTO]["falsos_positivos"] == 1


def test_ignora_eventos_no_ascenso():
    sim = [
        _ev("a", 2024, Grado.PREFECTO),
        EventoCarrera(funcionario_id="x", año=2024, tipo=TipoEvento.RETIRO, grado_origen=Grado.COMISARIO),
    ]
    hist = [_hist("a", 2024, Grado.PREFECTO)]
    r = comparar_ascensos(sim, hist)
    assert len(r.matches) == 1
    assert not r.falsos_positivos


def test_loader_lee_ascensos_hist(tmp_path: Path):
    (tmp_path / "funcionarios.csv").write_text(
        "id,fecha_nacimiento,sexo,fecha_ingreso_institucion,fecha_ingreso_grado_actual,grado_actual,"
        "antiguedad_escalafon,abono_meses,retiro_voluntario_fecha,retiro_voluntario_causal\n"
        "1,1985-01-01,M,2010-01-01,2018-01-01,7,1,0,,\n",
        encoding="utf-8",
    )
    (tmp_path / "planta_vacantes.csv").write_text("grado,vacantes_ley,permanencia_min_años\n5,1,5\n", encoding="utf-8")
    (tmp_path / "ingresos.csv").write_text("id,fecha_nombramiento,fecha_nacimiento,sexo\n", encoding="utf-8")
    (tmp_path / "ascensos_hist.csv").write_text(
        "funcionario_id,año,grado_origen,grado_destino,via\n"
        "1,2024,7,5,merito\n"
        "9,2024,7,5,antiguedad\n",
        encoding="utf-8",
    )
    data = cargar_tabular(str(tmp_path), AppConfig())
    assert len(data.ascensos_hist) == 2
    assert data.ascensos_hist[0].funcionario_id == "1"
    assert data.ascensos_hist[0].grado_destino == Grado.PREFECTO
    assert data.ascensos_hist[0].via == Via.MERITO
    # huérfano (id no está en funcionarios) emite warning pero igual se lee
    assert any(i.code == "ASCENSO_HIST_HUERFANO" for i in data.validation_issues)
