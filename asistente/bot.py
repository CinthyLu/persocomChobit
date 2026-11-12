"""Arranque del bot y handlers de Telegram.

Ejecutar desde la carpeta del proyecto:  python -m asistente.bot
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import anthropic
from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import config, entender
from .entender import DIAS, Resultado
from .modelos import Evento, Recordatorio, Registro, Tarea, Usuario, crear_motor, crear_tablas

log = logging.getLogger("asistente")

MAX_TURNOS_PREGUNTA = 6  # mensajes de ida y vuelta que se recuerdan mientras falta un dato


# ---------------------------------------------------------------- textos


def cuando(d: datetime) -> str:
    return f"{DIAS[d.weekday()]} {d:%d/%m} a las {d:%H:%M}"


def antelacion(minutos: int) -> str:
    if minutos == 0:
        return "a la hora"
    if minutos % 1440 == 0:
        n = minutos // 1440
        return f"{n} día{'s' if n > 1 else ''} antes"
    if minutos % 60 == 0:
        n = minutos // 60
        return f"{n} hora{'s' if n > 1 else ''} antes"
    return f"{minutos} min antes"


def resumen(r: Resultado) -> str:
    """Texto que la persona confirma antes de guardar."""
    if r.intencion == "crear_evento":
        lineas = [f"📅 {r.titulo}", f"{cuando(r.inicio)} (hasta las {r.fin:%H:%M})"]
    elif r.intencion == "crear_tarea":
        lineas = [f"📝 {r.titulo}", f"Fecha límite: {cuando(r.inicio)}"]
    elif r.intencion == "crear_alarma":
        lineas = [f"⏰ {r.titulo}", cuando(r.inicio)]
    elif r.intencion == "mover":
        lineas = [f"Mover «{r.referencia}»", f"Nueva fecha: {cuando(r.inicio)}"]
    else:  # borrar
        lineas = [f"Borrar «{r.referencia}»"]
    if r.avisos_min and r.intencion != "crear_alarma":
        lineas.append("Avisos: " + ", ".join(antelacion(m) for m in r.avisos_min))
    return "\n".join(lineas)


BOTONES = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Confirmar", callback_data="ok"), InlineKeyboardButton("Cancelar", callback_data="no")]]
)


# ---------------------------------------------------------------- base de datos


def obtener_usuario(sesion, telegram_id: int, zona: str) -> Usuario:
    usuario = sesion.scalar(select(Usuario).where(Usuario.telegram_id == telegram_id))
    if usuario is None:
        usuario = Usuario(telegram_id=telegram_id, zona_horaria=zona)
        sesion.add(usuario)
        sesion.flush()
    return usuario


def guardar(sesion, usuario: Usuario, r: Resultado) -> None:
    """Guarda en SQLite lo confirmado. Google Calendar se conecta en la semana 3."""
    if r.intencion == "crear_tarea":
        item = Tarea(usuario=usuario, titulo=r.titulo, limite=r.inicio)
    else:
        item = Evento(
            usuario=usuario,
            titulo=r.titulo,
            inicio=r.inicio,
            fin=r.fin or r.inicio,
            tipo="alarma" if r.intencion == "crear_alarma" else r.tipo,
        )
    for minutos in r.avisos_min:
        item.recordatorios.append(Recordatorio(enviar_en=r.inicio - timedelta(minutes=minutos)))
    sesion.add(item)


def consultar(sesion, usuario: Usuario, r: Resultado, zona) -> str:
    eventos = sesion.scalars(
        select(Evento)
        .where(Evento.usuario_id == usuario.id, Evento.inicio >= r.desde, Evento.inicio <= r.hasta)
        .order_by(Evento.inicio)
    ).all()
    tareas = sesion.scalars(
        select(Tarea)
        .where(
            Tarea.usuario_id == usuario.id,
            Tarea.estado == "pendiente",
            Tarea.limite >= r.desde,
            Tarea.limite <= r.hasta,
        )
        .order_by(Tarea.limite)
    ).all()
    if not eventos and not tareas:
        return "No tienes nada anotado en esas fechas."
    lineas = [f"• {cuando(e.inicio.astimezone(zona))}: {e.titulo}" for e in eventos]
    lineas += [f"• 📝 {t.titulo} (hasta el {cuando(t.limite.astimezone(zona))})" for t in tareas]
    return "\n".join(lineas)


# ---------------------------------------------------------------- handlers


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde a cualquiera con su propio id: sirve para llenar TELEGRAM_OWNER_ID."""
    await update.message.reply_text(f"Tu id de Telegram es {update.effective_user.id}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hola. Escríbeme lo que quieras anotar, por ejemplo:\n"
        "«el martes a las 3 tengo dentista» o «¿qué tengo mañana?»"
    )


async def cmd_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text("Listo, lo dejamos ahí.")


async def al_recibir_texto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: config.Config = context.bot_data["config"]
    texto = update.message.text
    ahora = datetime.now(cfg.zona)
    historial: list[dict] = context.user_data.get("historial", [])

    await update.message.chat.send_action("typing")
    try:
        interp = await entender.interpretar(
            texto, ahora, cliente=context.bot_data["llm"], modelo=cfg.llm_model, historial=historial
        )
    except entender.ErrorLLM as e:
        log.warning("Fallo del LLM: %s", e)
        await update.message.reply_text("No pude procesar eso ahora mismo. Inténtalo de nuevo en un momento.")
        return

    r = entender.validar(interp, ahora)
    log.info("%r -> %s / %s", texto, r.intencion, r.estado)

    with context.bot_data["sesiones"].begin() as sesion:
        usuario = obtener_usuario(sesion, update.effective_user.id, str(cfg.zona))
        sesion.add(Registro(usuario_id=usuario.id, accion="mensaje", detalle=f"{r.intencion}/{r.estado}"))
        respuesta_consulta = consultar(sesion, usuario, r, cfg.zona) if r.intencion == "consultar" and r.estado == "listo" else None

    if r.estado in ("falta", "invalido"):
        # Se guarda la conversación para que la respuesta a la pregunta tenga contexto.
        historial += [
            {"role": "user", "content": f"{entender.contexto(ahora)}\n\nMensaje: {texto}"},
            {"role": "assistant", "content": r.mensaje},
        ]
        context.user_data["historial"] = historial[-MAX_TURNOS_PREGUNTA:]
        await update.message.reply_text(r.mensaje)
        return

    context.user_data.pop("historial", None)

    if r.estado == "charla":
        await update.message.reply_text(r.mensaje)
    elif respuesta_consulta is not None:
        await update.message.reply_text(respuesta_consulta)
    elif r.intencion in ("mover", "borrar"):
        await update.message.reply_text(
            f"Te entendí:\n{resumen(r)}\n\nMover y borrar llegan en las semanas 5 y 6; todavía no lo aplico."
        )
    else:
        context.user_data["pendiente"] = r
        await update.message.reply_text(resumen(r), reply_markup=BOTONES)


async def al_pulsar_boton(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    consulta = update.callback_query
    cfg: config.Config = context.bot_data["config"]
    if update.effective_user.id != cfg.owner_id:
        await consulta.answer()
        return
    await consulta.answer()
    r: Resultado | None = context.user_data.pop("pendiente", None)
    if r is None:
        await consulta.edit_message_text(f"{consulta.message.text}\n\n(Esta confirmación ya caducó.)")
        return
    if consulta.data != "ok":
        await consulta.edit_message_text(f"{consulta.message.text}\n\n✖️ Cancelado")
        return
    with context.bot_data["sesiones"].begin() as sesion:
        guardar(sesion, obtener_usuario(sesion, update.effective_user.id, str(cfg.zona)), r)
    await consulta.edit_message_text(f"{consulta.message.text}\n\n✅ Guardado")


async def al_fallar(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Error en un handler", exc_info=context.error)


# ---------------------------------------------------------------- arranque


def construir(cfg: config.Config) -> Application:
    app = ApplicationBuilder().token(cfg.telegram_token).build()
    app.bot_data["config"] = cfg
    app.bot_data["sesiones"] = crear_tablas(crear_motor(cfg.database_url))
    app.bot_data["llm"] = anthropic.AsyncAnthropic()

    app.add_handler(CommandHandler("id", cmd_id))
    if cfg.owner_id is None:
        log.warning("Falta TELEGRAM_OWNER_ID: el bot solo responde a /id hasta que lo configures.")
    else:
        # Todo lo demás solo atiende a la dueña; los mensajes de otras personas se ignoran.
        duena = filters.User(user_id=cfg.owner_id)
        app.add_handler(CommandHandler("start", cmd_start, filters=duena))
        app.add_handler(CommandHandler("cancelar", cmd_cancelar, filters=duena))
        app.add_handler(MessageHandler(duena & filters.TEXT & ~filters.COMMAND, al_recibir_texto))
        app.add_handler(CallbackQueryHandler(al_pulsar_boton))
    app.add_error_handler(al_fallar)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = config.cargar()
    if not cfg.telegram_token:
        raise SystemExit("Falta TELEGRAM_TOKEN en el archivo .env (mira .env.example).")
    construir(cfg).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
