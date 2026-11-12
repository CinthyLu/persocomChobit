"""Las 10 frases de prueba que el bot debe entender (meta: 9 de 10 a la primera).

Todas se evalúan como si fueran las 10:00 del jueves 12 de noviembre de 2026.
Cambia o agrega frases con tu forma real de hablar y los idiomas que usas.
Cada caso: (frase, intención esperada, campos esperados).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

AHORA = datetime(2026, 11, 12, 10, 0, tzinfo=ZoneInfo("America/Guayaquil"))  # jueves

FRASES = [
    ("el martes a las 3 tengo dentista", "crear_evento", {"inicio": "2026-11-17T15:00"}),
    ("El jueves a las 10 tengo lección de cálculo", "crear_evento", {"inicio": "2026-11-19T10:00"}),
    ("¿Qué tengo mañana?", "consultar", {"desde": "2026-11-13T00:00", "hasta": "2026-11-13T23:59"}),
    ("Tengo que entregar el informe el viernes", "crear_tarea", {"inicio": "2026-11-13T23:59"}),
    ("despiértame a las 6:30", "crear_alarma", {"inicio": "2026-11-13T06:30"}),
    ("Pasa el dentista al miércoles a las 4", "mover", {"inicio": "2026-11-18T16:00"}),
    ("borra la reunión del lunes", "borrar", {}),
    ("pasado mañana reunión de grupo de 2 a 4 de la tarde", "crear_evento",
     {"inicio": "2026-11-14T14:00", "fin": "2026-11-14T16:00"}),
    ("I have a meeting with Dr. Lee next Monday at 9am", "crear_evento", {"inicio": "2026-11-16T09:00"}),
    ("tengo examen de física", "crear_evento", {"inicio": None}),  # falta el día: debe preguntar
]
