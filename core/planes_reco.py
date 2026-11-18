"""Recomendador de plan por reglas (sin IA, gratis, instantáneo).

Venta guiada: 3 preguntas simples → recomienda el plan que MEJOR encaja.
La lógica hace que la mayoría de negocios normales caiga en el plan del MEDIO
(Pro), que es "el completo para la mayoría" — honesto, no forzado: solo manda
al base a quien recién prueba y al alto a agencias/multi-cliente.

Todo es data pura + una función; la UI (en app.py) solo muestra y enруta.
"""
from __future__ import annotations

# Preguntas y opciones (clave interna, etiqueta ES, etiqueta EN).
PREGUNTAS_RECO = [
    ("venta", ("¿Cómo vendes hoy?", "How do you sell today?"), [
        ("empiezo", ("Recién empiezo / aún no vendo online", "Just starting / not selling online yet")),
        ("sin_ads", ("Vendo, pero no invierto en publicidad", "I sell, but don't invest in ads")),
        ("con_ads", ("Ya invierto en publicidad (Meta, Google…)", "I already invest in ads (Meta, Google…)")),
    ]),
    ("equipo", ("¿Quién maneja tu marketing?", "Who runs your marketing?"), [
        ("solo", ("Solo yo", "Just me")),
        ("equipo", ("Tengo un equipo pequeño", "I have a small team")),
        ("agencia", ("Soy agencia / manejo varios negocios", "I'm an agency / I manage several businesses")),
    ]),
    ("objetivo", ("¿Qué quieres lograr?", "What do you want to achieve?"), [
        ("probar", ("Probar y aprender", "Try it and learn")),
        ("crecer", ("Crecer en serio", "Grow seriously")),
        ("varios", ("Gestionar varios clientes/negocios", "Manage several clients/businesses")),
    ]),
]


def recomendar_plan(venta: str, equipo: str, objetivo: str) -> dict:
    """Devuelve {"plan", "razon_es", "razon_en"} según las 3 respuestas.

    plan ∈ {"Starter", "Pro", "Agency"}. Pro (el del medio) es el resultado más
    común a propósito: es el completo para un negocio normal.
    """
    if equipo == "agencia" or objetivo == "varios":
        return {"plan": "Agency",
                "razon_es": "Manejas varios negocios o clientes: el plan Agency te da multi-cliente "
                            "y todo lo del plan Pro.",
                "razon_en": "You manage several businesses or clients: Agency gives you multi-client "
                            "and everything in Pro."}
    if venta == "empiezo" and objetivo == "probar":
        return {"plan": "Starter",
                "razon_es": "Estás empezando y quieres probar: el plan Starter te da el contenido con IA "
                            "y el Gemelo para arrancar sin gastar de más.",
                "razon_en": "You're starting out and want to try: Starter gives you AI content and the "
                            "Twin to begin without overspending."}
    return {"plan": "Pro",
            "razon_es": "Para crecer en serio: el plan Pro desbloquea el Gemelo COMPLETO (historial + "
                        "precisión), las integraciones y el Autopiloto. Es el ideal para la mayoría.",
            "razon_en": "To grow seriously: Pro unlocks the FULL Twin (history + accuracy), integrations "
                        "and Autopilot. The best fit for most businesses."}
