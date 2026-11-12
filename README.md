# Asistente de agenda en Telegram (fase 1)

Bot personal que entiende frases como «el martes a las 3 tengo dentista», pide confirmación
y las guarda. Este es el código de la semana 1: el bot responde solo a su dueña, el LLM
convierte cada frase en JSON, el código lo valida y lo confirmado se guarda en SQLite.
Google Calendar y los recordatorios llegan en las semanas 3 y 4.

## Puesta en marcha

1. Crea el bot en Telegram con [@BotFather](https://t.me/BotFather) (`/newbot`) y copia el token.
2. Crea una clave en la consola de Anthropic y ponle un límite de gasto mensual.
3. Instala y configura (Python 3.12 o superior):

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # en Windows: .venv\Scripts\activate
   pip install -r requirements-dev.txt
   cp .env.example .env             # y llena TELEGRAM_TOKEN y ANTHROPIC_API_KEY
   ```

4. Arranca el bot con `python -m asistente.bot`, escríbele `/id` y pega ese número en
   `TELEGRAM_OWNER_ID` dentro de `.env`. Reinicia: desde ahí solo te atiende a ti.

## Pruebas

```bash
pytest              # reglas de validación, fechas y base de datos (gratis, sin conexión)
pytest -m llm -v    # las 10 frases contra el LLM real (necesita ANTHROPIC_API_KEY, cuesta centavos)
```

Las 10 frases están en `asistente/tests/frases.py`; cámbialas por tu forma real de hablar.

## Archivos

| Archivo | Qué hace |
| --- | --- |
| `asistente/bot.py` | Arranque, filtro por dueña, confirmación con botones, guardado |
| `asistente/entender.py` | Llamada al LLM (salida JSON) y validación en código |
| `asistente/modelos.py` | Tablas `usuarios`, `eventos`, `tareas`, `recordatorios`, `registro` |
| `asistente/personalidad.md` | Nombre y tono del asistente (borrador: edítalo) |
| `asistente/config.py` | Lectura del `.env` |

El modelo por defecto es `claude-opus-5-5`; se cambia con `LLM_MODEL` en `.env`.
