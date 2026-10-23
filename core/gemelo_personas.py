"""Gemelo — AGENTES-PERSONA (el 20% que razona el "por qué").

Tres personas opinan sobre la decisión YA simulada: comprador, competidor y
mercado. NO inventan cifras: razonan SOBRE los números que calculó el motor
(veredicto, ventas, utilidad). Usan gemini-2.5-flash-lite (rápido y barato) y
temperatura baja (anti-fantasía). Se llaman a pedido, no en cada simulación.

`generar_texto` se inyecta (igual que en gemelo_ui) para no acoplar con app.py.
"""
from __future__ import annotations

MODELO_PERSONAS = "gemini-2.5-flash-lite"

_DECISION_DESC = {
    "presupuesto": "decidir cuánto invertir en publicidad y cómo repartirlo entre canales",
    "precio": "cambiar el precio de venta",
    "producto": "lanzar un producto nuevo",
    "zona": "abrir operaciones en una zona/distrito nuevo",
}


def _contexto_numeros(r, moneda):
    """Resumen de los números del motor que las personas pueden citar (no inventan)."""
    v = r.get("ventas", {})
    ut = r.get("utilidad", {})
    ver = r.get("veredicto", {})
    txt = (f"Veredicto del motor: {ver.get('icono','')} {ver.get('titulo','')}. "
           f"Ventas estimadas entre {v.get('p10',0):.0f} y {v.get('p90',0):.0f} "
           f"(probable {v.get('p50',0):.0f}). "
           f"Utilidad probable {moneda}{ut.get('p50',0):.0f}.")
    if r.get("precio"):
        txt += f" Precio {moneda}{r.get('precio',0):.0f}."
    if r.get("comparacion"):
        c = r["comparacion"]
        txt += (f" (Precio actual {moneda}{r.get('precio_actual',0):.0f} vs nuevo "
                f"{moneda}{r.get('precio_nuevo',0):.0f}; cambio de utilidad {c.get('mejora',0):+.0f}.)")
    return txt


def _pedir(generar_texto, prompt):
    try:
        out = generar_texto(prompt, max_out=900, modelo=MODELO_PERSONAS, temperatura=0.3)
        return (out or "").strip()
    except Exception:
        return ""


def opiniones_equipo(generar_texto, resultado, marca, sector, moneda,
                     ciudad="", distrito=""):
    """Devuelve {'comprador':.., 'competidor':.., 'mercado':..} (texto corto cada uno)."""
    if not generar_texto:
        return {}
    tipo = resultado.get("tipo", "presupuesto")
    decision = _DECISION_DESC.get(tipo, tipo)
    nums = _contexto_numeros(resultado, moneda)
    lugar = (f"{ciudad} {distrito}").strip() or "su mercado"
    regla = ("Responde en español, en 2-3 frases, directo y sin markdown. "
             "NO inventes cifras ni nombres; puedes citar los números dados. "
             "Si el veredicto es ⚠️ o ❌, no lo adornes.")

    p_comprador = (
        f"Eres un CLIENTE típico del sector {sector} en {lugar}. "
        f"La marca '{marca}' está evaluando {decision}.\n{nums}\n"
        f"Como comprador, reacciona: ¿comprarías?, ¿el precio te parece justo?, "
        f"¿qué te haría dudar? {regla}"
    )
    p_competidor = (
        f"Eres un COMPETIDOR directo de '{marca}' en el sector {sector} en {lugar}. "
        f"'{marca}' va a {decision}.\n{nums}\n"
        f"¿Cómo reaccionas tú? (bajar precio, copiar, ignorar, diferenciarte). {regla}"
    )
    p_mercado = (
        f"Eres un ANALISTA de mercado del sector {sector} en {lugar}. "
        f"Evalúa el contexto de {decision}: timing, estacionalidad, tendencia y riesgo principal.\n{nums}\n{regla}"
    )
    return {
        "comprador": _pedir(generar_texto, p_comprador),
        "competidor": _pedir(generar_texto, p_competidor),
        "mercado": _pedir(generar_texto, p_mercado),
    }
