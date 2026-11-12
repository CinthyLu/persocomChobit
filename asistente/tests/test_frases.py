"""Las 10 frases contra el LLM real. Se saltan si no hay ANTHROPIC_API_KEY.

Correr solo estas:  pytest -m llm -v
"""

import os

import anthropic
import pytest

from asistente import config
from asistente.entender import interpretar, validar
from asistente.tests.frases import AHORA, FRASES

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="sin ANTHROPIC_API_KEY"),
]


@pytest.mark.parametrize("frase, intencion, campos", FRASES, ids=[f[0][:40] for f in FRASES])
async def test_frase(frase, intencion, campos):
    async with anthropic.AsyncAnthropic() as cliente:
        i = await interpretar(frase, AHORA, cliente=cliente, modelo=config.cargar().llm_model)
    assert i.intencion == intencion
    for campo, esperado in campos.items():
        assert getattr(i, campo) == esperado, f"{campo}: {getattr(i, campo)!r}"
    r = validar(i, AHORA)
    assert r.estado == ("falta" if campos.get("inicio", "") is None else "listo")
