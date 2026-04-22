from pathlib import Path

from pdi_projection.config import AppConfig
from pdi_projection.data_loader import cargar_tabular
from pdi_projection.domain import Grado
from pdi_projection.domain.state_factory import construir_estado_inicial
from pdi_projection.outputs import exportar_resultados
from pdi_projection.simulator import simular


def write(p: Path, text: str):
    p.write_text(text, encoding="utf-8")


def test_cargar_tabular_detecta_duplicado_y_exporta_outputs(tmp_path: Path):
    write(
        tmp_path / "funcionarios.csv",
        "id,fecha_nacimiento,sexo,fecha_ingreso_institucion,fecha_ingreso_grado_actual,grado_actual,antiguedad_escalafon,abono_meses,retiro_voluntario_fecha,retiro_voluntario_causal\n"
        "1,1980-01-01,M,2010-01-01,2015-01-01,7,1,0,,\n"
        "1,1981-01-01,F,2011-01-01,2016-01-01,7,2,0,,\n",
    )
    write(tmp_path / "calificaciones.csv", "id,año,lista\n1,2025,1\n")
    write(tmp_path / "cursos.csv", "id,curso_id\n1,COG\n")
    write(tmp_path / "impedimentos.csv", "id,tipo,fecha_inicio,fecha_fin\n")
    write(tmp_path / "planta_vacantes.csv", "grado,vacantes_ley,permanencia_min_años\n5,1,5\n7,1,5\n13,1,1\n12,1,3\n11,1,5\n9,1,6\n8,1,5\n")
    write(tmp_path / "transitorias.csv", "año,grado,delta\n")
    write(tmp_path / "ingresos.csv", "id,fecha_nombramiento,fecha_nacimiento,sexo\nX,2026-01-01,2000-01-01,M\n")

    data = cargar_tabular(str(tmp_path), AppConfig())
    assert any(i.code == "ID_DUPLICATE" for i in data.validation_issues)

    estado = construir_estado_inicial(data.funcionarios, 2026, planta=data.planta, transitorias=data.transitorias)
    logs = simular(estado, 2026, 0, data.ingresos_por_año, AppConfig())
    export_dir = tmp_path / "out"
    exportar_resultados(logs, data.validation_issues, str(export_dir))
    expected = {
        "funcionarios_evaluados.csv",
        "ascensos.csv",
        "retiros.csv",
        "postergaciones.csv",
        "resultados_proyeccion.csv",
        "indicadores.csv",
        "reporte_validacion.csv",
        "resumen_escenarios.csv",
    }
    assert expected.issubset({p.name for p in export_dir.iterdir()})


def test_transitorias_tabulares_se_cargan(tmp_path: Path):
    write(
        tmp_path / "funcionarios.csv",
        "id,fecha_nacimiento,sexo,fecha_ingreso_institucion,fecha_ingreso_grado_actual,grado_actual,antiguedad_escalafon,abono_meses,retiro_voluntario_fecha,retiro_voluntario_causal\n",
    )
    write(tmp_path / "planta_vacantes.csv", "grado,vacantes_ley,permanencia_min_años\n5,0,5\n")
    write(tmp_path / "ingresos.csv", "id,fecha_nombramiento,fecha_nacimiento,sexo\n")
    write(tmp_path / "transitorias.csv", "año,grado,delta\n2027,5,3\n")
    data = cargar_tabular(str(tmp_path), AppConfig())
    assert data.transitorias[(2027, Grado.PREFECTO)] == 3
