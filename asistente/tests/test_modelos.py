from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from asistente.bot import consultar, guardar, obtener_usuario
from asistente.entender import Interpretacion, validar
from asistente.modelos import Evento, Recordatorio, Tarea, crear_motor, crear_tablas

ZONA = ZoneInfo("America/Guayaquil")
AHORA = datetime(2026, 11, 12, 10, 0, tzinfo=ZONA)


@pytest.fixture
def sesiones(tmp_path):
    return crear_tablas(crear_motor(f"sqlite:///{tmp_path / 'prueba.db'}"))


def test_las_fechas_vuelven_en_utc_con_zona(sesiones):
    with sesiones.begin() as s:
        u = obtener_usuario(s, 123, "America/Guayaquil")
        inicio = datetime(2026, 11, 17, 15, 0, tzinfo=ZONA)
        s.add(Evento(usuario=u, titulo="Dentista", inicio=inicio, fin=inicio + timedelta(hours=1)))
    with sesiones() as s:
        e = s.scalar(select(Evento))
        assert e.inicio == inicio and e.inicio.tzinfo == timezone.utc
        assert e.inicio.astimezone(ZONA).hour == 15


def test_no_se_aceptan_fechas_sin_zona(sesiones):
    with pytest.raises(Exception, match="zona horaria"):
        with sesiones.begin() as s:
            u = obtener_usuario(s, 123, "America/Guayaquil")
            s.add(Evento(usuario=u, titulo="X", inicio=datetime(2026, 11, 17, 15), fin=datetime(2026, 11, 17, 16)))


def test_el_usuario_se_crea_una_sola_vez(sesiones):
    with sesiones.begin() as s:
        a = obtener_usuario(s, 123, "America/Guayaquil")
        b = obtener_usuario(s, 123, "America/Guayaquil")
        assert a.id == b.id


def test_guardar_evento_y_tarea_con_sus_recordatorios_y_consultarlos(sesiones):
    evento = validar(Interpretacion(intencion="crear_evento", titulo="Dentista", inicio="2026-11-17T15:00", idioma="es"), AHORA)
    tarea = validar(Interpretacion(intencion="crear_tarea", titulo="Informe", inicio="2026-11-17T23:59", idioma="es"), AHORA)
    with sesiones.begin() as s:
        u = obtener_usuario(s, 123, "America/Guayaquil")
        guardar(s, u, evento)
        guardar(s, u, tarea)
    with sesiones() as s:
        u = obtener_usuario(s, 123, "America/Guayaquil")
        assert s.scalar(select(Tarea)).limite == tarea.inicio
        envios = sorted(r.enviar_en for r in s.scalar(select(Evento)).recordatorios)
        assert envios == [evento.inicio - timedelta(days=1), evento.inicio - timedelta(hours=1)]
        assert len(s.scalars(select(Recordatorio)).all()) == 4

        martes = validar(Interpretacion(intencion="consultar", desde="2026-11-17T00:00", hasta="2026-11-17T23:59", idioma="es"), AHORA)
        texto = consultar(s, u, martes, ZONA)
        assert "martes 17/11 a las 15:00: Dentista" in texto and "Informe" in texto

        lunes = validar(Interpretacion(intencion="consultar", desde="2026-11-16T00:00", hasta="2026-11-16T23:59", idioma="es"), AHORA)
        assert "No tienes nada" in consultar(s, u, lunes, ZONA)
