from __future__ import annotations

from datetime import date

from pdi_projection.config import AppConfig
from pdi_projection.domain import (
    EligibilityTrace,
    EstadoEscalafon,
    EstadoFuncionario,
    EventoCarrera,
    Funcionario,
    Grado,
    PromotionDecisionTrace,
    RankingTrace,
    TipoEvento,
    Via,
    grado_anterior,
)
from pdi_projection.eligibility import get_elegibles


def puntaje_merito(f: Funcionario, t: int, config: dict) -> float:
    ventana = config["ventana_años"]
    mapeo = config["mapeo_lista_puntaje"]
    pesos = config["ponderadores_temporales"]
    cals = sorted([c for c in f.historico_calificaciones if c.año < t], key=lambda c: c.año, reverse=True)[:ventana]
    if not cals:
        return 0.0
    puntajes = [mapeo.get(c.lista, 0) or 0 for c in cals]
    pesos_efectivos = pesos[: len(puntajes)]
    total_peso = sum(pesos_efectivos)
    return sum(p * w for p, w in zip(puntajes, pesos_efectivos)) / total_peso


def ordenar_por_merito(elegibles: list[Funcionario], t: int, config: dict) -> list[Funcionario]:
    return sorted(elegibles, key=lambda f: (-puntaje_merito(f, t, config), f.antiguedad_escalafon, f.id))


def ordenar_por_antiguedad(elegibles: list[Funcionario]) -> list[Funcionario]:
    return sorted(elegibles, key=lambda f: (f.antiguedad_escalafon, f.id))


def construir_ranking_trace(
    elegibles: list[Funcionario],
    grado_destino: Grado,
    t: int,
    config_merito: dict,
) -> list[RankingTrace]:
    m = ordenar_por_merito(elegibles, t, config_merito)
    a = ordenar_por_antiguedad(elegibles)
    mpos = {f.id: i + 1 for i, f in enumerate(m)}
    apos = {f.id: i + 1 for i, f in enumerate(a)}
    out = []
    for f in elegibles:
        out.append(
            RankingTrace(
                funcionario_id=f.id,
                grado_destino=grado_destino,
                puntaje_merito=puntaje_merito(f, t, config_merito),
                ranking_merito=mpos[f.id],
                ranking_antiguedad=apos[f.id],
                año=t,
            )
        )
    return sorted(out, key=lambda x: x.ranking_merito)


def calcular_vacantes(grado: Grado, t: int, estado: EstadoEscalafon, cfg: AppConfig) -> int:
    planta_ley = estado.planta[grado].vacantes_ley
    transitoria = estado.transitorias.get((t, grado), 0)
    dotacion_actual = sum(
        1 for f in estado.funcionarios.values() if f.estado == EstadoFuncionario.ACTIVO and f.grado_actual == grado
    )
    no_provistas = estado.vacantes_no_provistas[grado]
    if not cfg.policy.accumulate_unfilled_vacancies:
        no_provistas = 0
    return max(0, planta_ley + transitoria - dotacion_actual + no_provistas)


def siguiente_numero_escalafon(estado: EstadoEscalafon, grado: Grado) -> int:
    actuales = [
        f.antiguedad_escalafon
        for f in estado.funcionarios.values()
        if f.estado == EstadoFuncionario.ACTIVO and f.grado_actual == grado
    ]
    return max(actuales, default=0) + 1


def aplicar_ascenso(f: Funcionario, grado_destino: Grado, t: int, estado: EstadoEscalafon, cfg: AppConfig) -> None:
    f.grado_actual = grado_destino
    month, day = cfg.policy.event_month_day
    f.fecha_ingreso_grado_actual = date(t, month, day)
    f.antiguedad_escalafon = siguiente_numero_escalafon(estado, grado_destino)
    f.abono_meses = 0
    if estado.vacantes_no_provistas[grado_destino] > 0:
        estado.vacantes_no_provistas[grado_destino] -= 1


def seleccionar_candidato(
    pos: int,
    lista_merito: list[Funcionario],
    lista_antiguedad: list[Funcionario],
    ya_ascendidos: set[str],
    cfg: AppConfig,
) -> tuple[Funcionario | None, Via | None, str]:
    prefer_merito = pos <= 5
    lane = Via.MERITO if prefer_merito else Via.ANTIGUEDAD
    primary = lista_merito if prefer_merito else lista_antiguedad
    secondary = lista_antiguedad if prefer_merito else lista_merito

    candidato = next((x for x in primary if x.id not in ya_ascendidos), None)
    if candidato:
        return candidato, lane, "lane_ok"

    if cfg.policy.allow_lane_fallback:
        candidato = next((x for x in secondary if x.id not in ya_ascendidos), None)
        if candidato:
            via_fb = Via.ANTIGUEDAD if lane == Via.MERITO else Via.MERITO
            return candidato, via_fb, "fallback_lane"

    return None, None, "lane_without_candidate"


def registrar_vacantes_remanentes(estado: EstadoEscalafon, grado_destino: Grado, vacantes: int, cfg: AppConfig) -> None:
    if vacantes <= 0:
        return
    if cfg.policy.accumulate_unfilled_vacancies:
        estado.vacantes_no_provistas[grado_destino] += vacantes
        estado.vacancy_age[grado_destino] += 1
        ttl = cfg.policy.unfilled_vacancy_ttl_years
        if ttl is not None and estado.vacancy_age[grado_destino] > ttl:
            estado.vacantes_no_provistas[grado_destino] = 0
            estado.vacancy_age[grado_destino] = 0


def ejecutar_ascensos(
    estado: EstadoEscalafon,
    t: int,
    cfg: AppConfig,
) -> tuple[list[EventoCarrera], list[EventoCarrera], list[EligibilityTrace], list[RankingTrace], list[PromotionDecisionTrace]]:
    config_merito = cfg.merit.config
    ascensos_totales: list[EventoCarrera] = []
    postergados_totales: list[EventoCarrera] = []
    elegibilidad_trazas: list[EligibilityTrace] = []
    ranking_trazas: list[RankingTrace] = []
    decision_trazas: list[PromotionDecisionTrace] = []

    orden_ascensos = [Grado.PREFECTO, Grado.SUBPREFECTO, Grado.COMISARIO, Grado.SUBCOMISARIO, Grado.INSPECTOR, Grado.SUBINSPECTOR]

    for grado_destino in orden_ascensos:
        grado_origen = grado_anterior(grado_destino)
        if grado_origen is None:
            continue

        vacantes = calcular_vacantes(grado_destino, t, estado, cfg)
        if vacantes == 0:
            continue

        elegibles, trazas = get_elegibles(estado, grado_origen, t, grado_destino, cfg)
        elegibilidad_trazas.extend(trazas)
        decisiones = []
        cycle_ini = estado.cycle_counter[grado_destino]
        vac_ini = vacantes

        if not elegibles:
            registrar_vacantes_remanentes(estado, grado_destino, vacantes, cfg)
            decision_trazas.append(PromotionDecisionTrace(t, grado_destino, grado_origen, vac_ini, vacantes, cycle_ini, cycle_ini, [{"resultado": "sin_elegibles"}]))
            continue

        lista_merito = ordenar_por_merito(elegibles, t, config_merito)
        lista_antiguedad = ordenar_por_antiguedad(elegibles)
        ranking_trazas.extend(construir_ranking_trace(elegibles, grado_destino, t, config_merito))

        ya_ascendidos: set[str] = set()
        posiciones_sin_candidato = 0
        while vacantes > 0 and len(ya_ascendidos) < len(elegibles):
            pos = estado.cycle_counter[grado_destino] + 1
            candidato, via, motivo_sel = seleccionar_candidato(pos, lista_merito, lista_antiguedad, ya_ascendidos, cfg)
            if candidato is None:
                decisiones.append({"pos": str(pos), "resultado": motivo_sel})
                if cfg.policy.enforce_batch_cutoff_on_missing_lane_candidate:
                    break
                if cfg.policy.allow_lane_fallback:
                    # seleccionar_candidato ya intentó ambas vías: no hay forma de avanzar.
                    break
                estado.cycle_counter[grado_destino] = pos % 6
                posiciones_sin_candidato += 1
                if posiciones_sin_candidato >= 6:
                    # Una vuelta completa sin candidato: el ciclo no puede progresar.
                    break
                continue

            posiciones_sin_candidato = 0
            aplicar_ascenso(candidato, grado_destino, t, estado, cfg)
            ascensos_totales.append(
                EventoCarrera(
                    candidato.id,
                    t,
                    TipoEvento.ASCENSO,
                    grado_origen=grado_origen,
                    grado_destino=grado_destino,
                    via=via,
                    motivo=motivo_sel,
                )
            )
            decisiones.append({"pos": str(pos), "funcionario": candidato.id, "via": via.value, "resultado": motivo_sel})
            ya_ascendidos.add(candidato.id)
            vacantes -= 1
            estado.cycle_counter[grado_destino] = pos % 6

        registrar_vacantes_remanentes(estado, grado_destino, vacantes, cfg)

        for f in elegibles:
            if f.id not in ya_ascendidos:
                postergados_totales.append(
                    EventoCarrera(
                        f.id,
                        t,
                        TipoEvento.POSTERGACION_VACANTE,
                        grado_origen=f.grado_actual,
                        grado_destino=grado_destino,
                        motivo="sin_vacante_o_corte_tanda",
                    )
                )

        decision_trazas.append(
            PromotionDecisionTrace(
                año=t,
                grado_destino=grado_destino,
                grado_origen=grado_origen,
                vacantes_iniciales=vac_ini,
                vacantes_finales=vacantes,
                cycle_counter_inicial=cycle_ini,
                cycle_counter_final=estado.cycle_counter[grado_destino],
                decisiones=decisiones,
            )
        )

    return ascensos_totales, postergados_totales, elegibilidad_trazas, ranking_trazas, decision_trazas
