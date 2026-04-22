from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum, IntEnum


class Grado(IntEnum):
    DETECTIVE = 13
    SUBINSPECTOR = 12
    INSPECTOR = 11
    SUBCOMISARIO = 9
    COMISARIO = 8
    SUBPREFECTO = 7
    PREFECTO = 5


SECUENCIA_OPPL = [
    Grado.DETECTIVE,
    Grado.SUBINSPECTOR,
    Grado.INSPECTOR,
    Grado.SUBCOMISARIO,
    Grado.COMISARIO,
    Grado.SUBPREFECTO,
    Grado.PREFECTO,
]


def grado_siguiente(g: Grado) -> Grado | None:
    try:
        return SECUENCIA_OPPL[SECUENCIA_OPPL.index(g) + 1]
    except IndexError:
        return None


def grado_anterior(g: Grado) -> Grado | None:
    idx = SECUENCIA_OPPL.index(g)
    if idx == 0:
        return None
    return SECUENCIA_OPPL[idx - 1]


class Via(Enum):
    MERITO = "merito"
    ANTIGUEDAD = "antiguedad"


class TipoImpedimento(Enum):
    SUMARIO = "sumario"
    SANCION = "sancion"
    SALUD = "salud"


class EstadoFuncionario(Enum):
    ACTIVO = "activo"
    RETIRADO_CARRERA_30 = "retirado_carrera_30"
    RETIRADO_LISTA_4 = "retirado_lista_4"
    RETIRADO_VOLUNTARIO = "retirado_voluntario"
    RETIRADO_OTRO = "retirado_otro"


class TipoEvento(Enum):
    ASCENSO = "ascenso"
    POSTERGACION_VACANTE = "postergacion_vacante"
    POSTERGACION_LISTA = "postergacion_lista"
    RETIRO = "retiro"
    INGRESO = "ingreso"
    INGRESO_RECHAZADO = "ingreso_rechazado"


class CausalRetiro(Enum):
    CARRERA_30 = "carrera_30"
    LISTA_4 = "lista_4"
    VOLUNTARIO = "voluntario"
    SALUD = "salud"
    OTRO = "otro"


class EstadoElegibilidad(Enum):
    ELEGIBLE = "elegible"
    NO_ELEGIBLE_TIEMPO = "no_elegible_tiempo"
    NO_ELEGIBLE_CURSO = "no_elegible_curso"
    NO_ELEGIBLE_IMPEDIMENTO = "no_elegible_impedimento"
    POSTERGADO_LISTA = "postergado_lista"
    RETIRADO = "retirado"


@dataclass
class Calificacion:
    año: int
    lista: int
    nota: float | None = None


@dataclass
class Impedimento:
    tipo: TipoImpedimento
    fecha_inicio: date
    fecha_fin: date | None


@dataclass
class Curso:
    id: str
    nombre: str
    grado_que_habilita: Grado


@dataclass
class EventoCarrera:
    funcionario_id: str
    año: int
    tipo: TipoEvento
    grado_origen: Grado | None = None
    grado_destino: Grado | None = None
    via: Via | None = None
    causal: CausalRetiro | None = None
    motivo: str | None = None


@dataclass
class Funcionario:
    id: str
    fecha_nacimiento: date
    sexo: str
    fecha_ingreso_institucion: date
    fecha_ingreso_grado_actual: date
    grado_actual: Grado
    antiguedad_escalafon: int
    cursos_aprobados: set[str]
    historico_calificaciones: list[Calificacion]
    abono_meses: int = 0
    impedimentos: list[Impedimento] = field(default_factory=list)
    estado: EstadoFuncionario = EstadoFuncionario.ACTIVO
    retiro_voluntario_fecha: date | None = None
    retiro_voluntario_causal: CausalRetiro | None = None
    historico_eventos: list[EventoCarrera] = field(default_factory=list)


@dataclass
class Planta:
    grado: Grado
    vacantes_ley: int
    permanencia_min_años: int


@dataclass
class EligibilityTrace:
    funcionario_id: str
    año: int
    grado_origen: Grado
    grado_destino: Grado
    cumple_lista: bool
    lista_valor: int | None
    cumple_impedimento: bool
    impedimento_activo: str | None
    cumple_tiempo: bool
    tiempo_en_grado: float
    cumple_curso: bool
    elegible: bool
    estado: EstadoElegibilidad
    motivo: str


@dataclass
class RankingTrace:
    funcionario_id: str
    grado_destino: Grado
    puntaje_merito: float
    ranking_merito: int
    ranking_antiguedad: int


@dataclass
class PromotionDecisionTrace:
    año: int
    grado_destino: Grado
    grado_origen: Grado
    vacantes_iniciales: int
    vacantes_finales: int
    cycle_counter_inicial: int
    cycle_counter_final: int
    decisiones: list[dict[str, str]]


@dataclass
class ValidationIssue:
    severity: str
    code: str
    message: str
    row_ref: str | None = None


@dataclass
class EstadoEscalafon:
    """Modelo consolidado del escalafón en un año t."""

    año_actual: int
    funcionarios: dict[str, Funcionario]
    planta: dict[Grado, Planta]
    transitorias: dict[tuple[int, Grado], int]
    vacantes_no_provistas: dict[Grado, int]
    cycle_counter: dict[Grado, int]
    cursos: dict[str, Curso]
    vacancy_age: dict[Grado, int] = field(default_factory=dict)


PLANTA_OPPL_2025 = {
    Grado.DETECTIVE: Planta(Grado.DETECTIVE, 300, 1),
    Grado.SUBINSPECTOR: Planta(Grado.SUBINSPECTOR, 1351, 3),
    Grado.INSPECTOR: Planta(Grado.INSPECTOR, 1955, 5),
    Grado.SUBCOMISARIO: Planta(Grado.SUBCOMISARIO, 1609, 6),
    Grado.COMISARIO: Planta(Grado.COMISARIO, 711, 5),
    Grado.SUBPREFECTO: Planta(Grado.SUBPREFECTO, 321, 5),
    Grado.PREFECTO: Planta(Grado.PREFECTO, 59, 5),
}

CURSOS_OPPL = {
    "COG": Curso(id="COG", nombre="Curso de Oficial Graduado", grado_que_habilita=Grado.PREFECTO)
}

MERITO_CONFIG_DEFAULT = {
    "ventana_años": 3,
    "mapeo_lista_puntaje": {1: 100, 2: 70, 3: 0, 4: None},
    "ponderadores_temporales": [0.5, 0.3, 0.2],
    "bonus_cursos_adicionales": 0,
    "descuento_sanciones": 0,
}
