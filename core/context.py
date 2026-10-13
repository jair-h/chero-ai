"""Capa de contexto y validación del motor de texto de Tentakl.

Funciones PURAS (sin Streamlit ni cliente de IA) que el motor de generación
usa para armar y sanear los prompts:
  - get_contexto_pais: contexto de mercado local por país.
  - construir_contexto_base: bloque base que se antepone a todos los prompts.
  - validar_input / sanitizar: saneamiento de entrada antes de ir al modelo.

Extraídas de app.py para adelgazar el monolito y poder, más adelante, sacar
el motor de texto a core/ai.py sin arrastrar imports circulares.
"""
from __future__ import annotations

# Emojis de bandera que se limpian del nombre de país recibido de la UI
_EMOJIS_BANDERA = [
    "🇵🇪", "🇨🇴", "🇲🇽", "🇦🇷", "🇨🇱", "🇧🇷", "🇺🇸", "🇪🇸", "🇨🇦",
    "🇪🇨", "🇧🇴", "🇵🇾", "🇺🇾", "🇻🇪", "🇨🇷", "🇵🇦", "🇬🇹", "🇭🇳",
    "🇸🇻", "🇳🇮", "🇩🇴", "🇵🇷", "🇨🇺", "🌍",
]

# Contexto de mercado por país (moneda, plataformas, pagos, fechas, idioma…)
CONTEXTO_PAISES = {
    "Perú":     {"moneda": "S/", "moneda_nombre": "Soles peruanos", "plataformas_top": "Instagram, TikTok, Facebook, WhatsApp", "pagos_locales": "Yape, Plin, tarjetas Visa/MC, PagoEfectivo", "timezone": "GMT-5", "idioma": "es", "fechas_clave": "CyberWow (mayo), Fiestas Patrias (julio), Black Friday (nov), Navidad"},
    "Colombia":  {"moneda": "COP $", "moneda_nombre": "Pesos colombianos", "plataformas_top": "Instagram, TikTok, Facebook, WhatsApp", "pagos_locales": "Nequi, Daviplata, PSE, tarjetas", "timezone": "GMT-5", "idioma": "es", "fechas_clave": "Día sin IVA (jun/nov), Amor y Amistad (sep), Navidad"},
    "México":  {"moneda": "MXN $", "moneda_nombre": "Pesos mexicanos", "plataformas_top": "Instagram, TikTok, Facebook, YouTube, WhatsApp", "pagos_locales": "OXXO, SPEI, tarjetas, Mercado Pago, CoDi", "timezone": "GMT-6", "idioma": "es", "fechas_clave": "Buen Fin (nov), Día de Muertos (nov), Hot Sale (may)"},
    "Argentina": {"moneda": "ARS $", "moneda_nombre": "Pesos argentinos", "plataformas_top": "Instagram, WhatsApp, TikTok, Facebook", "pagos_locales": "MercadoPago, transferencia bancaria, tarjetas", "timezone": "GMT-3", "idioma": "es", "fechas_clave": "Hot Sale (may), CyberMonday (oct), Navidad"},
    "Chile":     {"moneda": "CLP $", "moneda_nombre": "Pesos chilenos", "plataformas_top": "Instagram, TikTok, Facebook, WhatsApp", "pagos_locales": "Webpay, Khipu, tarjetas, Mercado Pago", "timezone": "GMT-3", "idioma": "es", "fechas_clave": "CyberDay (may), Fiestas Patrias (sep), Black Friday"},
    "Brasil":    {"moneda": "R$", "moneda_nombre": "Reais brasileiros", "plataformas_top": "WhatsApp, Instagram, TikTok, YouTube", "pagos_locales": "PIX, boleto bancário, cartões", "timezone": "GMT-3", "idioma": "pt", "fechas_clave": "Black Friday (nov), Carnaval (fev), Natal (dez), Dia das Mães (mai)"},
    "España":  {"moneda": "€", "moneda_nombre": "Euros", "plataformas_top": "Instagram, TikTok, LinkedIn, Facebook, YouTube", "pagos_locales": "Bizum, tarjetas, PayPal, transferencia", "timezone": "GMT+1", "idioma": "es", "fechas_clave": "Black Friday, Reyes Magos (ene), Navidad, verano"},
    "USA":       {"moneda": "$", "moneda_nombre": "US Dollars", "plataformas_top": "Instagram, TikTok, Facebook, YouTube, LinkedIn, X/Twitter", "pagos_locales": "PayPal, Venmo, tarjetas, Apple Pay, Zelle", "timezone": "GMT-5 to GMT-8", "idioma": "en", "fechas_clave": "Black Friday, Cyber Monday, Super Bowl, 4th of July"},
    "Canadá": {"moneda": "CAD $", "moneda_nombre": "Canadian Dollars", "plataformas_top": "Instagram, TikTok, Facebook, YouTube, LinkedIn", "pagos_locales": "Interac, tarjetas, PayPal", "timezone": "GMT-5 to GMT-8", "idioma": "en", "fechas_clave": "Black Friday, Boxing Day (dic), Canada Day (jul)"},
    "Ecuador":   {"moneda": "$", "moneda_nombre": "Dólares (moneda oficial)", "plataformas_top": "WhatsApp, Instagram, Facebook, TikTok", "pagos_locales": "tarjetas, transferencias, DeUna", "timezone": "GMT-5", "idioma": "es", "fechas_clave": "Black Friday, Navidad, Fiestas de Quito (dic)"},
    "Bolivia":   {"moneda": "Bs.", "moneda_nombre": "Bolivianos", "plataformas_top": "WhatsApp, Facebook, Instagram, TikTok", "pagos_locales": "Tigo Money, tarjetas, transferencias", "timezone": "GMT-4", "idioma": "es", "fechas_clave": "Black Friday, Navidad, Carnaval de Oruro (feb)"},
    "Paraguay":  {"moneda": "₲", "moneda_nombre": "Guaraníes", "plataformas_top": "WhatsApp, Facebook, Instagram, TikTok", "pagos_locales": "Tigo Money, tarjetas, transferencias", "timezone": "GMT-4", "idioma": "es", "fechas_clave": "Black Friday, Navidad, Carnaval"},
    "Uruguay":   {"moneda": "$", "moneda_nombre": "Pesos uruguayos", "plataformas_top": "Instagram, WhatsApp, Facebook, TikTok", "pagos_locales": "MercadoPago, tarjetas, transferencias", "timezone": "GMT-3", "idioma": "es", "fechas_clave": "Black Friday, Navidad, Carnaval"},
    "Venezuela": {"moneda": "$", "moneda_nombre": "USD (uso común) / Bolívares", "plataformas_top": "Instagram, TikTok, WhatsApp, Facebook", "pagos_locales": "Pago móvil, Zelle, tarjetas, efectivo USD", "timezone": "GMT-4", "idioma": "es", "fechas_clave": "Black Friday, Navidad, Carnaval"},
    "Costa Rica": {"moneda": "₡", "moneda_nombre": "Colones", "plataformas_top": "WhatsApp, Instagram, Facebook, TikTok", "pagos_locales": "SINPE Móvil, tarjetas, transferencias", "timezone": "GMT-6", "idioma": "es", "fechas_clave": "Black Friday, Navidad, 15 de Septiembre"},
    "Panamá": {"moneda": "$", "moneda_nombre": "Dólares (moneda oficial)", "plataformas_top": "WhatsApp, Instagram, Facebook, TikTok", "pagos_locales": "tarjetas, transferencias, Yappy", "timezone": "GMT-5", "idioma": "es", "fechas_clave": "Black Friday, Navidad, Carnaval"},
    "Guatemala": {"moneda": "Q", "moneda_nombre": "Quetzales", "plataformas_top": "WhatsApp, Facebook, Instagram, TikTok", "pagos_locales": "tarjetas, transferencias, Tigo Money", "timezone": "GMT-6", "idioma": "es", "fechas_clave": "Black Friday, Navidad, 15 de Septiembre"},
    "Honduras":  {"moneda": "L", "moneda_nombre": "Lempiras", "plataformas_top": "WhatsApp, Facebook, Instagram, TikTok", "pagos_locales": "tarjetas, transferencias, Tigo Money", "timezone": "GMT-6", "idioma": "es", "fechas_clave": "Black Friday, Navidad, 15 de Septiembre"},
    "El Salvador": {"moneda": "$", "moneda_nombre": "Dólares (moneda oficial)", "plataformas_top": "WhatsApp, Facebook, Instagram, TikTok", "pagos_locales": "tarjetas, transferencias, Bitcoin (legal)", "timezone": "GMT-6", "idioma": "es", "fechas_clave": "Black Friday, Navidad, 15 de Septiembre"},
    "Nicaragua": {"moneda": "C$", "moneda_nombre": "Córdobas", "plataformas_top": "WhatsApp, Facebook, Instagram, TikTok", "pagos_locales": "tarjetas, transferencias", "timezone": "GMT-6", "idioma": "es", "fechas_clave": "Black Friday, Navidad, 19 de Julio"},
    "República Dominicana": {"moneda": "RD$", "moneda_nombre": "Pesos dominicanos", "plataformas_top": "WhatsApp, Instagram, Facebook, TikTok", "pagos_locales": "tarjetas, transferencias bancarias", "timezone": "GMT-4", "idioma": "es", "fechas_clave": "Black Friday, Navidad, 27 de Febrero"},
    "Puerto Rico": {"moneda": "$", "moneda_nombre": "US Dollars", "plataformas_top": "Instagram, TikTok, Facebook, WhatsApp", "pagos_locales": "PayPal, tarjetas, Venmo", "timezone": "GMT-4", "idioma": "es", "fechas_clave": "Black Friday, Navidad, Fiestas San Sebastián (ene)"},
    "Cuba":      {"moneda": "CUP $", "moneda_nombre": "Pesos cubanos", "plataformas_top": "WhatsApp, Facebook, Instagram", "pagos_locales": "efectivo, transferencias", "timezone": "GMT-5", "idioma": "es", "fechas_clave": "Navidad, Año Nuevo, 26 de Julio"},
}

_CONTEXTO_DEFAULT = {
    "moneda": "$", "moneda_nombre": "USD",
    "plataformas_top": "Instagram, TikTok, Facebook, WhatsApp, YouTube",
    "pagos_locales": "tarjetas internacionales Visa/Mastercard, PayPal",
    "timezone": "GMT-5", "idioma": "es",
    "fechas_clave": "Black Friday (nov), Navidad (dic), fin de año",
}


def get_contexto_pais(pais):
    """Devuelve el contexto de mercado del país (o un default global)."""
    _p = str(pais)
    for _em in _EMOJIS_BANDERA:
        _p = _p.replace(_em, "").strip()
    for _k in CONTEXTO_PAISES:
        if _k.lower() in _p.lower():
            return CONTEXTO_PAISES[_k]
    return dict(_CONTEXTO_DEFAULT)


def construir_contexto_base(pais, moneda, idioma, reglas_marca):
    """CONTEXTO_BASE que se inyecta al inicio de todos los prompts."""
    return f"""
Adapta tu respuesta al mercado de {pais}.
Usa expresiones naturales de {pais}.
Precios y ejemplos en {moneda}.
Referencias culturales locales de {pais}.
Horarios y fechas relevantes.
Responde en el idioma del usuario: {idioma}.
Sé específico y accionable. No des respuestas genéricas.
{"Reglas de marca: " + reglas_marca if reglas_marca else ""}
"""


def _sanitizar(texto, max_chars=3000):
    texto = (texto or "").strip()[:max_chars]
    texto = texto.replace('<', '').replace('>', '')
    return texto


def validar_input(texto, max_chars=3000):
    """Valida y sanitiza input antes de enviar al modelo. Retorna (texto, error|None)."""
    if not texto or not str(texto).strip():
        return None, "Campo vacío"
    texto = str(texto).strip()[:max_chars]
    texto = texto.replace('<script', '')
    texto = texto.replace('</script', '')
    texto = texto.replace('javascript:', '')
    texto = texto.replace('<iframe', '')
    return texto, None
