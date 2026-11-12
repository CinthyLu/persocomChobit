"""Reglas de validación y fechas. No llama al LLM: corre gratis y sin conexión."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from asistente.entender import Interpretacion, calendario, contexto, validar

ZONA = ZoneInfo("America/Guayaquil")
AHORA = datetime(2026, 11, 12, 10, 0, tzinfo=ZONA)  # jueves


def interp(**campos) -> Interpretacion:
    return Interpretacion(**{"intencion": "crear_evento", "idioma": "es", **campos})


def test_evento_completo_queda_listo_con_valores_por_defecto():
    r = validar(interp(titulo="Dentista", inicio="2026-11-17T15:00"), AHORA)
    assert r.estado == "listo" and r.requiere_confirmacion
    assert r.inicio == datetime(2026, 11, 17, 15, 0, tzinfo=ZONA)
    assert r.fin - r.inicio == timedelta(hours=1)
    assert r.avisos_min == [1440, 60]


def test_evento_sin_hora_pregunta():
    r = validar(interp(titulo="Examen de física", pregunta="¿Qué día y a qué hora es el examen?"), AHORA)
    assert r.estado == "falta"
    assert r.mensaje == "¿Qué día y a qué hora es el examen?"


def test_evento_sin_titulo_pregunta():
    assert validar(interp(inicio="2026-11-17T15:00"), AHORA).estado == "falta"


def test_fecha_pasada_se_rechaza():
    r = validar(interp(titulo="Dentista", inicio="2026-11-11T15:00"), AHORA)
    assert r.estado == "invalido" and "ya pasó" in r.mensaje


def test_fin_antes_del_inicio_se_rechaza():
    r = validar(interp(titulo="Reunión", inicio="2026-11-14T16:00", fin="2026-11-14T14:00"), AHORA)
    assert r.estado == "invalido"


def test_fecha_ilegible_se_rechaza():
    assert validar(interp(titulo="Dentista", inicio="el martes"), AHORA).estado == "invalido"


def test_no_se_programan_avisos_que_ya_pasaron():
    # Evento en 3 horas: el aviso de "1 día antes" ya no tiene sentido.
    r = validar(interp(titulo="Cita", inicio="2026-11-12T13:00"), AHORA)
    assert r.avisos_min == [60]


def test_avisos_pedidos_por_la_persona():
    r = validar(interp(titulo="Cita", inicio="2026-11-20T13:00", avisos_min=[30, 120, -5]), AHORA)
    assert r.avisos_min == [120, 30]


def test_alarma_avisa_a_la_hora_y_no_necesita_titulo():
    r = validar(interp(intencion="crear_alarma", inicio="2026-11-13T06:30"), AHORA)
    assert r.estado == "listo" and r.titulo == "Alarma"
    assert r.avisos_min == [0] and r.fin is None


def test_tarea_usa_inicio_como_fecha_limite():
    r = validar(interp(intencion="crear_tarea", titulo="Informe", inicio="2026-11-13T23:59"), AHORA)
    assert r.estado == "listo" and r.tipo == "entrega" and r.fin is None


def test_consulta_no_pide_confirmacion():
    r = validar(interp(intencion="consultar", desde="2026-11-13T00:00", hasta="2026-11-13T23:59"), AHORA)
    assert r.estado == "listo" and not r.requiere_confirmacion


def test_consulta_sin_rango_es_hoy():
    r = validar(interp(intencion="consultar"), AHORA)
    assert (r.desde.day, r.desde.hour, r.hasta.hour, r.hasta.minute) == (12, 0, 23, 59)


def test_mover_y_borrar_necesitan_referencia():
    assert validar(interp(intencion="borrar"), AHORA).estado == "falta"
    assert validar(interp(intencion="mover", inicio="2026-11-18T16:00"), AHORA).estado == "falta"
    assert validar(interp(intencion="borrar", referencia="reunión del lunes"), AHORA).estado == "listo"


def test_charla_devuelve_la_respuesta():
    r = validar(interp(intencion="charla", respuesta="¡Hola!"), AHORA)
    assert r.estado == "charla" and r.mensaje == "¡Hola!"


def test_fecha_con_desfase_se_convierte_a_la_zona_local():
    r = validar(interp(titulo="Llamada", inicio="2026-11-17T20:00+00:00"), AHORA)
    assert r.inicio.hour == 15 and r.inicio.tzinfo == ZONA


@pytest.mark.parametrize(
    "ahora, esperado",
    [
        (datetime(2026, 11, 12, 10, 0, tzinfo=ZONA), ["2026-11-12 jueves (hoy)", "2026-11-13 viernes (mañana)"]),
        (datetime(2026, 11, 30, 10, 0, tzinfo=ZONA), ["2026-11-30 lunes (hoy)", "2026-12-01 martes (mañana)"]),  # cambio de mes
        (datetime(2026, 12, 31, 23, 0, tzinfo=ZONA), ["2026-12-31 jueves (hoy)", "2027-01-01 viernes (mañana)"]),  # cambio de año
    ],
)
def test_calendario_que_recibe_el_llm(ahora, esperado):
    assert calendario(ahora).splitlines()[:2] == esperado
    assert f"Ahora: {ahora:%Y-%m-%dT%H:%M}" in contexto(ahora)
