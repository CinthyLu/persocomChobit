"""Tablas de SQLite (SQLAlchemy 2.0).

Todas las fechas se guardan en UTC y se devuelven con zona horaria, para que
nunca haya una fecha "ingenua" dando vueltas por el código.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


class FechaUTC(TypeDecorator):
    """DateTime que exige zona horaria al guardar y devuelve siempre UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("La fecha debe llevar zona horaria")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(unique=True, index=True)
    zona_horaria: Mapped[str] = mapped_column(String(64), default="America/Guayaquil")
    hora_resumen: Mapped[str] = mapped_column(String(5), default="07:00")  # HH:MM local
    # Minutos de antelación de los avisos, separados por comas: "1440,60" = 1 día y 1 hora.
    avisos_min: Mapped[str] = mapped_column(String(64), default="1440,60")
    creado: Mapped[datetime] = mapped_column(FechaUTC, default=ahora_utc)

    eventos: Mapped[list[Evento]] = relationship(back_populates="usuario", cascade="all, delete-orphan")
    tareas: Mapped[list[Tarea]] = relationship(back_populates="usuario", cascade="all, delete-orphan")


class Evento(Base):
    __tablename__ = "eventos"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    google_id: Mapped[str | None] = mapped_column(String(128), unique=True)  # se llena en la semana 3
    titulo: Mapped[str] = mapped_column(String(200))
    inicio: Mapped[datetime] = mapped_column(FechaUTC, index=True)
    fin: Mapped[datetime] = mapped_column(FechaUTC)
    tipo: Mapped[str] = mapped_column(String(16), default="otro")  # clase, cita, entrega, alarma, otro
    creado: Mapped[datetime] = mapped_column(FechaUTC, default=ahora_utc)

    usuario: Mapped[Usuario] = relationship(back_populates="eventos")
    recordatorios: Mapped[list[Recordatorio]] = relationship(
        back_populates="evento", cascade="all, delete-orphan"
    )


class Tarea(Base):
    __tablename__ = "tareas"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    limite: Mapped[datetime | None] = mapped_column(FechaUTC, index=True)
    estado: Mapped[str] = mapped_column(String(16), default="pendiente")  # pendiente, hecha, cancelada
    veces_pospuesta: Mapped[int] = mapped_column(default=0)
    creado: Mapped[datetime] = mapped_column(FechaUTC, default=ahora_utc)

    usuario: Mapped[Usuario] = relationship(back_populates="tareas")
    recordatorios: Mapped[list[Recordatorio]] = relationship(
        back_populates="tarea", cascade="all, delete-orphan"
    )


class Recordatorio(Base):
    __tablename__ = "recordatorios"

    id: Mapped[int] = mapped_column(primary_key=True)
    evento_id: Mapped[int | None] = mapped_column(ForeignKey("eventos.id"), index=True)
    tarea_id: Mapped[int | None] = mapped_column(ForeignKey("tareas.id"), index=True)
    enviar_en: Mapped[datetime] = mapped_column(FechaUTC, index=True)
    enviado_en: Mapped[datetime | None] = mapped_column(FechaUTC)
    estado: Mapped[str] = mapped_column(String(16), default="pendiente")  # pendiente, enviado, hecho, pospuesto

    evento: Mapped[Evento | None] = relationship(back_populates="recordatorios")
    tarea: Mapped[Tarea | None] = relationship(back_populates="recordatorios")


class Registro(Base):
    """Historial de lo que pasó con cada aviso; base de las métricas y de la fase 3."""

    __tablename__ = "registro"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    recordatorio_id: Mapped[int | None] = mapped_column(ForeignKey("recordatorios.id"))
    fecha: Mapped[datetime] = mapped_column(FechaUTC, default=ahora_utc, index=True)
    accion: Mapped[str] = mapped_column(String(16))  # mensaje, cumplida, pospuesta, ignorada
    detalle: Mapped[str | None] = mapped_column(String(500))


def crear_motor(url: str) -> Engine:
    return create_engine(url)


def crear_tablas(motor: Engine) -> sessionmaker:
    """Crea las tablas que falten y devuelve la fábrica de sesiones."""
    Base.metadata.create_all(motor)
    return sessionmaker(motor, expire_on_commit=False)
