"""Convierte una frase en una intención estructurada y la valida.

El LLM nunca escribe en la agenda: solo devuelve una `Interpretacion` (JSON).
`validar()` revisa ese JSON con reglas de código y decide si se puede ejecutar,
si hay que preguntar algo o si no se entendió.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import anthropic
from pydantic import BaseModel, Field

RAIZ = Path(__file__).resolve().parent

Intencion = Literal[
    "crear_evento", "crear_tarea", "crear_alarma", "consultar", "mover", "borrar", "charla", "desconocido"
]

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
AVISOS_POR_DEFECTO = [1440, 60]  # 1 día y 1 hora antes
DURACION_POR_DEFECTO = timedelta(hours=1)


class Interpretacion(BaseModel):
    """Lo que el LLM entendió de la frase. Las fechas van en hora local, sin zona."""

    intencion: Intencion
    titulo: str | None = Field(
        None, description="Título corto del evento, tarea o alarma, en el idioma de la persona."
    )
    inicio: str | None = Field(
        None,
        description=(
            "Fecha y hora local en formato AAAA-MM-DDTHH:MM. Inicio del evento, hora de la alarma, "
            "fecha límite de la tarea, o nuevo inicio al mover. null si la persona no dio fecha u hora."
        ),
    )
    fin: str | None = Field(
        None, description="Fin del evento, AAAA-MM-DDTHH:MM. null si no se dijo duración ni hora de fin."
    )
    tipo: Literal["clase", "cita", "entrega", "otro"] | None = None
    avisos_min: list[int] | None = Field(
        None, description="Minutos de antelación de los avisos, solo si la persona los pidió."
    )
    desde: str | None = Field(None, description="Para consultar: inicio del rango, AAAA-MM-DDTHH:MM.")
    hasta: str | None = Field(None, description="Para consultar: fin del rango, AAAA-MM-DDTHH:MM.")
    referencia: str | None = Field(
        None, description="Para mover o borrar: palabras que identifican el evento existente."
    )
    pregunta: str | None = Field(
        None, description="Si falta un dato indispensable, la pregunta breve para pedirlo."
    )
    respuesta: str | None = Field(None, description="Solo para charla o desconocido: respuesta breve.")
    idioma: str = Field(description="Código ISO 639-1 del idioma de la frase, por ejemplo es, en.")


@dataclass
class Resultado:
    """Interpretación ya validada, con fechas con zona horaria."""

    estado: Literal["listo", "falta", "invalido", "charla"]
    intencion: Intencion
    titulo: str | None = None
    inicio: datetime | None = None
    fin: datetime | None = None
    tipo: str = "otro"
    avisos_min: list[int] = field(default_factory=list)
    desde: datetime | None = None
    hasta: datetime | None = None
    referencia: str | None = None
    mensaje: str | None = None  # pregunta, error o respuesta de charla
    idioma: str = "es"

    @property
    def requiere_confirmacion(self) -> bool:
        return self.estado == "listo" and self.intencion != "consultar"


class ErrorLLM(Exception):
    """El LLM no devolvió una interpretación utilizable."""


# ---------------------------------------------------------------- prompt

REGLAS = """\
Eres el módulo de comprensión de un asistente personal de agenda. Recibes un mensaje de la \
persona y devuelves solo la interpretación estructurada. Otro programa valida tu salida, pide \
confirmación y recién entonces escribe en la agenda, así que tu trabajo es interpretar con \
exactitud, no ejecutar.

Intenciones:
- crear_evento: algo con día y hora (cita, clase, reunión).
- crear_tarea: un pendiente con fecha límite ("tengo que entregar el informe el viernes"). \
`inicio` es la fecha límite; si no se dijo hora, usa 23:59.
- crear_alarma: un aviso suelto a una hora ("despiértame a las 6:30"). `inicio` es la hora del aviso.
- consultar: pregunta por la agenda. Llena `desde` y `hasta` con el rango pedido \
("mañana" es de 00:00 a 23:59 de mañana; "esta semana" llega hasta el domingo a las 23:59).
- mover: cambiar un evento existente. `referencia` lo identifica, `inicio` es la nueva fecha y hora.
- borrar: eliminar un evento existente. `referencia` lo identifica.
- charla: saludo o conversación que no toca la agenda. Contesta en `respuesta`.
- desconocido: no se entiende qué quiere. Explícalo brevemente en `respuesta`.

Fechas:
- Usa el calendario que viene con cada mensaje para resolver "mañana", "el martes", "pasado \
mañana" o "el 3". No calcules los días de la semana de memoria.
- Un día de la semana sin más significa su próxima aparición, sin contar hoy salvo que la hora \
indicada aún no haya pasado.
- Una hora ambigua como "a las 3" para una cita, clase o reunión es por la tarde (15:00). \
"A las 6:30" para despertarse es por la mañana.
- Una hora de hoy que ya pasó se entiende como mañana solo en alarmas; en lo demás, respeta lo dicho.
- No inventes datos. Si a un evento le falta el día o la hora, deja `inicio` en null y escribe \
en `pregunta` qué falta. Deja `fin` en null si no se dijo duración.

Escribe `titulo`, `pregunta` y `respuesta` en el idioma de la persona. El título es corto y \
empieza con mayúscula ("Dentista", "Lección de cálculo").

Lo que sigue describe la voz del asistente; aplícala en `pregunta` y `respuesta`.
"""


def cargar_personalidad() -> str:
    return (RAIZ / "personalidad.md").read_text(encoding="utf-8")


def calendario(ahora: datetime, dias: int = 15) -> str:
    """Lista de los próximos días con su nombre, para que el LLM no calcule fechas de memoria."""
    lineas = []
    for i in range(dias):
        d = ahora.date() + timedelta(days=i)
        marca = " (hoy)" if i == 0 else " (mañana)" if i == 1 else ""
        lineas.append(f"{d.isoformat()} {DIAS[d.weekday()]}{marca}")
    return "\n".join(lineas)


def contexto(ahora: datetime) -> str:
    return (
        f"Ahora: {ahora:%Y-%m-%dT%H:%M}, {DIAS[ahora.weekday()]}. Zona horaria: {ahora.tzinfo}.\n"
        f"Calendario:\n{calendario(ahora)}"
    )


# ---------------------------------------------------------------- LLM


async def interpretar(
    texto: str,
    ahora: datetime,
    *,
    cliente: anthropic.AsyncAnthropic,
    modelo: str = "claude-opus-5-5",
    historial: list[dict] | None = None,
) -> Interpretacion:
    """Llama al LLM. `historial` son los turnos previos cuando el bot hizo una pregunta."""
    mensajes = list(historial or [])
    mensajes.append({"role": "user", "content": f"{contexto(ahora)}\n\nMensaje: {texto}"})
    try:
        r = await cliente.beta.messages.parse(
            model=modelo,
            max_tokens=4000,
            # Las reglas y la personalidad no cambian entre mensajes: se cachean.
            system=[
                {
                    "type": "text",
                    "text": REGLAS + "\n" + cargar_personalidad(),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=mensajes,
            output_format=Interpretacion,
            output_config={"effort": "low"},  # frases cortas: no hace falta más
            # Si el modelo rechaza una frase por error, la API reintenta sola en otro modelo.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError as e:
        raise ErrorLLM("límite de uso alcanzado") from e
    except anthropic.APIStatusError as e:
        raise ErrorLLM(f"error {e.status_code} de la API") from e
    except anthropic.APIConnectionError as e:
        raise ErrorLLM("sin conexión con la API") from e

    if r.stop_reason in ("refusal", "max_tokens") or r.parsed_output is None:
        raise ErrorLLM(f"respuesta incompleta ({r.stop_reason})")
    return r.parsed_output


# ---------------------------------------------------------------- validación


def _fecha(valor: str | None, zona: ZoneInfo) -> datetime | None:
    """Convierte 'AAAA-MM-DDTHH:MM' en fecha con zona. Lanza ValueError si no es una fecha."""
    if not valor:
        return None
    d = datetime.fromisoformat(valor)
    return d.replace(tzinfo=zona) if d.tzinfo is None else d.astimezone(zona)


def validar(i: Interpretacion, ahora: datetime) -> Resultado:
    """Aplica las reglas de código sobre lo que devolvió el LLM."""
    zona = ahora.tzinfo
    base = dict(intencion=i.intencion, titulo=(i.titulo or "").strip() or None, idioma=i.idioma)

    def falta(porque: str) -> Resultado:
        return Resultado(estado="falta", mensaje=i.pregunta or porque, **base)

    def invalido(porque: str) -> Resultado:
        return Resultado(estado="invalido", mensaje=porque, **base)

    if i.intencion in ("charla", "desconocido"):
        return Resultado(estado="charla", mensaje=i.respuesta or "No te entendí, ¿me lo dices de otra forma?", **base)

    try:
        inicio, fin = _fecha(i.inicio, zona), _fecha(i.fin, zona)
        desde, hasta = _fecha(i.desde, zona), _fecha(i.hasta, zona)
    except ValueError:
        return invalido("No pude leer la fecha. ¿Me la repites con día y hora?")

    if i.intencion == "consultar":
        if desde is None:
            desde = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        if hasta is None:
            hasta = desde.replace(hour=23, minute=59)
        if hasta < desde:
            return invalido("El rango de fechas quedó al revés. ¿Qué días quieres ver?")
        return Resultado(estado="listo", desde=desde, hasta=hasta, **base)

    if i.intencion == "borrar":
        if not i.referencia:
            return falta("¿Qué evento quieres borrar?")
        return Resultado(estado="listo", referencia=i.referencia, **base)

    if i.intencion == "mover":
        if not i.referencia:
            return falta("¿Qué evento quieres mover?")
        if inicio is None:
            return falta("¿A qué día y hora lo paso?")
    else:  # crear_evento, crear_tarea, crear_alarma
        if base["titulo"] is None:
            if i.intencion != "crear_alarma":
                return falta("¿Cómo lo anoto?")
            base["titulo"] = "Alarma"
        if inicio is None:
            return falta("¿Para qué día y a qué hora?")

    if inicio <= ahora:
        return invalido(f"Esa fecha ya pasó ({inicio:%d/%m %H:%M}). ¿Cuál es la correcta?")
    if inicio > ahora + timedelta(days=366 * 2):
        return invalido("Esa fecha queda a más de dos años. ¿La revisas?")

    if i.intencion in ("crear_evento", "mover"):
        if fin is None:
            fin = inicio + DURACION_POR_DEFECTO
        elif fin <= inicio:
            return invalido("La hora de fin queda antes del inicio. ¿A qué hora termina?")
    else:
        fin = None

    if i.intencion == "crear_alarma":
        avisos = [0]
    else:
        pedidos = i.avisos_min if i.avisos_min else AVISOS_POR_DEFECTO
        # Se descartan los avisos cuya hora ya pasó (un evento en 30 min no avisa "1 día antes").
        avisos = sorted(
            {m for m in pedidos if 0 <= m <= 60 * 24 * 30 and inicio - timedelta(minutes=m) > ahora},
            reverse=True,
        )

    return Resultado(
        estado="listo",
        inicio=inicio,
        fin=fin,
        tipo="entrega" if i.intencion == "crear_tarea" and not i.tipo else (i.tipo or "otro"),
        avisos_min=avisos,
        referencia=i.referencia,
        **base,
    )
