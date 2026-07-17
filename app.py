import os
import streamlit as st
from google import genai
from google.genai import types
import pandas as pd
from pytrends.request import TrendReq
import datetime
from datetime import datetime as dt, timedelta, timezone
import requests
import re
import warnings
import io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
with warnings.catch_warnings():
    warnings.filterwarnings("ignore")
    from supabase import create_client, Client
from openai import OpenAI as OpenAIClient

# ✅ SIEMPRE PRIMERO: configuración de página
st.set_page_config(page_title="Tentakl.ai", page_icon="🐙", layout="wide")

# --- SECRETOS ---
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"🚨 Error conectando Supabase: {e}")
        supabase = None
elif not SUPABASE_URL:
    st.warning("⚠ SUPABASE_URL no configurada en secrets.toml — los datos no se guardarán.")
elif not SUPABASE_KEY:
    st.warning("⚠ SUPABASE_KEY no configurada en secrets.toml — los datos no se guardarán.")

# --- API KEYS ---
API_KEY = ""
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except Exception:
    API_KEY = os.getenv("GEMINI_API_KEY", "")

if not API_KEY:
    st.error("🚨 Falta tu GEMINI_API_KEY. Configúrala en .streamlit/secrets.toml")
    st.stop()

YOUTUBE_API_KEY = ""
try:
    YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]
except Exception:
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# ✅ CLIENTE GEMINI
try:
    client = genai.Client(api_key=API_KEY)
except Exception as e:
    st.error(f"Error conectando cliente Gemini: {e}")
    st.stop()

# =========================
# MODELOS Y PLANES
# =========================
MODELO_RAPIDO = "gemini-2.5-flash-lite"
MODELO_FUERTE = "gemini-2.5-flash"

# =========================
# COSTOS Y LÍMITES (esquema Tentakl)
# =========================
COSTO_CREDITOS = {
    "funcion_texto": 1,      # cualquier subfunción de texto
    "imagen": 5,             # generar imagen (además descuenta 1 del límite de imágenes)
    "edicion_imagen": 5,     # editar imagen con referencia (también descuenta 1 del límite)
    "autopiloto": 8,         # una corrida completa de Autopiloto
}

PRECIOS_PLANES = {"Starter": 19, "Pro": 39, "Agency": 79}

# Fallback si planes_config no está disponible (la fuente de verdad es Supabase)
_PLANES_FALLBACK = {
    "Free":    {"creditos": 50,   "imagenes_limite": 2,   "imagenes_limite_diario": 2,  "calidad_imagen": "low",    "precio": 0,  "creditos_renovables": False},
    "Starter": {"creditos": 200,  "imagenes_limite": 5,   "imagenes_limite_diario": 3,  "calidad_imagen": "medium", "precio": 19, "creditos_renovables": True},
    "Pro":     {"creditos": 500,  "imagenes_limite": 20,  "imagenes_limite_diario": 8,  "calidad_imagen": "high",   "precio": 39, "creditos_renovables": True},
    "Agency":  {"creditos": 1500, "imagenes_limite": 100, "imagenes_limite_diario": 25, "calidad_imagen": "high",   "precio": 79, "creditos_renovables": True},
    "Admin":   {"creditos": 9999, "imagenes_limite": 999, "imagenes_limite_diario": 999,"calidad_imagen": "high",   "precio": 0,  "creditos_renovables": True},
}

@st.cache_data(ttl=300)
def cargar_planes_config():
    """Lee los planes desde la tabla planes_config de Supabase (NO hardcodear).
    Cache de 5 min para no golpear la DB en cada rerun."""
    try:
        if not supabase:
            return _PLANES_FALLBACK
        res = supabase.table("planes_config").select("*").execute()
        planes = {}
        for row in (res.data or []):
            planes[row["nombre"]] = {
                "creditos": int(row.get("creditos", 50) or 50),
                "imagenes_limite": int(row.get("imagenes_limite", 0) or 0),
                "imagenes_limite_diario": int(row.get("imagenes_limite_diario", 2) or 2),
                "calidad_imagen": row.get("calidad_imagen", "low") or "low",
                "precio": float(row.get("precio", 0) or 0),
                "creditos_renovables": bool(row.get("creditos_renovables", True)),
            }
        if planes:
            return planes
    except Exception:
        pass
    return _PLANES_FALLBACK

def get_plan_config(plan=None):
    if plan is None:
        plan = st.session_state.get("plan", "Free")
    planes = cargar_planes_config()
    return planes.get(plan, planes.get("Free", _PLANES_FALLBACK["Free"]))

# Compatibilidad: PLANES ahora deriva de planes_config (limite = créditos del plan)
def _planes_compat():
    _p = {}
    for _nombre, _cfg in cargar_planes_config().items():
        _p[_nombre] = {"limite": _cfg["creditos"], "video": True, "max_output": 8000}
    return _p

class _PlanesProxy(dict):
    """Permite que el código existente siga usando PLANES[plan]['limite'] leyendo de planes_config."""
    def __getitem__(self, key):
        return _planes_compat().get(key, {"limite": 50, "video": True, "max_output": 8000})
    def get(self, key, default=None):
        _todos = _planes_compat()
        if key in _todos:
            return _todos[key]
        return default if default is not None else {"limite": 50, "video": True, "max_output": 8000}

PLANES = _PlanesProxy()

# =========================
# SESSION STATE INICIAL (una sola vez, al inicio)
# =========================
defaults = {
    "plan": "Free",
    "usados": 0,
    "cliente_sugerido": "",
    "user_email": "",
    "perfil_cargado": False,
    "cliente_activo_id": "",
    "cliente_activo_nombre": "",
    "marca_guardada": "",
    "pais_guardado": "Perú 🇵🇪",
    "ciudad_guardada": "",
    "nicho_guardado": "",
    "cliente_ideal_guardado": "",
    "producto_servicio": "",
    "link_redes": "",
    "link_web": "",
    "reglas_marca": "",
    "compliance_producto": "",
    "catalogo_lista_manual": "",
    "comunidad_comentarios": "",
    "email_marketing_descripcion": "",
    "landing_texto": "",
    "pr_noticia": "",
    "influencer_descripcion": "",
    "autopiloto_descripcion": "",
    "autopiloto_free_usado": False,
    "idioma_preferido": "Español",
    "user_sincronizado": False,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# =========================
# SISTEMA DE IDIOMAS
# =========================
_TRANS = {
    "es": {
        "tab_inicio": "🏠 INICIO",
        "tab_calendario": "📅 CALENDARIO",
        "tab_marketing": "🚀 MARKETING",
        "tab_ventas": "💰 VENTAS",
        "tab_admin": "🏢 ADMIN",
        "tab_reportes": "📊 MIS REPORTES",
        "tu_cuenta": "### 👤 Tu Cuenta",
        "mercado": "### 🌎 Mercado",
        "negocio": "### 💼 Negocio",
        "cliente_ideal_sec": "### 👥 Cliente Ideal",
        "email_label": "Email (Guardar Progreso):",
        "pais_label": "País Objetivo:",
        "ciudad_label": "Ciudad (Opcional):",
        "marca_label": "Marca:",
        "nicho_label": "Nicho:",
        "que_vendes": "¿Qué vendes?",
        "que_vendes_ph": "Ej: Vendo lentes ópticos, ropa casual, servicios de marketing...",
        "link_redes_label": "Link de redes sociales (Opcional):",
        "link_redes_ph": "Ej: instagram.com/minegocio o tiktok.com/@minegocio",
        "link_web_label": "Link de web o tienda online (Opcional):",
        "link_web_ph": "Ej: minegocio.com o minegocio.shopify.com",
        "detectar_cliente": "🧠 Detectar Cliente",
        "cliente_ideal_label": "Describe a tu cliente ideal:",
        "guardar_perfil": "💾 Guardar Perfil del Negocio",
        "creditos_restantes": "Créditos restantes",
        "consumo": "Consumo",
        "termometro": "📊 Termómetro de Marca",
        "rec_inteligente": "## ⚡ Acciones Inteligentes de Hoy",
        "btn_rec": "⚡ Ver acciones inteligentes de hoy",
        "btn_escanear": "🩺 Auditoría Maestra del Negocio (1 Crédito)",
        "plan_semanal_titulo": "## 🧠 Plan de Contenido Semanal",
        "btn_regenerar_plan": "🔄 Regenerar Plan Semanal (1 crédito)",
        "btn_generar_plan": "🚀 Generar Plan Semanal",
        "onboarding": "### 👋 ¡Bienvenido a TENTAKL.AI!\nComienza configurando tu perfil de negocio en el sidebar izquierdo: tu marca, nicho y qué vendes.",
        "motor_atraccion": "🚀 Motor de Atracción",
        "motor_desc": "Herramientas avanzadas para crear contenido que vende.",
        "sel_herramienta": "Herramienta:",
        "mkt_tools": [
            "Auditoría Visual (Video/Foto)", "Experto TikTok/Reels", "Segmentación Ads",
            "Embudo de Ventas",
            "Storytelling de Marca", "Plan de Crisis",
            "SEO y Palabras Clave", "Artículo de Blog SEO",
            "Compliance Checker", "🕵 Inteligencia Competitiva", "Campaña de Catálogo",
            "Generador de Imagenes",
            "🧪 Simulador de Campaña",
        ],
        "cerrador": "💰 Cerrador de Tratos",
        "sales_tools": ["Psicólogo de Precios", "Mata-Objeciones", "Calculadora Descuentos"],
        "oficina": "📊 Oficina Virtual",
        "admin_tools": ["Analista ROI (CSV)", "Cotizaciones", "Contratos", "Reglas de Marca", "Analizador de Métricas", "🔗 Integraciones"],
        "plan_selector": "Plan (cambiar):",
        "tab_power": "⚡ POWER TOOLS",
        "tab_crm": "👥 CRM",
        "power_tools": [
            "Email Marketing", "Gestión de Comunidad", "Influencer Marketing",
            "Auditoría SEO Completa",
            "PR Digital", "Tracker de KPIs", "Optimizador Landing CRO",
        ],
        "tab_autopiloto": "🤖 Autopiloto",
        "prompt_prefix": "",
    },
    "en": {
        "tab_inicio": "🏠 HOME",
        "tab_calendario": "📅 CALENDAR",
        "tab_marketing": "🚀 MARKETING",
        "tab_ventas": "💰 SALES",
        "tab_admin": "🏢 ADMIN",
        "tab_reportes": "📊 MY REPORTS",
        "tu_cuenta": "### 👤 Your Account",
        "mercado": "### 🌎 Market",
        "negocio": "### 💼 Business",
        "cliente_ideal_sec": "### 👥 Ideal Client",
        "email_label": "Email (Save Progress):",
        "pais_label": "Target Country:",
        "ciudad_label": "City (Optional):",
        "marca_label": "Brand:",
        "nicho_label": "Niche:",
        "que_vendes": "What do you sell?",
        "que_vendes_ph": "Ex: I sell optical glasses, casual clothing, marketing services...",
        "link_redes_label": "Social media link (Optional):",
        "link_redes_ph": "Ex: instagram.com/mybusiness or tiktok.com/@mybusiness",
        "link_web_label": "Website or online store link (Optional):",
        "link_web_ph": "Ex: mybusiness.com or mybusiness.shopify.com",
        "detectar_cliente": "🧠 Detect Client",
        "cliente_ideal_label": "Describe your ideal client:",
        "guardar_perfil": "💾 Save Business Profile",
        "creditos_restantes": "Remaining credits",
        "consumo": "Usage",
        "termometro": "📊 Brand Thermometer",
        "rec_inteligente": "## ⚡ Today's Intelligent Actions",
        "btn_rec": "⚡ See today's intelligent actions",
        "btn_escanear": "🩺 Master Business Audit (1 Credit)",
        "plan_semanal_titulo": "## 🧠 Weekly Content Plan",
        "btn_regenerar_plan": "🔄 Regenerate Weekly Plan (1 credit)",
        "btn_generar_plan": "🚀 Generate Weekly Plan",
        "onboarding": "### 👋 Welcome to TENTAKL.AI!\nStart by setting up your business profile in the left sidebar: your brand, niche and what you sell.",
        "motor_atraccion": "🚀 Attraction Engine",
        "motor_desc": "Advanced tools to create content that sells.",
        "sel_herramienta": "Tool:",
        "mkt_tools": [
            "Visual Audit (Video/Photo)", "TikTok/Reels Expert", "Ads Segmentation",
            "Sales Funnel",
            "Brand Storytelling", "Crisis Plan",
            "SEO & Keywords", "SEO Blog Article",
            "Compliance Checker", "🕵 Competitive Intelligence", "Catalog Campaign",
            "Image Generator",
            "🧪 Campaign Simulator",
        ],
        "cerrador": "💰 Deal Closer",
        "sales_tools": ["Price Psychology", "Objection Buster", "Discount Calculator"],
        "oficina": "📊 Virtual Office",
        "admin_tools": ["ROI Analyst (CSV)", "Quotes", "Contracts", "Brand Rules", "Metrics Analyzer", "🔗 Integrations"],
        "plan_selector": "Plan (change):",
        "tab_power": "⚡ POWER TOOLS",
        "power_tools": [
            "Email Marketing", "Community Management", "Influencer Marketing",
            "Complete SEO Audit",
            "Digital PR Generator", "KPI Tracker", "Landing Page Optimizer (CRO)",
        ],
        "tab_autopiloto": "🤖 Autopilot",
        "tab_crm": "👥 CRM",
        "prompt_prefix": "Respond in English. ",
    },
}

def t(key):
    lang = st.session_state.get("lang", "es")
    return _TRANS.get(lang, _TRANS["es"]).get(key, _TRANS["es"].get(key, key))


# =========================
# FUNCIONES DE IA
# =========================
# CONTEXTO LOCAL POR PAÍS
# =========================
def get_contexto_pais(pais):
    _p = str(pais)
    for _em in ["🇵🇪","🇨🇴","🇲🇽",
                "🇦🇷","🇨🇱","🇧🇷",
                "🇺🇸","🇪🇸","🇨🇦",
                "🇪🇨","🇧🇴","🇵🇾",
                "🇺🇾","🇻🇪","🇨🇷",
                "🇵🇦","🇬🇹","🇭🇳",
                "🇸🇻","🇳🇮","🇩🇴",
                "🇵🇷","🇨🇺","🌍"]:
        _p = _p.replace(_em, "").strip()
    _ctx = {
        "Perú":     {"moneda":"S/","moneda_nombre":"Soles peruanos","plataformas_top":"Instagram, TikTok, Facebook, WhatsApp","pagos_locales":"Yape, Plin, tarjetas Visa/MC, PagoEfectivo","timezone":"GMT-5","idioma":"es","fechas_clave":"CyberWow (mayo), Fiestas Patrias (julio), Black Friday (nov), Navidad"},
        "Colombia":  {"moneda":"COP $","moneda_nombre":"Pesos colombianos","plataformas_top":"Instagram, TikTok, Facebook, WhatsApp","pagos_locales":"Nequi, Daviplata, PSE, tarjetas","timezone":"GMT-5","idioma":"es","fechas_clave":"Día sin IVA (jun/nov), Amor y Amistad (sep), Navidad"},
        "México":  {"moneda":"MXN $","moneda_nombre":"Pesos mexicanos","plataformas_top":"Instagram, TikTok, Facebook, YouTube, WhatsApp","pagos_locales":"OXXO, SPEI, tarjetas, Mercado Pago, CoDi","timezone":"GMT-6","idioma":"es","fechas_clave":"Buen Fin (nov), Día de Muertos (nov), Hot Sale (may)"},
        "Argentina": {"moneda":"ARS $","moneda_nombre":"Pesos argentinos","plataformas_top":"Instagram, WhatsApp, TikTok, Facebook","pagos_locales":"MercadoPago, transferencia bancaria, tarjetas","timezone":"GMT-3","idioma":"es","fechas_clave":"Hot Sale (may), CyberMonday (oct), Navidad"},
        "Chile":     {"moneda":"CLP $","moneda_nombre":"Pesos chilenos","plataformas_top":"Instagram, TikTok, Facebook, WhatsApp","pagos_locales":"Webpay, Khipu, tarjetas, Mercado Pago","timezone":"GMT-3","idioma":"es","fechas_clave":"CyberDay (may), Fiestas Patrias (sep), Black Friday"},
        "Brasil":    {"moneda":"R$","moneda_nombre":"Reais brasileiros","plataformas_top":"WhatsApp, Instagram, TikTok, YouTube","pagos_locales":"PIX, boleto bancário, cartões","timezone":"GMT-3","idioma":"pt","fechas_clave":"Black Friday (nov), Carnaval (fev), Natal (dez), Dia das Mães (mai)"},
        "España":  {"moneda":"€","moneda_nombre":"Euros","plataformas_top":"Instagram, TikTok, LinkedIn, Facebook, YouTube","pagos_locales":"Bizum, tarjetas, PayPal, transferencia","timezone":"GMT+1","idioma":"es","fechas_clave":"Black Friday, Reyes Magos (ene), Navidad, verano"},
        "USA":       {"moneda":"$","moneda_nombre":"US Dollars","plataformas_top":"Instagram, TikTok, Facebook, YouTube, LinkedIn, X/Twitter","pagos_locales":"PayPal, Venmo, tarjetas, Apple Pay, Zelle","timezone":"GMT-5 to GMT-8","idioma":"en","fechas_clave":"Black Friday, Cyber Monday, Super Bowl, 4th of July"},
        "Canadá": {"moneda":"CAD $","moneda_nombre":"Canadian Dollars","plataformas_top":"Instagram, TikTok, Facebook, YouTube, LinkedIn","pagos_locales":"Interac, tarjetas, PayPal","timezone":"GMT-5 to GMT-8","idioma":"en","fechas_clave":"Black Friday, Boxing Day (dic), Canada Day (jul)"},
        "Ecuador":   {"moneda":"$","moneda_nombre":"Dólares (moneda oficial)","plataformas_top":"WhatsApp, Instagram, Facebook, TikTok","pagos_locales":"tarjetas, transferencias, DeUna","timezone":"GMT-5","idioma":"es","fechas_clave":"Black Friday, Navidad, Fiestas de Quito (dic)"},
        "Bolivia":   {"moneda":"Bs.","moneda_nombre":"Bolivianos","plataformas_top":"WhatsApp, Facebook, Instagram, TikTok","pagos_locales":"Tigo Money, tarjetas, transferencias","timezone":"GMT-4","idioma":"es","fechas_clave":"Black Friday, Navidad, Carnaval de Oruro (feb)"},
        "Paraguay":  {"moneda":"₲","moneda_nombre":"Guaraníes","plataformas_top":"WhatsApp, Facebook, Instagram, TikTok","pagos_locales":"Tigo Money, tarjetas, transferencias","timezone":"GMT-4","idioma":"es","fechas_clave":"Black Friday, Navidad, Carnaval"},
        "Uruguay":   {"moneda":"$","moneda_nombre":"Pesos uruguayos","plataformas_top":"Instagram, WhatsApp, Facebook, TikTok","pagos_locales":"MercadoPago, tarjetas, transferencias","timezone":"GMT-3","idioma":"es","fechas_clave":"Black Friday, Navidad, Carnaval"},
        "Venezuela": {"moneda":"$","moneda_nombre":"USD (uso común) / Bolívares","plataformas_top":"Instagram, TikTok, WhatsApp, Facebook","pagos_locales":"Pago móvil, Zelle, tarjetas, efectivo USD","timezone":"GMT-4","idioma":"es","fechas_clave":"Black Friday, Navidad, Carnaval"},
        "Costa Rica":{"moneda":"₡","moneda_nombre":"Colones","plataformas_top":"WhatsApp, Instagram, Facebook, TikTok","pagos_locales":"SINPE Móvil, tarjetas, transferencias","timezone":"GMT-6","idioma":"es","fechas_clave":"Black Friday, Navidad, 15 de Septiembre"},
        "Panamá": {"moneda":"$","moneda_nombre":"Dólares (moneda oficial)","plataformas_top":"WhatsApp, Instagram, Facebook, TikTok","pagos_locales":"tarjetas, transferencias, Yappy","timezone":"GMT-5","idioma":"es","fechas_clave":"Black Friday, Navidad, Carnaval"},
        "Guatemala": {"moneda":"Q","moneda_nombre":"Quetzales","plataformas_top":"WhatsApp, Facebook, Instagram, TikTok","pagos_locales":"tarjetas, transferencias, Tigo Money","timezone":"GMT-6","idioma":"es","fechas_clave":"Black Friday, Navidad, 15 de Septiembre"},
        "Honduras":  {"moneda":"L","moneda_nombre":"Lempiras","plataformas_top":"WhatsApp, Facebook, Instagram, TikTok","pagos_locales":"tarjetas, transferencias, Tigo Money","timezone":"GMT-6","idioma":"es","fechas_clave":"Black Friday, Navidad, 15 de Septiembre"},
        "El Salvador":{"moneda":"$","moneda_nombre":"Dólares (moneda oficial)","plataformas_top":"WhatsApp, Facebook, Instagram, TikTok","pagos_locales":"tarjetas, transferencias, Bitcoin (legal)","timezone":"GMT-6","idioma":"es","fechas_clave":"Black Friday, Navidad, 15 de Septiembre"},
        "Nicaragua": {"moneda":"C$","moneda_nombre":"Córdobas","plataformas_top":"WhatsApp, Facebook, Instagram, TikTok","pagos_locales":"tarjetas, transferencias","timezone":"GMT-6","idioma":"es","fechas_clave":"Black Friday, Navidad, 19 de Julio"},
        "República Dominicana":{"moneda":"RD$","moneda_nombre":"Pesos dominicanos","plataformas_top":"WhatsApp, Instagram, Facebook, TikTok","pagos_locales":"tarjetas, transferencias bancarias","timezone":"GMT-4","idioma":"es","fechas_clave":"Black Friday, Navidad, 27 de Febrero"},
        "Puerto Rico":{"moneda":"$","moneda_nombre":"US Dollars","plataformas_top":"Instagram, TikTok, Facebook, WhatsApp","pagos_locales":"PayPal, tarjetas, Venmo","timezone":"GMT-4","idioma":"es","fechas_clave":"Black Friday, Navidad, Fiestas San Sebastián (ene)"},
        "Cuba":      {"moneda":"CUP $","moneda_nombre":"Pesos cubanos","plataformas_top":"WhatsApp, Facebook, Instagram","pagos_locales":"efectivo, transferencias","timezone":"GMT-5","idioma":"es","fechas_clave":"Navidad, Año Nuevo, 26 de Julio"},
    }
    for _k in _ctx:
        if _k.lower() in _p.lower():
            return _ctx[_k]
    return {"moneda":"$","moneda_nombre":"USD","plataformas_top":"Instagram, TikTok, Facebook, WhatsApp, YouTube","pagos_locales":"tarjetas internacionales Visa/Mastercard, PayPal","timezone":"GMT-5","idioma":"es","fechas_clave":"Black Friday (nov), Navidad (dic), fin de año"}


# =========================
def construir_contexto_base(pais, moneda, idioma, reglas_marca):
    """CONTEXTO_BASE que se inyecta al inicio de todos los prompts (CAMBIO 3)."""
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


def scrapear_url(url):
    """CAMBIO 5: scraping real de una URL con requests + BeautifulSoup.
    Retorna dict con title, meta, headings, texto y productos, o {'error': msg}."""
    _en_sc = st.session_state.get("lang") == "en"
    url = (url or "").strip()
    if not url:
        return {"error": ""}
    if not url.startswith("http"):
        url = "https://" + url
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return {"error": "Falta la librería beautifulsoup4 (agregada a requirements.txt — redeploy)."}
    try:
        _resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        })
        if _resp.status_code in (403, 404):
            return {"error": ("Esa página no permite acceso o no existe (error "
                              f"{_resp.status_code}). Prueba con otra URL.") if not _en_sc
                    else f"That page blocks access or doesn't exist (error {_resp.status_code}). Try another URL."}
        _resp.raise_for_status()
        _soup = BeautifulSoup(_resp.text, "html.parser")
        for _tag in _soup(["script", "style", "noscript"]):
            _tag.decompose()
        _title = (_soup.title.string or "").strip() if _soup.title else ""
        _meta = ""
        _meta_tag = _soup.find("meta", attrs={"name": "description"})
        if _meta_tag:
            _meta = (_meta_tag.get("content") or "").strip()
        _headings = [h.get_text(" ", strip=True) for h in _soup.find_all(["h1", "h2", "h3"])[:25]]
        _texto = " ".join(_soup.get_text(" ", strip=True).split())[:8000]
        # Detectar productos/precios visibles (para Inteligencia Competitiva)
        _productos = []
        import re as _re_sc
        for _precio_m in _re_sc.finditer(r"(S/\.?|\$|USD|MXN|COP|ARS|CLP|PEN|€)\s?\d[\d.,]*", _resp.text[:60000]):
            _productos.append(_precio_m.group(0))
            if len(_productos) >= 20:
                break
        return {"title": _title, "meta": _meta, "headings": _headings,
                "texto": _texto, "productos": _productos, "url": url, "error": None}
    except requests.exceptions.Timeout:
        return {"error": "La página tardó demasiado en responder (timeout). Intenta de nuevo o usa otra URL." if not _en_sc
                else "The page took too long to respond (timeout). Try again or use another URL."}
    except requests.exceptions.RequestException:
        return {"error": "No se pudo acceder a esa URL. Verifica que esté bien escrita (ej: mitienda.com)." if not _en_sc
                else "Could not access that URL. Check it's correct (e.g. mystore.com)."}


def _scrape_a_texto(_sc):
    """Convierte el resultado de scrapear_url en texto para el prompt."""
    if not _sc or _sc.get("error") is not None:
        return ""
    _partes = [f"URL ANALIZADA: {_sc['url']}", f"TITLE: {_sc['title']}", f"META DESCRIPTION: {_sc['meta']}"]
    if _sc["headings"]:
        _partes.append("HEADINGS:\n- " + "\n- ".join(_sc["headings"]))
    if _sc.get("productos"):
        _partes.append("PRECIOS/PRODUCTOS DETECTADOS: " + ", ".join(_sc["productos"][:15]))
    _partes.append(f"TEXTO VISIBLE:\n{_sc['texto'][:6000]}")
    return "\n\n".join(_partes)


def _msg_ia_ocupada():
    if st.session_state.get("lang") == "en":
        st.warning("🐙 The AI servers are busy right now. Please try again in 1-2 minutes. Your credits were NOT charged.")
    else:
        st.warning("🐙 Los servidores de IA están ocupados en este momento. Intenta de nuevo en 1-2 minutos. NO se descontaron tus créditos.")


def generar_texto(prompt, max_out=8000, modelo=None, temperatura=None):
    import time as _time
    from datetime import datetime as _dt_rl
    if modelo is None:
        modelo = MODELO_FUERTE

    # ── Rate limiting: max 15 calls per 60 seconds per session ───────────────
    _now_rl = _dt_rl.now()
    _ultimo_reset = st.session_state.get("ultimo_reset")
    if _ultimo_reset is None or (_now_rl - _ultimo_reset).total_seconds() > 60:
        st.session_state["requests_este_minuto"] = 0
        st.session_state["ultimo_reset"] = _now_rl
    if st.session_state.get("requests_este_minuto", 0) >= 15:
        st.warning("⏳ Vas muy rápido. Espera un momento antes de continuar.")
        return ""
    st.session_state["requests_este_minuto"] = st.session_state.get("requests_este_minuto", 0) + 1

    # ── Validate prompt ────────────────────────────────────────────────
    _prompt_validado, _prompt_err = validar_input(prompt, max_chars=12000)
    if _prompt_err:
        return ""

    prompt = _prompt_validado

    _prefix = t("prompt_prefix") if st.session_state.get("lang", "es") == "en" else ""
    # Auto-inject business context when profile is filled
    _marca_ctx  = st.session_state.get("marca_guardada", "")
    _pais_ctx   = st.session_state.get("pais_guardado", "")
    _nicho_ctx  = st.session_state.get("nicho_guardado", "")
    _oferta_ctx = st.session_state.get("producto_servicio", "")
    _cliente_ctx = st.session_state.get("cliente_ideal_guardado", "")
    if any([_marca_ctx, _nicho_ctx, _oferta_ctx]):
        _ctx_negocio = (
            "CONTEXTO DEL NEGOCIO (usa esto siempre):\n"
            f"Marca: {_marca_ctx}\n"
            f"País: {_pais_ctx}\n"
            f"Nicho: {_nicho_ctx}\n"
            f"Oferta principal: {_oferta_ctx}\n"
            f"Cliente ideal: {_cliente_ctx[:500]}\n\n"
        )
        prompt = _ctx_negocio + prompt

    # ── Local market context (PASO 3) ──────────────────────────────────────
    _ciudad_ctx = st.session_state.get("ciudad_guardada", "") or st.session_state.get("ciudad", "")
    _ctx_pais   = get_contexto_pais(_pais_ctx)
    _lugar      = _ciudad_ctx if _ciudad_ctx else _pais_ctx
    _ctx_local  = (
        f"UBICACIÓN DEL NEGOCIO:\n"
        f"País: {_pais_ctx}\n"
        f"Ciudad: {_ciudad_ctx if _ciudad_ctx else 'No especificada'}\n\n"
        f"CONTEXTO DEL MERCADO LOCAL:\n"
        f"Moneda local: {_ctx_pais['moneda']} ({_ctx_pais['moneda_nombre']})\n"
        f"Plataformas más usadas: {_ctx_pais['plataformas_top']}\n"
        f"Métodos de pago locales: {_ctx_pais['pagos_locales']}\n"
        f"Fechas comerciales clave: {_ctx_pais['fechas_clave']}\n"
        f"Zona horaria: {_ctx_pais['timezone']}\n\n"
        f"REGLAS IMPORTANTES:\n"
        f"1. Usa SIEMPRE {_ctx_pais['moneda']} para presupuestos y precios\n"
        f"2. Recomienda las plataformas de este mercado: {_ctx_pais['plataformas_top']}\n"
        f"3. Usa referencias culturales de {_lugar}\n"
        f"4. Sugiere métodos de pago que usa la gente de este mercado\n\n"
    )
    prompt = _ctx_local + prompt

    # ── Language instruction (PASO 4) ─────────────────────────────────────────
    # idioma_preferido has priority over country language
    _idioma_pref = st.session_state.get("idioma_preferido", "Español")
    _idioma_pais = _ctx_pais.get("idioma", "es")
    _lang_ss     = st.session_state.get("lang", "es")

    if _idioma_pref == "English" or _lang_ss == "en" or _idioma_pais == "en":
        _idioma_instruccion = (
            "IMPORTANT: Respond ONLY in English. "
            "Adapt to the user's market context. "
            f"Prices in {_ctx_pais['moneda']}.\n\n"
        )
    elif _idioma_pref == "Português" or _idioma_pais == "pt":
        _idioma_instruccion = (
            "IMPORTANTE: Responda APENAS em português. "
            "Adapte ao contexto do mercado do usuário. "
            f"Preços em {_ctx_pais['moneda']}.\n\n"
        )
    else:
        _idioma_instruccion = (
            "IMPORTANTE: Responde SOLO en español. "
            f"Usa el contexto cultural de {_lugar}. "
            f"Precios en {_ctx_pais['moneda']}.\n\n"
        )
    prompt = _idioma_instruccion + prompt

    # ── CONTEXTO_BASE (CAMBIO 3): se antepone a TODOS los prompts ─────────────
    _idioma_cb = st.session_state.get("idioma_preferido", "Español")
    _reglas_cb = st.session_state.get("reglas_marca", "")
    _colores_cb = (st.session_state.get("colores_marca") or "").strip()
    if _colores_cb:
        _reglas_cb = (_reglas_cb + "\n" if _reglas_cb else "") + f"Colores de marca: {_colores_cb}"
    prompt = construir_contexto_base(_pais_ctx or "LATAM", _ctx_pais["moneda"], _idioma_cb, _reglas_cb) + "\n" + prompt

    # ── Memoria compartida entre agentes (CAMBIO 8) ───────────────────────────
    _ctx_compartido = st.session_state.get("ctx_compartido", "")
    if _ctx_compartido:
        prompt = f"CONTEXTO DE TRABAJO PREVIO DE TU EQUIPO DE AGENTES (úsalo para ser coherente):\n{_ctx_compartido[:2500]}\n\n" + prompt

    # FIX truncamiento: Gemini 2.5 gasta parte de max_output_tokens en "thinking".
    # Piso de 6000 tokens + límite al thinking para que la respuesta visible no se corte.
    max_out = max(int(max_out or 0), 6000)
    _cfg_kwargs = {"max_output_tokens": max_out}
    if temperatura is not None:
        _cfg_kwargs["temperature"] = temperatura
    try:
        _cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=1024)
    except Exception:
        pass

    st.session_state["_ultima_gen_ok"] = False
    _ultimo_error = None
    for _intento in range(3):
        try:
            response = client.models.generate_content(
                model=modelo,
                contents=_prefix + prompt,
                config=types.GenerateContentConfig(**_cfg_kwargs)
            )
            st.session_state["_ultima_gen_ok"] = True
            return response.text
        except Exception as e:
            _ultimo_error = e
            _msg = str(e).upper()
            if "THINKING" in _msg and "thinking_config" in _cfg_kwargs:
                _cfg_kwargs.pop("thinking_config", None)
                continue
            if any(x in _msg for x in ["503", "UNAVAILABLE", "OVERLOADED", "RESOURCE_EXHAUSTED"]):
                if _intento < 2:
                    st.info("🐙 Los servidores de IA están ocupados. Reintentando en 5 segundos..." if st.session_state.get("lang") != "en" else "🐙 AI servers are busy. Retrying in 5 seconds...")
                    _time.sleep(5)
                    continue
            break
    _msg_ia_ocupada()
    return ""

SYSTEM_ANALITICO = """Eres TENTAKL, el Analista de Datos Senior del negocio del usuario.
REGLAS ABSOLUTAS:
1. Solo afirmas lo que puedes deducir directamente de los datos o inputs proporcionados.
2. Nunca inventas métricas, porcentajes, nombres de clientes, ni ejemplos específicos que no estén en el input.
3. Si no tienes datos suficientes para una sección, di explícitamente: "Datos insuficientes para esta sección."
4. Toda recomendación debe estar justificada por un dato concreto del input.
5. Usa formato estructurado con headers claros, bullet points y números exactos cuando los haya.
6. Prioriza precisión sobre creatividad. Este análisis puede afectar decisiones de negocio reales."""

def generar_analitico(prompt, max_tokens=6000):
    import time as _time_an
    _marca_ctx  = st.session_state.get("marca_guardada", "")
    _pais_ctx   = st.session_state.get("pais_guardado", "")
    _nicho_ctx  = st.session_state.get("nicho_guardado", "")
    _oferta_ctx = st.session_state.get("producto_servicio", "")
    if any([_marca_ctx, _nicho_ctx, _oferta_ctx]):
        _ctx = (
            f"CONTEXTO DEL NEGOCIO:\nMarca: {_marca_ctx}\nPaís: {_pais_ctx}\n"
            f"Nicho: {_nicho_ctx}\nOferta: {_oferta_ctx}\n\n"
        )
        prompt = _ctx + prompt

    # ── CONTEXTO_BASE (CAMBIO 3) ───────────────────────────────────────────────
    _ctx_pais_an = get_contexto_pais(_pais_ctx)
    _idioma_an = st.session_state.get("idioma_preferido", "Español")
    _reglas_an = st.session_state.get("reglas_marca", "")
    _colores_an = (st.session_state.get("colores_marca") or "").strip()
    if _colores_an:
        _reglas_an = (_reglas_an + "\n" if _reglas_an else "") + f"Colores de marca: {_colores_an}"
    prompt = construir_contexto_base(_pais_ctx or "LATAM", _ctx_pais_an["moneda"], _idioma_an, _reglas_an) + "\n" + prompt

    # FIX truncamiento: piso de 6000 tokens + límite al thinking (igual que generar_texto)
    max_tokens = max(int(max_tokens or 0), 6000)
    _cfg_an = {
        "system_instruction": SYSTEM_ANALITICO,
        "temperature": 0.0,
        "top_p": 0.1,
        "max_output_tokens": max_tokens,
    }
    try:
        _cfg_an["thinking_config"] = types.ThinkingConfig(thinking_budget=1024)
    except Exception:
        pass

    st.session_state["_ultima_gen_ok"] = False
    _ultimo_error_an = None
    for _intento_an in range(3):
        try:
            resp = client.models.generate_content(
                model=MODELO_FUERTE,
                contents=prompt,
                config=types.GenerateContentConfig(**_cfg_an)
            )
            st.session_state["_ultima_gen_ok"] = True
            return resp.text
        except Exception as e:
            _ultimo_error_an = e
            _msg_an = str(e).upper()
            if "THINKING" in _msg_an and "thinking_config" in _cfg_an:
                _cfg_an.pop("thinking_config", None)
                continue
            if any(x in _msg_an for x in ["503", "UNAVAILABLE", "OVERLOADED", "RESOURCE_EXHAUSTED"]):
                if _intento_an < 2:
                    st.info("🐙 Los servidores de IA están ocupados. Reintentando en 5 segundos..." if st.session_state.get("lang") != "en" else "🐙 AI servers are busy. Retrying in 5 seconds...")
                    _time_an.sleep(5)
                    continue
            break
    _msg_ia_ocupada()
    return ""

def generar_imagen_openai(prompt_descripcion, marca, nicho, pais,
                          formato="1024x1024", calidad="medium",
                          imagen_referencia_url=None, imagen_referencia_bytes=None):
    import base64, io
    try:
        _oai_key = st.secrets.get("OPENAI_API_KEY", "")
        if not _oai_key:
            return None, "sin_api_key"
        _oai_client = OpenAIClient(api_key=_oai_key)

        # Colores de marca persistentes (assets de marca) al prompt
        _colores_bm = (st.session_state.get("colores_marca") or "").strip()
        if _colores_bm:
            prompt_descripcion = prompt_descripcion + f"\nBrand color palette to respect in the design: {_colores_bm}."

        if imagen_referencia_bytes or imagen_referencia_url:
            if imagen_referencia_bytes:
                _img_bytes = imagen_referencia_bytes
            else:
                import requests as _req_img
                _img_resp = _req_img.get(imagen_referencia_url, timeout=10)
                _img_bytes = _img_resp.content
            _img_file = io.BytesIO(_img_bytes)
            _img_file.name = "product.png"
            response = _oai_client.images.edit(
                model="gpt-image-2",
                image=_img_file,
                prompt=prompt_descripcion,
                size=formato,
                quality=calidad,
            )
        else:
            response = _oai_client.images.generate(
                model="gpt-image-2",
                prompt=prompt_descripcion,
                size=formato,
                quality=calidad,
                n=1,
                output_format="png"
            )

        img_b64 = response.data[0].b64_json
        if not img_b64:
            img_b64 = response.data[0].url
        return img_b64, None
    except Exception as e:
        return None, str(e)


# ── CREATIVE DIRECTION ENGINE ────────────────────────────────────────────────
_CD_OBJETIVOS = {
    "venta":      "high-conversion ecommerce advertisement, urgent purchase intent, CTA-driven composition",
    "ventas":     "high-conversion ecommerce advertisement, urgent purchase intent, CTA-driven composition",
    "descuento":  "high-urgency promotional sale ad, price-dominant hierarchy, aggressive conversion focus",
    "oferta":     "high-urgency promotional sale ad, price-dominant hierarchy, aggressive conversion focus",
    "branding":   "premium brand awareness campaign, aspirational storytelling, emotional brand connection",
    "lanzamiento":"exciting product launch campaign, anticipation and desire, reveal moment composition",
    "viral":      "viral social media campaign, bold visual impact, thumb-stopping shareability",
    "lujo":       "luxury premium advertising campaign, exclusivity and desire, whisper-marketing aesthetic",
    "autoridad":  "professional authority branding, trust and expertise positioning, confident credibility",
    "fiesta":     "festive celebratory campaign, joyful cultural energy, patriotic pride and celebration",
    "fiestas":    "festive celebratory campaign, joyful cultural energy, patriotic pride and celebration",
    "patria":     "patriotic festive campaign, national pride, bold cultural color identity",
    "patrias":    "patriotic festive campaign, national pride, bold cultural color identity",
}

_CD_ESTILOS = {
    "wellness":    "premium wellness editorial, clean scandinavian minimalism, warm healing light, organic texture",
    "maca":        "premium peruvian superfood aesthetic, earthy rich tones, powerful masculine energy direction",
    "suplemento":  "premium supplement commercial, powerful clinical-clean style, masculine performance energy",
    "suplementos": "premium supplement commercial, powerful clinical-clean style, masculine performance energy",
    "fitness":     "Nike commercial campaign aesthetic, explosive dynamic energy, bold athletic hero shot",
    "deporte":     "Nike commercial campaign aesthetic, explosive dynamic energy, bold athletic hero shot",
    "deportes":    "Nike commercial campaign aesthetic, explosive dynamic energy, bold athletic hero shot",
    "food":        "Michelin-star food editorial photography, warm appetizing light, perfect plating presentation",
    "comida":      "high-end food commercial photography, warm appetizing light, perfect food styling",
    "restaurante": "upscale restaurant editorial, intimate warm amber atmosphere, food styling perfection",
    "moda":        "Vogue editorial fashion campaign, high-contrast dramatic lighting, elegant asymmetric composition",
    "ropa":        "editorial fashion campaign, clean lifestyle aesthetic, aspirational wardrobe narrative",
    "prendas":     "editorial fashion campaign, clean lifestyle aesthetic, aspirational wardrobe narrative",
    "polo":        "clean lifestyle fashion campaign, relatable everyday aspirational aesthetic",
    "tech":        "Stripe and Linear startup aesthetic, clean minimal modern product-forward visual",
    "tecnologia":  "Stripe and Linear startup aesthetic, clean minimal modern product-forward visual",
    "inmueble":    "luxury real estate advertising, architectural beauty, aspirational lifestyle photography",
    "inmuebles":   "luxury real estate advertising, architectural beauty, aspirational lifestyle photography",
    "joyas":       "luxury jewelry advertising, intimate close-up, dramatic side lighting on precious materials",
    "joya":        "luxury jewelry advertising, intimate close-up, dramatic side lighting on precious materials",
    "perfume":     "luxury perfume advertising, artistic abstract composition, sensual premium atmosphere",
    "cafe":        "specialty coffee artisan photography, rich dark tones, steam and warmth atmosphere",
    "natural":     "organic wellness brand, clean earthy authentic tones, honest premium feel",
    "organico":    "organic wellness brand, clean earthy authentic tones, honest premium feel",
    "skin":        "luxury skincare editorial, clean dewy textures, soft clinical-premium aesthetic",
    "crema":       "luxury skincare editorial, clean dewy textures, soft clinical-premium aesthetic",
}

_CD_EMOCIONES = {
    "energia":      "explosive kinetic energy, dramatic diagonal rim lighting, bold saturated power palette",
    "lujo":         "sophisticated quiet luxury, golden hour soft directional light, muted premium earth palette",
    "paz":          "serene healing atmosphere, soft diffused window light, cool clean desaturated tonal range",
    "confianza":    "clean authoritative atmosphere, neutral confident tones, balanced structured frame",
    "poder":        "cinematic high-contrast chiaroscuro, strong shadow and bold highlight, dark dramatic tonality",
    "exclusividad": "intimate exclusive atmosphere, selective sharp focus, premium material close-up texture",
    "alegria":      "warm vibrant joyful atmosphere, bright golden natural sunlight, open expressive composition",
    "fiestas":      "festive celebratory energy, warm rich cultural colors, dynamic movement and joy",
    "patriotismo":  "patriotic national pride, bold cultural color identity, proud inspiring aspirational composition",
    "urgencia":     "high-contrast urgent composition, bold typography hierarchy, action-driving visual tension",
}

_CD_PAISES = {
    "Perú":      "peruvian cultural richness, andean warmth and color, vibrant heritage identity",
    "Colombia":  "colombian vibrant energy, tropical luxury atmosphere, warm caribbean premium mood",
    "México":    "rich mexican visual culture, warm deep earth tones, bold cultural pride and craft",
    "Argentina": "european-latin sophisticated elegance, premium urban cosmopolitan feel",
    "Chile":     "clean modern latin minimalism, premium patagonian aesthetic, cool fresh precision",
    "España":    "mediterranean european warmth, sophisticated iberian premium, golden warm light",
    "Brasil":    "vibrant tropical luxury, bold brazilian premium energy, warm golden atmosphere",
    "USA":       "american aspirational lifestyle, clean premium commercial aesthetic, confident ambition",
    "default":   "international premium commercial aesthetic, global luxury standard, universal appeal",
}

_CD_CALIDAD = (
    "ultra realistic, commercial photography grade, cinematic three-point lighting setup, "
    "editorial advertising style, professional advertising aesthetics, "
    "high-end spatial composition, selective depth of field with creamy bokeh background, "
    "shot on Sony A7R IV with 85mm f/1.4 lens, studio-grade lighting rig, "
    "photorealistic rendering, ultra-sharp foreground focus, 8K resolution, "
    "color graded, no AI artifacts, no distortion, no stock photo feel"
)

CREATIVE_DIRECTOR_PROMPT = """You are an elite creative director and advertising agency specialized in generating premium marketing campaigns.

Your task is NOT to generate simple AI images.
Your task is to generate HIGH-CONVERTING ADVERTISEMENTS that look like they were created by Apple, Nike, Adidas, Stripe, Notion, Luxury ecommerce brands.

PROJECT CONTEXT:
Brand: {marca}
Business Type: {nicho}
Country: {pais}
Platform: {plataforma}
Campaign Goal: {objetivo}
Audience: {cliente_ideal}
User Request: {pedido_usuario}

VISUAL STYLE RULES:
Always prioritize:
- cinematic lighting
- premium composition
- luxury branding
- emotional storytelling
- advertising realism
- modern commercial photography
- high-end editorial quality
- high-conversion marketing aesthetic

NEVER generate:
- generic AI art
- random stock image look
- low-quality compositions
- cluttered scenes
- amateur design

VISUAL QUALITY:
ultra realistic, commercial photography, cinematic lighting, editorial advertising style, high-end composition, professional branding, depth of field, luxury atmosphere, dramatic lighting, premium campaign aesthetic, shot on Sony A7R IV, social media advertising quality, award-winning commercial photography

COMPOSITION RULES:
If product-based:
- hero product centered composition
- professional product placement
- minimal distractions
- premium ecommerce aesthetic

If lifestyle-based:
- emotional storytelling
- aspirational lifestyle
- luxury commercial atmosphere

If SaaS/startup:
- futuristic startup branding
- premium workspace atmosphere
- modern UI-inspired aesthetics

MARKETING RULES:
The image must:
- attract attention instantly
- feel premium and trustworthy
- increase conversions
- feel emotionally powerful
- look like a real paid ad campaign

TYPOGRAPHY RULES:
{typography_rules}

OUTPUT: Generate ONE premium advertising campaign image that feels cinematic, emotionally powerful, commercially optimized, visually premium, globally competitive."""


def _sanitizar(texto, max_chars=3000):
    texto = (texto or "").strip()[:max_chars]
    texto = texto.replace('<', '').replace('>', '')
    return texto

def validar_input(texto, max_chars=3000):
    """Valida y sanitiza input antes de enviar a Gemini. Retorna (texto_limpio, error|None)."""
    if not texto or not str(texto).strip():
        return None, "Campo vacío"
    texto = str(texto).strip()[:max_chars]
    texto = texto.replace('<script', '')
    texto = texto.replace('</script', '')
    texto = texto.replace('javascript:', '')
    texto = texto.replace('<iframe', '')
    return texto, None

def generar_multimodal(prompt, mime_type, file_bytes, temperatura=None, max_out=None):
    try:
        cfg = {}
        if temperatura is not None:
            cfg["temperature"] = temperatura
        if max_out is not None:
            cfg["max_output_tokens"] = max_out
        response = client.models.generate_content(
            model=MODELO_FUERTE,
            contents=[
                prompt,
                types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
            ],
            config=types.GenerateContentConfig(**cfg)
        )
        return response.text
    except Exception as e:
        return f"❌ Error en Auditoría Visual: {e}"

# ── POST-GENERATION EDIT PANEL ──────────────────────────────────────────────
def _panel_edicion(resultado, key_suffix, max_tokens=6000):
    if not resultado or str(resultado).startswith("❌"):
        return
    st.divider()
    st.subheader("¿Qué quieres hacer con este resultado?")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("✏ Mejorar este resultado", key=f"btn_ed_mejorar_{key_suffix}"):
            st.session_state[f"ed_modo_{key_suffix}"] = "mejorar"
            st.session_state[f"ed_orig_{key_suffix}"] = resultado
    with col2:
        if st.button("➕ Agregar información", key=f"btn_ed_agregar_{key_suffix}"):
            st.session_state[f"ed_modo_{key_suffix}"] = "agregar"
            st.session_state[f"ed_orig_{key_suffix}"] = resultado
    with col3:
        if st.button("🔄 Generar versión diferente", key=f"btn_ed_regen_{key_suffix}"):
            st.session_state[f"ed_modo_{key_suffix}"] = "regenerar"
            st.session_state[f"ed_orig_{key_suffix}"] = resultado
    _modo = st.session_state.get(f"ed_modo_{key_suffix}")
    _orig = st.session_state.get(f"ed_orig_{key_suffix}", resultado)
    if _modo == "mejorar":
        instrucciones = st.text_area(
            "¿Qué cambios quieres?",
            placeholder="Ej: Hazlo más corto, cambia el tono a más formal, enfócalo más en precios...",
            height=100, key=f"ed_instruc_{key_suffix}"
        )
        if st.button("Aplicar cambios", key=f"btn_ed_aplicar_{key_suffix}"):
            if instrucciones.strip():
                _prompt_ed = (f"Tienes este contenido:\n{_orig}\n\n"
                              f"El usuario quiere estos cambios:\n{instrucciones}\n\n"
                              f"Aplica los cambios manteniendo la estructura y calidad del original.\n"
                              f"Entrega el contenido completo corregido.")
                with st.spinner("Aplicando cambios..."):
                    _nuevo = generar_texto(_prompt_ed, max_out=max_tokens)
                if _nuevo and not _nuevo.startswith("❌"):
                    st.markdown(_nuevo)
                    st.session_state[f"ed_modo_{key_suffix}"] = None
    elif _modo == "agregar":
        info_adicional = st.text_area(
            "¿Qué información quieres agregar?",
            placeholder="Ej: Agrega que tenemos envío gratis, menciona el precio S/49, incluye el teléfono de contacto...",
            height=100, key=f"ed_info_{key_suffix}"
        )
        if st.button("Incorporar información", key=f"btn_ed_incorp_{key_suffix}"):
            if info_adicional.strip():
                _prompt_ag = (f"Tienes este contenido:\n{_orig}\n\n"
                              f"Incorpora esta información adicional de forma natural:\n{info_adicional}\n\n"
                              f"Entrega el contenido completo actualizado.")
                with st.spinner("Incorporando información..."):
                    _nuevo = generar_texto(_prompt_ag, max_out=max_tokens)
                if _nuevo and not _nuevo.startswith("❌"):
                    st.markdown(_nuevo)
                    st.session_state[f"ed_modo_{key_suffix}"] = None
    elif _modo == "regenerar":
        _prompt_orig = st.session_state.get(f"_ed_prompt_{key_suffix}")
        if _prompt_orig:
            with st.spinner("Generando versión diferente..."):
                _nuevo = generar_texto(_prompt_orig, max_out=max_tokens)
            if _nuevo and not _nuevo.startswith("❌"):
                st.markdown(_nuevo)
                st.session_state[f"_ed_{key_suffix}"] = _nuevo
        else:
            st.info("Para generar una versión diferente, usa el botón de generación original.")
        st.session_state[f"ed_modo_{key_suffix}"] = None

# =========================
# SUPABASE: USUARIOS
# =========================
def db_upsert_usuario(email: str, plan: str, creditos_usados: int, extra: dict = None):
    if not supabase:
        return
    try:
        payload = {
            "email": email,
            "plan": plan,
            "creditos_usados": int(creditos_usados),
        }
        if extra:
            payload.update(extra)
        supabase.table("usuarios").upsert(payload, on_conflict="email").execute()
    except Exception:
        st.warning("No se pudo guardar en Supabase (usuarios).")

def db_get_usuario(email: str):
    if not supabase:
        return None
    try:
        res = supabase.table("usuarios").select("*").eq("email", email).limit(1).execute()
        data = res.data or []
        return data[0] if data else None
    except Exception as e:
        st.warning("No se pudo leer usuario en Supabase.")
        st.exception(e)
        return None

ADMIN_EMAILS = {"jairh798@gmail.com"}

def asegurar_usuario_desde_db():
    """Sincroniza el usuario desde la DB. Ya NO existe el plan Demo:
    - Si el correo existe → login (aunque no tenga créditos: 1 cuenta Free por correo).
    - Si no existe → NO se crea automáticamente; requiere aceptar T&C (CAMBIO 10)."""
    email = st.session_state.get("user_email", "").strip().lower()
    if email and not st.session_state.get("user_sincronizado", False):
        datos = db_get_usuario(email)
        if datos:
            _plan_db = datos.get("plan", "Free")
            if _plan_db == "Demo":  # migrar cuentas Demo legadas a Free
                _plan_db = "Free"
                db_upsert_usuario(email, "Free", int(datos.get("creditos_usados", 0) or 0))
            st.session_state.plan = _plan_db
            st.session_state.usados = int(datos.get("creditos_usados", 0) or 0)
            st.session_state.creditos_extra = int(datos.get("creditos_extra", 0) or 0)
            st.session_state.imagenes_usadas = int(datos.get("imagenes_usadas", 0) or 0)
            st.session_state.imagenes_usadas_hoy = int(datos.get("imagenes_usadas_hoy", 0) or 0)
            st.session_state.fecha_ultimo_uso_imagen = datos.get("fecha_ultimo_uso_imagen") or ""
            st.session_state.encuesta_completada = bool(datos.get("encuesta_completada", False))
            st.session_state["_cuenta_pendiente_tc"] = False
            st.session_state.user_sincronizado = True
        else:
            # Cuenta nueva: pedir aceptación de T&C antes de crearla
            st.session_state["_cuenta_pendiente_tc"] = True
        if email in ADMIN_EMAILS:
            st.session_state.plan = "Admin"
            st.session_state.usados = 0
            st.session_state["_cuenta_pendiente_tc"] = False
            st.session_state.user_sincronizado = True

def crear_cuenta_free(email):
    """Crea la cuenta Free (50 créditos, 2 imágenes low, una única vez) tras aceptar T&C."""
    db_upsert_usuario(email, "Free", 0, extra={
        "fecha_aceptacion_tc": dt.now(timezone.utc).isoformat(),
    })
    st.session_state.plan = "Free"
    st.session_state.usados = 0
    st.session_state.creditos_extra = 0
    st.session_state.imagenes_usadas = 0
    st.session_state.imagenes_usadas_hoy = 0
    st.session_state.encuesta_completada = False
    st.session_state["_cuenta_pendiente_tc"] = False
    st.session_state.user_sincronizado = True

# =========================
# SUPABASE: PERFIL NEGOCIO
# =========================
def db_get_perfil_negocio(user_email: str):
    if not supabase or not user_email:
        return None
    try:
        res = (
            supabase
            .table("perfil_negocio")
            .select("*")
            .eq("user_email", user_email)
            .limit(1)
            .execute()
        )
        data = res.data or []
        return data[0] if data else None
    except Exception as e:
        st.warning("No se pudo leer perfil_negocio.")
        st.exception(e)
        return None

def db_upsert_perfil_negocio(
    user_email: str,
    marca: str,
    pais: str,
    ciudad: str,
    nicho: str,
    cliente_ideal: str,
    oferta_principal: str = "",
    ticket_promedio: str = "",
    objetivo_principal: str = "",
    idioma: str = "Español",
):
    if not supabase or not user_email:
        return
    try:
        existente = (
            supabase
            .table("perfil_negocio")
            .select("id")
            .eq("user_email", user_email)
            .limit(1)
            .execute()
        )
        data = existente.data or []
        payload = {
            "user_email": user_email,
            "marca": marca,
            "pais": pais,
            "ciudad": ciudad,
            "nicho": nicho,
            "cliente_ideal": cliente_ideal,
            "oferta_principal": oferta_principal,
            "ticket_promedio": ticket_promedio,
            "objetivo_principal": objetivo_principal,
            "idioma": idioma,
            "updated_at": dt.now(timezone.utc).isoformat(),
        }
        if data:
            perfil_id = data[0]["id"]
            supabase.table("perfil_negocio").update(payload).eq("id", perfil_id).execute()
        else:
            supabase.table("perfil_negocio").insert(payload).execute()
    except Exception as e:
        st.warning("No se pudo guardar perfil_negocio.")
        st.exception(e)

def cargar_perfil_desde_db():
    user_email = (st.session_state.get("user_email") or "").strip().lower()
    if not user_email or st.session_state.get("perfil_cargado", False):
        return
    try:
        perfil = db_get_perfil_negocio(user_email)
    except Exception:
        return  # Don't mark as loaded — will retry next run
    if perfil:
        st.session_state.marca_guardada       = perfil.get("marca", "") or ""
        st.session_state.pais_guardado        = perfil.get("pais", "Perú 🇵🇪") or "Perú 🇵🇪"
        st.session_state.ciudad_guardada      = perfil.get("ciudad", "") or ""
        st.session_state.nicho_guardado       = perfil.get("nicho", "") or ""
        st.session_state.cliente_ideal_guardado = perfil.get("cliente_ideal", "") or ""
        st.session_state.producto_servicio    = perfil.get("oferta_principal", "") or ""
        st.session_state.reglas_marca         = perfil.get("reglas_marca", "") or ""
        st.session_state.logo_url             = perfil.get("logo_url", "") or ""
        st.session_state.colores_marca        = perfil.get("colores_marca", "") or ""
        _idioma_db = perfil.get("idioma", "Español") or "Español"
        if _idioma_db not in ("Español", "English", "Português"):
            _idioma_db = "Español"
        st.session_state.idioma_preferido = _idioma_db
        if _idioma_db == "English":
            st.session_state["lang"] = "en"
        else:
            st.session_state["lang"] = "es"
    st.session_state.perfil_cargado = True


def db_guardar_reglas_marca(user_email: str, reglas: str):
    if not supabase or not user_email:
        return
    try:
        existente = (
            supabase.table("perfil_negocio")
            .select("id")
            .eq("user_email", user_email)
            .limit(1)
            .execute()
        )
        data = existente.data or []
        if data:
            supabase.table("perfil_negocio").update({"reglas_marca": reglas}).eq("id", data[0]["id"]).execute()
        else:
            supabase.table("perfil_negocio").insert({"user_email": user_email, "reglas_marca": reglas}).execute()
    except Exception:
        pass


# =========================
# UI: GESTIÓN DE CATÁLOGO
# =========================
def _mostrar_fuente_agregar(fuente_catalogo, moneda_cat, user_email_cat):
    """Muestra UI para actualizar catálogo desde distintas fuentes."""
    pass  # reuses the same logic shown in MODO 2 above, user switches to "Actualizar"

def _mostrar_gestion_catalogo(user_email_cat, catalogo_guardado, moneda_cat):
    st.markdown("### 📦 Mi Catálogo")
    col_add1, col_add2, col_add3 = st.columns([2, 1, 1])
    with col_add1:
        nuevo_nombre = st.text_input("Nombre del producto:", key="gc_nuevo_nombre")
    with col_add2:
        nuevo_precio = st.text_input("Precio:", key="gc_nuevo_precio")
    with col_add3:
        st.write("")
        st.write("")
        if st.button("➕ Agregar", key="gc_btn_agregar"):
            if nuevo_nombre.strip():
                ok = db_guardar_producto(user_email_cat, nuevo_nombre.strip(), nuevo_precio.strip(), fuente="manual")
                if ok:
                    st.session_state["catalogo_db"] = db_get_catalogo(user_email_cat)
                    st.success(f"Producto '{nuevo_nombre}' agregado.")
                    st.rerun()

    st.markdown("---")
    todos = db_get_catalogo_todos(user_email_cat)
    if not todos:
        st.info("No hay productos en tu catálogo.")
        return
    for prod in todos:
        pid = prod["id"]
        activo = prod.get("activo", True)
        c1, c2, c3, c4, c5 = st.columns([3, 2, 1, 1, 1])
        with c1:
            nuevo_n = st.text_input("", value=prod.get("nombre",""), key=f"gc_n_{pid}", label_visibility="collapsed")
        with c2:
            nuevo_p = st.text_input("", value=prod.get("precio",""), key=f"gc_p_{pid}", label_visibility="collapsed")
        with c3:
            if st.button("💾", key=f"gc_save_{pid}", help="Guardar cambios"):
                db_actualizar_producto(pid, {"nombre": nuevo_n, "precio": nuevo_p})
                st.session_state["catalogo_db"] = db_get_catalogo(user_email_cat)
                st.rerun()
        with c4:
            label_toggle = "✅" if activo else "❌"
            if st.button(label_toggle, key=f"gc_tog_{pid}", help="Activar/Desactivar"):
                db_actualizar_producto(pid, {"activo": not activo})
                st.session_state["catalogo_db"] = db_get_catalogo(user_email_cat)
                st.rerun()
        with c5:
            if st.button("🗑", key=f"gc_del_{pid}", help="Eliminar"):
                db_eliminar_producto(pid)
                st.session_state["catalogo_db"] = db_get_catalogo(user_email_cat)
                st.rerun()



# =========================
# SUPABASE: CATÁLOGO
# =========================
def db_get_catalogo(user_email: str):
    if not supabase or not user_email:
        return []
    try:
        res = (
            supabase.table("catalogo_productos")
            .select("*")
            .eq("user_email", user_email)
            .eq("activo", True)
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        return []

def db_get_catalogo_todos(user_email: str):
    if not supabase or not user_email:
        return []
    try:
        res = (
            supabase.table("catalogo_productos")
            .select("*")
            .eq("user_email", user_email)
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        return []

def db_guardar_producto(user_email: str, nombre: str, precio: str = "", descripcion: str = "", categoria: str = "", fuente: str = "manual", imagen_url: str = ""):
    if not supabase or not user_email:
        return False
    try:
        _payload_prod = {
            "user_email": user_email,
            "nombre": nombre,
            "precio": precio,
            "descripcion": descripcion,
            "categoria": categoria,
            "fuente": fuente,
            "activo": True,
            "updated_at": dt.now(timezone.utc).isoformat(),
        }
        if imagen_url:
            _payload_prod["imagen_url"] = imagen_url
        supabase.table("catalogo_productos").insert(_payload_prod).execute()
        return True
    except Exception as e:
        return False


def db_actualizar_imagenes_desde_tienda(email):
    """Tras sincronizar la tienda, guarda la imagen_url de cada producto del
    catálogo haciendo match por nombre con los productos de la tienda conectada."""
    if not supabase or not email:
        return 0
    try:
        _prods_t = obtener_productos_tienda(email) or []
    except Exception:
        return 0
    _mapa_img = {(p.get("nombre") or "").strip().lower(): p.get("foto_url")
                 for p in _prods_t if p.get("foto_url")}
    if not _mapa_img:
        return 0
    _n_act = 0
    try:
        _rows_c = (supabase.table("catalogo_productos")
                   .select("id,nombre,imagen_url")
                   .eq("user_email", email).execute().data or [])
        for _r_c in _rows_c:
            if not (_r_c.get("imagen_url") or "").strip():
                _url_c = _mapa_img.get((_r_c.get("nombre") or "").strip().lower())
                if _url_c:
                    supabase.table("catalogo_productos").update(
                        {"imagen_url": _url_c}).eq("id", _r_c["id"]).execute()
                    _n_act += 1
    except Exception:
        pass
    return _n_act


def db_guardar_asset_marca(email, campo, valor):
    """Guarda logo_url o colores_marca en perfil_negocio (update o insert)."""
    if not supabase or not email or campo not in ("logo_url", "colores_marca"):
        return False
    try:
        _ex_am = (supabase.table("perfil_negocio").select("id")
                  .eq("user_email", email).limit(1).execute().data or [])
        if _ex_am:
            supabase.table("perfil_negocio").update({campo: valor}).eq("id", _ex_am[0]["id"]).execute()
        else:
            supabase.table("perfil_negocio").insert({"user_email": email, campo: valor}).execute()
        return True
    except Exception:
        return False

def db_guardar_catalogo_lista(user_email: str, productos: list, fuente: str = "manual"):
    """Inserta lista de dicts {nombre, precio, descripcion} en Supabase."""
    if not supabase or not user_email or not productos:
        return 0
    guardados = 0
    for p in productos:
        ok = db_guardar_producto(
            user_email,
            nombre=p.get("nombre", ""),
            precio=p.get("precio", ""),
            descripcion=p.get("descripcion", ""),
            fuente=fuente,
        )
        if ok:
            guardados += 1
    return guardados

def db_actualizar_producto(producto_id: int, campos: dict):
    if not supabase:
        return False
    try:
        campos["updated_at"] = dt.now(timezone.utc).isoformat()
        supabase.table("catalogo_productos").update(campos).eq("id", producto_id).execute()
        return True
    except Exception as e:
        return False

def db_eliminar_producto(producto_id: int):
    if not supabase:
        return False
    try:
        supabase.table("catalogo_productos").delete().eq("id", producto_id).execute()
        return True
    except Exception as e:
        return False

def db_borrar_catalogo(user_email: str):
    if not supabase or not user_email:
        return False
    try:
        supabase.table("catalogo_productos").delete().eq("user_email", user_email).execute()
        return True
    except Exception as e:
        return False


# =========================
# SUPABASE: TIENDA
# =========================
def guardar_config_tienda(email, plataforma, url, ck, cs):
    if not supabase:
        raise RuntimeError("Supabase no inicializado")
    if not email:
        raise ValueError("Email vacío — inicia sesión primero")
    api_key = f"{ck}|{cs}"
    existing = supabase.table("integraciones_tienda")\
        .select("id")\
        .eq("user_email", email)\
        .execute()
    datos = {
        "user_email": email,
        "plataforma": plataforma,
        "url_tienda": url,
        "api_key": api_key,
        "activa": True,
    }
    if existing.data:
        supabase.table("integraciones_tienda")\
            .update(datos)\
            .eq("user_email", email)\
            .execute()
    else:
        supabase.table("integraciones_tienda")\
            .insert(datos)\
            .execute()
    return True

def obtener_config_tienda(email):
    if not supabase or not email:
        return None
    try:
        result = supabase.table("integraciones_tienda")\
            .select("*")\
            .eq("user_email", email)\
            .eq("activa", True)\
            .execute()
        if result.data:
            config = result.data[0]
            claves = config["api_key"].split("|")
            return {
                "plataforma": config["plataforma"],
                "url": config["url_tienda"],
                "consumer_key": claves[0],
                "consumer_secret": claves[1] if len(claves) > 1 else "",
            }
        return None
    except Exception:
        return None

def obtener_productos_tienda(email):
    config = obtener_config_tienda(email)
    if not config:
        return None
    try:
        if config["plataforma"] == "WooCommerce":
            base = config["url"].rstrip("/")
            if not base.startswith("http"):
                base = "https://" + base
            url = f"{base}/wp-json/wc/v3/products"
            response = requests.get(
                url,
                auth=(config["consumer_key"], config["consumer_secret"]),
                params={"per_page": 100},
                timeout=15,
            )
            if response.status_code == 200:
                productos = []
                for p in response.json():
                    foto_url = ""
                    if p.get("images"):
                        foto_url = p["images"][0]["src"]
                    productos.append({
                        "nombre": p["name"],
                        "precio": p.get("price", ""),
                        "descripcion": p.get("short_description", ""),
                        "foto_url": foto_url,
                        "id": p["id"],
                    })
                return productos
            else:
                return None
    except Exception as e:
        st.error(f"Error conectando tienda: {e}")
        return None


# =========================
# SUPABASE: REPORTES
# =========================
def guardar_reporte(user_email, tipo, titulo, contenido):
    if not supabase or not user_email:
        return
    try:
        supabase.table("reportes").insert({
            "user_email": user_email,
            "cliente_id": st.session_state.get("cliente_activo_id", None) or None,
            "tipo_reporte": tipo,
            "titulo": titulo,
            "contenido": contenido
        }).execute()
    except Exception as e:
        st.warning("No se pudo guardar el reporte.")
        st.exception(e)

def obtener_ultimo_reporte_tipo(user_email, tipos, dias=30):
    """Retorna el ultimo reporte de uno de los tipos dados, dentro de N dias."""
    if not supabase or not user_email:
        return None
    try:
        from datetime import timezone as _tz
        _desde = (dt.now(_tz.utc) - timedelta(days=dias)).isoformat()
        for _tipo in (tipos if isinstance(tipos, list) else [tipos]):
            _res = (supabase.table("reportes")
                    .select("titulo,contenido,created_at,tipo_reporte")
                    .eq("user_email", user_email)
                    .eq("tipo_reporte", _tipo)
                    .gte("created_at", _desde)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute())
            if _res.data:
                return _res.data[0]
    except Exception:
        pass
    return None

def obtener_reportes(user_email):
    if not supabase or not user_email:
        return []
    try:
        query = (
            supabase
            .table("reportes")
            .select("*")
            .eq("user_email", user_email)
            .order("created_at", desc=True)
        )
        cliente_id = st.session_state.get("cliente_activo_id", "")
        if cliente_id:
            query = query.eq("cliente_id", cliente_id)
        res = query.execute()
        return res.data or []
    except Exception as e:
        st.warning("No se pudieron leer los reportes.")
        st.exception(e)
        return []

# =========================
# PLAN SEMANAL
# =========================
def obtener_semana_actual():
    hoy = dt.now()
    inicio = hoy - timedelta(days=hoy.weekday())
    fin = inicio + timedelta(days=6)
    meses = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    return f"{inicio.day} {meses[inicio.month-1]} – {fin.day} {meses[fin.month-1]}"

def guardar_plan_semanal(user_email, semana, contenido):
    if not supabase or not user_email:
        return
    try:
        supabase.table("reportes").insert({
            "user_email": user_email,
            "cliente_id": st.session_state.get("cliente_activo_id", None) or None,
            "tipo_reporte": "plan_semanal",
            "titulo": f"Plan semanal {semana}",
            "contenido": contenido
        }).execute()
    except Exception as e:
        st.warning("No se pudo guardar el plan semanal.")
        st.exception(e)

def obtener_plan_semanal(user_email, semana):
    if not supabase or not user_email:
        return None
    try:
        query = (
            supabase
            .table("reportes")
            .select("*")
            .eq("user_email", user_email)
            .eq("tipo_reporte", "plan_semanal")
            .eq("titulo", f"Plan semanal {semana}")
            .order("created_at", desc=True)
        )
        cliente_id = st.session_state.get("cliente_activo_id", "")
        if cliente_id:
            query = query.eq("cliente_id", cliente_id)
        res = query.limit(1).execute()
        data = res.data or []
        return data[0] if data else None
    except Exception as e:
        st.warning("No se pudo leer el plan semanal.")
        st.exception(e)
        return None

# =========================
# CLIENTES (FREELANCER)
# =========================
def db_crear_cliente(user_email, nombre_cliente, marca, pais, ciudad, nicho, cliente_ideal):
    if not supabase or not user_email:
        return
    try:
        supabase.table("clientes").insert({
            "user_email": user_email,
            "nombre_cliente": nombre_cliente,
            "marca": marca,
            "pais": pais,
            "ciudad": ciudad,
            "nicho": nicho,
            "cliente_ideal": cliente_ideal
        }).execute()
    except Exception as e:
        st.warning("No se pudo crear el cliente.")
        st.exception(e)

def db_obtener_clientes(user_email):
    if not supabase or not user_email:
        return []
    try:
        res = (
            supabase
            .table("clientes")
            .select("*")
            .eq("user_email", user_email)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        st.warning("No se pudieron cargar los clientes.")
        st.exception(e)
        return []

def cargar_cliente_activo(cliente_data):
    if not cliente_data:
        return
    st.session_state.cliente_activo_id = cliente_data.get("id", "")
    st.session_state.cliente_activo_nombre = cliente_data.get("nombre_cliente", "") or ""
    st.session_state.marca_guardada = cliente_data.get("marca", "") or ""
    st.session_state.pais_guardado = cliente_data.get("pais", "Perú 🇵🇪") or "Perú 🇵🇪"
    st.session_state.ciudad_guardada = cliente_data.get("ciudad", "") or ""
    st.session_state.nicho_guardado = cliente_data.get("nicho", "") or ""
    st.session_state.cliente_ideal_guardado = cliente_data.get("cliente_ideal", "") or ""

def obtener_limite_clientes_por_plan():
    plan = st.session_state.get("plan", "Free")
    limites = {"Free": 1, "Starter": 3, "Pro": 7, "Agency": 15}
    return limites.get(plan, 1)

# =========================
# PAÍSES Y MONEDAS
# =========================
ISO_CODES = {
    "Perú 🇵🇪": "PE", "México 🇲🇽": "MX", "Colombia 🇨🇴": "CO",
    "Argentina 🇦🇷": "AR", "Chile 🇨🇱": "CL", "Brasil 🇧🇷": "BR",
    "España 🇪🇸": "ES", "USA 🇺🇸": "US", "Canadá 🇨🇦": "CA",
    "Ecuador 🇪🇨": "EC", "Bolivia 🇧🇴": "BO", "Paraguay 🇵🇾": "PY",
    "Uruguay 🇺🇾": "UY", "Venezuela 🇻🇪": "VE", "Costa Rica 🇨🇷": "CR",
    "Panamá 🇵🇦": "PA", "Guatemala 🇬🇹": "GT", "Honduras 🇭🇳": "HN",
    "El Salvador 🇸🇻": "SV", "Nicaragua 🇳🇮": "NI",
    "República Dominicana 🇩🇴": "DO", "Puerto Rico 🇵🇷": "PR",
    "Cuba 🇨🇺": "CU", "Otro / Internacional 🌍": "US"
}

PAISES_MONEDA = {
    "Perú 🇵🇪": "S/", "México 🇲🇽": "MXN $", "Colombia 🇨🇴": "COP $",
    "Argentina 🇦🇷": "ARS $", "Chile 🇨🇱": "CLP $", "Brasil 🇧🇷": "R$",
    "España 🇪🇸": "€", "USA 🇺🇸": "$", "Canadá 🇨🇦": "CAD $",
    "Ecuador 🇪🇨": "$", "Bolivia 🇧🇴": "Bs.", "Paraguay 🇵🇾": "₲",
    "Uruguay 🇺🇾": "$", "Venezuela 🇻🇪": "$", "Costa Rica 🇨🇷": "₡",
    "Panamá 🇵🇦": "$", "Guatemala 🇬🇹": "Q", "Honduras 🇭🇳": "L",
    "El Salvador 🇸🇻": "$", "Nicaragua 🇳🇮": "C$",
    "República Dominicana 🇩🇴": "RD$", "Puerto Rico 🇵🇷": "$",
    "Cuba 🇨🇺": "CUP $", "Otro / Internacional 🌍": "$"
}

# =========================
# TRENDS + YOUTUBE
# =========================
@st.cache_data(ttl=3600)
def obtener_trends(pais_label: str, nicho: str) -> dict:
    geo = ISO_CODES.get(pais_label, "US")
    pytrends = TrendReq(hl="es-ES", tz=300)
    daily = []
    try:
        df_daily = pytrends.trending_searches(pn=geo.lower())
        daily = df_daily[0].head(10).tolist()
    except Exception:
        daily = []
    related_top = []
    try:
        kw_list = [nicho[:50]]
        pytrends.build_payload(kw_list, timeframe="now 7-d", geo=geo)
        rq = pytrends.related_queries()
        if kw_list[0] in rq and rq[kw_list[0]] is not None:
            top_df = rq[kw_list[0]].get("top")
            if top_df is not None:
                related_top = top_df["query"].head(8).tolist()
    except Exception:
        related_top = []
    return {"geo": geo, "daily": daily, "related_top": related_top, "fecha": str(datetime.date.today())}

@st.cache_data(ttl=1800)
def obtener_trending_youtube(pais_label="Perú 🇵🇪"):
    if not YOUTUBE_API_KEY:
        return "⚠ No hay API Key de YouTube configurada."
    region_code = ISO_CODES.get(pais_label, "PE")
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"part": "snippet", "chart": "mostPopular", "regionCode": region_code, "maxResults": 10, "key": YOUTUBE_API_KEY}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return f"⚠ YouTube no dio datos para {region_code}."
        data = response.json()
        items = data.get("items", [])
        if not items:
            return f"No se encontraron tendencias recientes en {pais_label}."
        lista_videos = [f"- {item['snippet']['title']} ({item['snippet']['channelTitle']})" for item in items]
        return "\n".join(lista_videos)
    except Exception:
        return "⚠ Error de conexión con YouTube."


# =========================
# DISEÑO VISUAL
# =========================
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background-color: #FFFFFF; }

    /* Títulos siempre en tinta oscura, nunca rojos ni morado chillón */
    h1, h2, h3, h4 { color: #15112B !important; font-weight: 700; }
    .stMarkdown h1 span, .stMarkdown h2 span { color: #15112B !important; }
    /* Links y acentos en morado Tentakl */
    a, a:visited { color: #7C3AED !important; }

    /* Botones por defecto (secundarios): estilo suave ghost, nada de rojo */
    .stButton > button, .stDownloadButton > button {
        background: #FFFFFF !important;
        color: #15112B !important;
        border: 1.5px solid #ECE9F7 !important;
        border-radius: 12px !important;
        font-weight: 600 !important;
        box-shadow: none !important;
        transition: all 0.15s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        border-color: #7C3AED !important;
        color: #7C3AED !important;
        transform: none !important;
        box-shadow: none !important;
    }
    /* Botón primario: morado sólido (solo CTAs marcados type="primary") */
    .stButton > button[kind="primary"],
    .stButton > button[data-testid="stBaseButton-primary"] {
        background: #7C3AED !important;
        color: #FFFFFF !important;
        border: 1.5px solid #7C3AED !important;
    }
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="stBaseButton-primary"]:hover {
        background: #5B21B6 !important;
        border-color: #5B21B6 !important;
        color: #FFFFFF !important;
    }

    /* Inputs suaves */
    .stTextInput>div>div>input, .stTextArea>div>div>textarea, .stSelectbox>div>div>div {
        border-radius: 10px; border: 1px solid #ECE9F7; background-color: #FAF9FF;
    }
    /* Ocultar menú hamburguesa y footer "Made with Streamlit" */
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# =========================
# SEGURIDAD
# =========================

# =========================
# CRÉDITOS
# =========================
def creditos_restantes_usuario():
    """Créditos disponibles = créditos del plan (planes_config) + créditos extra - usados."""
    cfg = get_plan_config()
    usados = int(st.session_state.get("usados", 0) or 0)
    extra = int(st.session_state.get("creditos_extra", 0) or 0)
    return max(int(cfg["creditos"]) + extra - usados, 0)


def _mostrar_upgrade(mensaje=None):
    """Todo mensaje de límite es una oportunidad de venta, nunca un error técnico."""
    _en = st.session_state.get("lang") == "en"
    if mensaje:
        st.warning(mensaje)
    _planes_cfg = cargar_planes_config()
    _c1, _c2, _c3 = st.columns(3)
    for _col, _pl in zip((_c1, _c2, _c3), ("Starter", "Pro", "Agency")):
        _cfgp = _planes_cfg.get(_pl, _PLANES_FALLBACK[_pl])
        with _col:
            st.markdown(
                f"**{_pl}** — ${int(_cfgp['precio'])}/mes\n\n"
                f"✅ {_cfgp['creditos']} " + ("credits/month" if _en else "créditos/mes") + "\n\n"
                f"🎨 {_cfgp['imagenes_limite']} " + ("images/month" if _en else "imágenes/mes") + f" ({_cfgp['calidad_imagen']})"
            )
    st.caption("👉 tentakl.ai/planes" if not _en else "👉 tentakl.ai/plans")


def verificar_creditos(costo=1, video=False):
    _en = st.session_state.get("lang") == "en"
    restantes = creditos_restantes_usuario()
    if int(costo) > restantes:
        if _en:
            _mostrar_upgrade(f"🐙 You need **{costo}** credit(s) and you have **{restantes}** left. Upgrade to keep growing:")
        else:
            _mostrar_upgrade(f"🐙 Necesitas **{costo}** crédito(s) y te quedan **{restantes}**. Mejora tu plan para seguir creciendo:")
        # Encuesta de conversión Free (una sola vez, +15 créditos)
        if st.session_state.get("plan", "Free") == "Free" and not st.session_state.get("encuesta_completada"):
            st.session_state["_mostrar_encuesta_free"] = True
        return False
    return True


def _hoy_str():
    return dt.now().strftime("%Y-%m-%d")


def verificar_limite_imagenes():
    """Verifica límite mensual Y diario de imágenes según el plan. Retorna (ok, mensaje)."""
    _en = st.session_state.get("lang") == "en"
    cfg = get_plan_config()
    usadas_mes = int(st.session_state.get("imagenes_usadas", 0) or 0)
    lim_mes = int(cfg["imagenes_limite"])
    lim_dia = int(cfg["imagenes_limite_diario"])
    # Reset diario
    if st.session_state.get("fecha_ultimo_uso_imagen", "")[:10] != _hoy_str():
        st.session_state.imagenes_usadas_hoy = 0
    usadas_hoy = int(st.session_state.get("imagenes_usadas_hoy", 0) or 0)
    if usadas_mes >= lim_mes:
        _plan = st.session_state.get("plan", "Free")
        if _en:
            return False, f"You reached your {lim_mes} images this month 🎨 Pro gives you 20 in high quality → [Upgrade plan]"
        return False, f"Alcanzaste tus {lim_mes} imágenes del mes 🎨 En Pro tienes 20 en alta calidad → [Mejorar plan]"
    if usadas_hoy >= lim_dia:
        if _en:
            return False, f"You reached your daily limit of {lim_dia} images. Come back tomorrow or upgrade your plan 🚀"
        return False, f"Alcanzaste tu límite diario de {lim_dia} imágenes. Vuelve mañana o mejora tu plan 🚀"
    return True, ""


def registrar_uso_imagen():
    """Descuenta 1 imagen del límite mensual y diario, y persiste en usuarios."""
    st.session_state.imagenes_usadas = int(st.session_state.get("imagenes_usadas", 0) or 0) + 1
    if st.session_state.get("fecha_ultimo_uso_imagen", "")[:10] != _hoy_str():
        st.session_state.imagenes_usadas_hoy = 0
    st.session_state.imagenes_usadas_hoy = int(st.session_state.get("imagenes_usadas_hoy", 0) or 0) + 1
    st.session_state.fecha_ultimo_uso_imagen = _hoy_str()
    email = (st.session_state.get("user_email") or "").strip().lower()
    if email:
        db_upsert_usuario(email, st.session_state.get("plan", "Free"),
                          int(st.session_state.get("usados", 0) or 0), extra={
            "imagenes_usadas": st.session_state.imagenes_usadas,
            "imagenes_usadas_hoy": st.session_state.imagenes_usadas_hoy,
            "fecha_ultimo_uso_imagen": _hoy_str(),
        })

def consumir(costo=1, tipo_accion="funcion_texto"):
    # CAMBIO 9: si la última generación de IA falló, NO descontar créditos
    if st.session_state.get("_ultima_gen_ok") is False:
        st.session_state["_ultima_gen_ok"] = True
        return
    st.session_state.usados = int(st.session_state.get("usados", 0) or 0) + int(costo)
    email = (st.session_state.get("user_email") or "").strip().lower()
    if email:
        try:
            db_upsert_usuario(email, st.session_state.get("plan", "Free"), st.session_state.usados)
        except Exception:
            pass
        registrar_uso_creditos(email, tipo_accion, costo)


def registrar_uso_creditos(email, tipo_accion, creditos):
    """Registra cada consumo en la tabla uso_creditos (alimenta el dashboard admin)."""
    if not supabase or not email:
        return
    try:
        supabase.table("uso_creditos").insert({
            "user_email": email,
            "tipo_accion": tipo_accion,
            "creditos": int(creditos),
            "agente": st.session_state.get("agente_activo") or "general",
            "subfuncion": st.session_state.get("_subfuncion_activa", "") or "",
            "fecha": dt.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        pass

# =========================
# BARRA LATERAL
# =========================
with st.sidebar:
    st.markdown("<div style='font-size:46px;text-align:center;line-height:1;'>🐙</div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;font-size:22px;font-weight:700;color:#7C3AED;margin-top:2px;'>TENTAKL.AI</div>", unsafe_allow_html=True)
    st.caption("Tu equipo de marketing con IA" if st.session_state.get("lang") != "en" else "Your AI marketing team")
    st.markdown("---")
    _lang_actual = st.session_state.get("lang", "es")
    _col_es, _col_en = st.columns(2)
    with _col_es:
        if st.button("🇪🇸 Español", key="lang_es", use_container_width=True,
                     type="primary" if _lang_actual == "es" else "secondary"):
            st.session_state["lang"] = "es"
            st.rerun()
    with _col_en:
        if st.button("🇺🇸 English", key="lang_en", use_container_width=True,
                     type="primary" if _lang_actual == "en" else "secondary"):
            st.session_state["lang"] = "en"
            st.rerun()
    st.markdown("---")

    st.markdown(t("tu_cuenta"))

    # ── Restaurar sesión desde la URL (?u=email): el clic en el pulpo navega
    #    y recarga la página, esto evita que el usuario pierda su login ────────
    if not (st.session_state.get("user_email") or "").strip():
        try:
            _u_qp = st.query_params.get("u")
        except Exception:
            _u_qp = None
        if _u_qp and re.match(r'^[^@]+@[^@]+\.[^@]+$', _u_qp.strip().lower()):
            st.session_state.user_email = _u_qp.strip().lower()

    email_in = st.text_input(t("email_label"), value=st.session_state.user_email, placeholder="tu@empresa.com")

    if email_in:
        nuevo_email = email_in.strip().lower()

        # Persistir el email en la URL para sobrevivir recargas del pulpo
        try:
            if st.query_params.get("u") != nuevo_email:
                st.query_params["u"] = nuevo_email
        except Exception:
            pass

        if nuevo_email != st.session_state.get("user_email", ""):
            st.session_state.perfil_cargado = False
            st.session_state.user_sincronizado = False
            st.session_state.cliente_activo_id = ""
            st.session_state.cliente_activo_nombre = ""

        st.session_state.user_email = nuevo_email

        try:
            asegurar_usuario_desde_db()
        except Exception:
            st.warning("⚠ No se pudo sincronizar usuario con Supabase.")

        # ── CAMBIO 10: registro nuevo requiere aceptar T&C ─────────────────────
        if st.session_state.get("_cuenta_pendiente_tc") and re.match(r'^[^@]+@[^@]+\.[^@]+$', nuevo_email):
            _en_tc = st.session_state.get("lang") == "en"
            st.info("🐙 ¡Bienvenido! Crea tu cuenta Free: 50 créditos y 2 imágenes gratis, por única vez." if not _en_tc
                    else "🐙 Welcome! Create your Free account: 50 credits and 2 free images, one time only.")
            _acepta_tc = st.checkbox(
                "Acepto los Términos y Condiciones y la Política de Privacidad" if not _en_tc
                else "I accept the Terms and Conditions and the Privacy Policy",
                key="chk_acepta_tc"
            )
            if st.button("🚀 Crear mi cuenta Free" if not _en_tc else "🚀 Create my Free account", key="btn_crear_cuenta"):
                if not _acepta_tc:
                    st.error("Debes aceptar los Términos y Condiciones para crear tu cuenta." if not _en_tc
                             else "You must accept the Terms and Conditions to create your account.")
                else:
                    crear_cuenta_free(nuevo_email)
                    st.success("✅ Cuenta creada. ¡Bienvenido a Tentakl!" if not _en_tc else "✅ Account created. Welcome to Tentakl!")
                    st.rerun()

        try:
            _lang_antes = st.session_state.get("lang", "es")
            cargar_perfil_desde_db()
            if st.session_state.get("lang", "es") != _lang_antes:
                st.rerun()
        except Exception:
            st.warning("⚠ No se pudo cargar el perfil del negocio.")

    # ── Idioma preferido ────────────────────────────────────────────────────────
    _idioma_opts = ["Español", "English", "Português"]
    _idioma_actual = st.session_state.get("idioma_preferido", "Español")
    if _idioma_actual not in _idioma_opts:
        _idioma_actual = "Español"
    _idioma_sel = st.selectbox(
        "Idioma preferido:" if st.session_state.get("lang") != "en" else "Preferred language:",
        _idioma_opts,
        index=_idioma_opts.index(_idioma_actual),
        key="idioma_pref_sb",
    )
    if _idioma_sel != st.session_state.get("idioma_preferido"):
        st.session_state["idioma_preferido"] = _idioma_sel
        st.session_state["lang"] = "en" if _idioma_sel == "English" else "es"
        st.rerun()
    st.markdown("---")

    st.markdown(t("mercado"))
    lista_paises = list(ISO_CODES.keys())
    pais_default = st.session_state.get("pais_guardado", lista_paises[0])
    if pais_default not in lista_paises:
        pais_default = lista_paises[0]

    pais = st.selectbox(t("pais_label"), lista_paises, index=lista_paises.index(pais_default))
    st.session_state.pais_guardado = pais
    ciudad = st.text_input(t("ciudad_label"), value=st.session_state.get("ciudad_guardada", ""), placeholder="Ej: Lima, Medellín...")
    st.session_state.ciudad_guardada = ciudad

    # ✅ FIX: alcance siempre definido aquí en el sidebar
    if ciudad:
        alcance = f"LOCAL ({ciudad}, {pais})"
    else:
        alcance = f"NACIONAL ({pais})"

    st.session_state.alcance = alcance
    st.caption(f"🎯 Modo: {alcance}")

    st.markdown(t("negocio"))
    nombre_marca = st.text_input(t("marca_label"), value=st.session_state.get("marca_guardada", ""))
    st.session_state.marca_guardada = nombre_marca

    opciones_nicho = [
        "🏡 Inmobiliaria", "👗 Moda / Retail", "🍔 Gastronomía", "💪 Fitness / Salud",
        "⚖ Servicios Legales", "💻 Tecnología / SaaS", "🎓 Educación / Cursos",
        "🚗 Automotriz", "🎬 Marca Personal / Influencer", "✍ OTRO"
    ]
    nicho_guardado = st.session_state.get("nicho_guardado", "")
    if nicho_guardado and nicho_guardado not in opciones_nicho:
        sel_nicho_default = "✍ OTRO"
    else:
        sel_nicho_default = nicho_guardado if nicho_guardado else opciones_nicho[0]

    sel_nicho = st.selectbox(t("nicho_label"), opciones_nicho, index=opciones_nicho.index(sel_nicho_default) if sel_nicho_default in opciones_nicho else 0)
    if sel_nicho == "✍ OTRO":
        nicho = st.text_input("Describe tu nicho:", value=nicho_guardado if nicho_guardado and nicho_guardado not in opciones_nicho else "")
    else:
        nicho = sel_nicho
    st.session_state.nicho_guardado = nicho

    producto_servicio = st.text_input(
        t("que_vendes"),
        value=st.session_state.get("producto_servicio", ""),
        placeholder=t("que_vendes_ph")
    )
    st.session_state.producto_servicio = producto_servicio

    # ── ASSETS DE MARCA: logo + colores (persistentes en perfil_negocio) ──────
    _is_en_bm = st.session_state.get("lang") == "en"
    st.markdown("### 🎨 " + ("Tu marca" if not _is_en_bm else "Your brand"))
    _logo_actual_bm = (st.session_state.get("logo_url") or "").strip()
    if _logo_actual_bm:
        st.image(_logo_actual_bm, width=90,
                 caption="Logo actual" if not _is_en_bm else "Current logo")
        if st.button("🗑 " + ("Quitar logo" if not _is_en_bm else "Remove logo"), key="btn_quitar_logo"):
            _em_bm = (st.session_state.get("user_email") or "").strip().lower()
            if _em_bm:
                db_guardar_asset_marca(_em_bm, "logo_url", "")
            st.session_state["logo_url"] = ""
            st.rerun()
    _logo_up_bm = st.file_uploader(
        "Sube tu logo (opcional):" if not _is_en_bm else "Upload your logo (optional):",
        type=["png", "jpg", "jpeg", "webp"], key="logo_uploader",
    )
    if _logo_up_bm is not None:
        if st.button("💾 " + ("Guardar logo" if not _is_en_bm else "Save logo"), key="btn_guardar_logo"):
            _em_bm2 = (st.session_state.get("user_email") or "").strip().lower()
            if not _em_bm2:
                st.warning("Ingresa tu email primero." if not _is_en_bm else "Enter your email first.")
            elif _logo_up_bm.size > 10 * 1024 * 1024:
                st.error("El logo supera los 10MB." if not _is_en_bm else "The logo exceeds 10MB.")
            elif not supabase:
                st.warning("Supabase no está conectado.")
            else:
                try:
                    _ext_bm = (_logo_up_bm.name.split(".")[-1] or "png").lower()
                    _path_bm = f"{_em_bm2}/logo.{_ext_bm}"
                    supabase.storage.from_("marcas").upload(
                        _path_bm, _logo_up_bm.getvalue(),
                        {"content-type": _logo_up_bm.type or "image/png", "upsert": "true"},
                    )
                    _url_bm = supabase.storage.from_("marcas").get_public_url(_path_bm)
                    db_guardar_asset_marca(_em_bm2, "logo_url", _url_bm)
                    st.session_state["logo_url"] = _url_bm
                    st.success("✅ Logo guardado" if not _is_en_bm else "✅ Logo saved")
                    st.rerun()
                except Exception as _e_bm:
                    st.error(("No se pudo subir el logo. Verifica que el bucket 'marcas' exista en Supabase Storage. Detalle: "
                              if not _is_en_bm else
                              "Could not upload the logo. Check that the 'marcas' bucket exists in Supabase Storage. Detail: ")
                             + str(_e_bm)[:140])
    _colores_bm_in = st.text_input(
        "Colores de tu marca (opcional):" if not _is_en_bm else "Your brand colors (optional):",
        value=st.session_state.get("colores_marca", ""),
        placeholder="Ej: #7C3AED, #F59E0B", key="colores_marca_input",
    )
    st.session_state["colores_marca"] = _colores_bm_in
    _hex_bm = [c.strip() for c in _colores_bm_in.split(",") if c.strip().startswith("#") and len(c.strip()) in (4, 7)]
    if _hex_bm:
        st.markdown("".join(
            f'<span style="display:inline-block;width:22px;height:22px;border-radius:5px;'
            f'background:{_c};margin-right:5px;border:1px solid #ddd;"></span>' for _c in _hex_bm[:6]
        ), unsafe_allow_html=True)

    link_redes = st.text_input(
        t("link_redes_label"),
        value=st.session_state.get("link_redes", ""),
        placeholder=t("link_redes_ph")
    )
    st.session_state.link_redes = link_redes

    link_web = st.text_input(
        t("link_web_label"),
        value=st.session_state.get("link_web", ""),
        placeholder=t("link_web_ph")
    )
    st.session_state.link_web = link_web

    st.markdown(t("cliente_ideal_sec"))
    if st.button(t("detectar_cliente")):
        if verificar_creditos(0):
            with st.spinner("Analizando demografía..."):
                p_cliente = f"""Crea un perfil detallado del cliente ideal para este negocio:
Nicho: {nicho}
Ubicación: {alcance}

Dame un perfil completo con:
- Nombre ficticio, edad exacta y ocupación
- Ciudad y estilo de vida
- Ingresos aproximados
- Dolores principales (qué problema tiene)
- Deseos (qué quiere lograr)
- Objeciones frecuentes antes de comprar
- Redes sociales que usa y a quién sigue
- Qué contenido consume
- Cómo toma decisiones de compra

Sé muy específico, como si describieras a una persona real."""
                st.session_state.cliente_sugerido = generar_texto(p_cliente, max_out=8000)
                st.rerun()  # ✅ FIX: refresca para mostrar el resultado en el text_area

    # ✅ FIX: prioriza el guardado sobre el sugerido correctamente
    valor_cliente_ideal = st.session_state.get("cliente_ideal_guardado", "")
    if not valor_cliente_ideal:
        valor_cliente_ideal = st.session_state.get("cliente_sugerido", "")

    cliente_ideal = st.text_area(t("cliente_ideal_label"), value=valor_cliente_ideal, height=100)
    st.session_state.cliente_ideal_guardado = cliente_ideal

    if st.button(t("guardar_perfil")):
        user_email = (st.session_state.get("user_email") or "").strip().lower()
        if not user_email:
            st.warning("Ingresa tu email primero para guardar el perfil.")
        elif not re.match(r'^[^@]+@[^@]+\.[^@]+$', user_email):
            st.error("Ingresa un email v\u00e1lido. Ej: tunombre@gmail.com")
        else:
            try:
                db_upsert_perfil_negocio(
                    user_email=user_email,
                    marca=nombre_marca,
                    pais=pais,
                    ciudad=ciudad,
                    nicho=nicho,
                    cliente_ideal=cliente_ideal,
                    oferta_principal=producto_servicio,
                    idioma=st.session_state.get("idioma_preferido", "Español"),
                )
                st.session_state.marca_guardada = nombre_marca
                st.session_state.pais_guardado = pais
                st.session_state.ciudad_guardada = ciudad
                st.session_state.nicho_guardado = nicho
                st.session_state.cliente_ideal_guardado = cliente_ideal
                db_guardar_asset_marca(user_email, "colores_marca",
                                       (st.session_state.get("colores_marca") or "").strip())
                st.success("✅ Perfil guardado correctamente.")
            except Exception as e:
                st.error("No se pudo guardar el perfil.")
                st.exception(e)

    plan_actual = st.session_state.get("plan", "Free")
    st.caption(f"Plan actual: {plan_actual}" if st.session_state.get("lang") != "en" else f"Current plan: {plan_actual}")
    _cfg_sb = get_plan_config(plan_actual)
    limite = int(_cfg_sb["creditos"]) + int(st.session_state.get("creditos_extra", 0) or 0)
    usados_sidebar = int(st.session_state.get("usados", 0))
    progreso = 0.0 if plan_actual == "Admin" else (min(usados_sidebar / limite, 1.0) if limite > 0 else 0)
    restantes = max(limite - usados_sidebar, 0)
    st.progress(progreso)
    st.caption(f'{t("creditos_restantes")}: {restantes}')
    st.caption(f'{t("consumo")}: {usados_sidebar} / {limite}')
    _img_cfg_sb = int(_cfg_sb["imagenes_limite"])
    _img_usadas_sb = int(st.session_state.get("imagenes_usadas", 0) or 0)
    st.caption(("🎨 Imágenes: " if st.session_state.get("lang") != "en" else "🎨 Images: ") + f"{max(_img_cfg_sb - _img_usadas_sb, 0)}/{_img_cfg_sb}")

    # ── Banner suave cuando quedan pocos créditos (plan Free) ─────────────────
    if plan_actual == "Free" and 0 < restantes <= 10:
        st.warning(f"🐙 Te quedan {restantes} créditos. Mira los planes →" if st.session_state.get("lang") != "en"
                   else f"🐙 You have {restantes} credits left. Check out the plans →")

    # ── Encuesta Free (+15 créditos, una única vez) ────────────────────────────
    if (plan_actual == "Free" and restantes <= 0
            and not st.session_state.get("encuesta_completada")
            and (st.session_state.get("user_email") or "").strip()):
        _en_enc = st.session_state.get("lang") == "en"
        with st.expander("🎁 Gana 15 créditos extra respondiendo 3 preguntas" if not _en_enc
                         else "🎁 Earn 15 extra credits by answering 3 questions"):
            _enc_fav = st.text_input("¿Cuál fue tu función favorita?" if not _en_enc else "What was your favorite feature?", key="enc_fav")
            _enc_mej = st.text_input("¿Qué mejorarías?" if not _en_enc else "What would you improve?", key="enc_mej")
            _enc_pag = st.selectbox("¿Pagarías por Tentakl?" if not _en_enc else "Would you pay for Tentakl?",
                                    ["Sí", "Tal vez", "No"] if not _en_enc else ["Yes", "Maybe", "No"], key="enc_pag")
            if st.button("Enviar y recibir mis créditos" if not _en_enc else "Submit and get my credits", key="btn_enc_free"):
                _email_enc = (st.session_state.get("user_email") or "").strip().lower()
                try:
                    if supabase:
                        supabase.table("encuestas_free").upsert({
                            "user_email": _email_enc,
                            "funcion_favorita": _enc_fav,
                            "mejoraria": _enc_mej,
                            "pagaria": _enc_pag,
                            "fecha": dt.now(timezone.utc).isoformat(),
                        }, on_conflict="user_email").execute()
                    st.session_state.creditos_extra = int(st.session_state.get("creditos_extra", 0) or 0) + 15
                    st.session_state.encuesta_completada = True
                    db_upsert_usuario(_email_enc, "Free", usados_sidebar, extra={
                        "creditos_extra": st.session_state.creditos_extra,
                        "encuesta_completada": True,
                    })
                    st.success("✅ ¡Gracias! Tienes 15 créditos extra." if not _en_enc else "✅ Thanks! You got 15 extra credits.")
                    st.rerun()
                except Exception:
                    st.warning("No se pudo guardar la encuesta. Intenta de nuevo." if not _en_enc else "Could not save the survey. Try again.")

    # ✅ FIX: Freelancer solo aparece en planes Pro y Agency
    plan_actual_sidebar = st.session_state.get("plan", "Free")
    if plan_actual_sidebar in ["Pro", "Agency"]:
        st.markdown("### 👥 Clientes (Freelancer)")
        email_sidebar = (st.session_state.get("user_email") or "").strip().lower()
        if email_sidebar:
            clientes_disponibles = db_obtener_clientes(email_sidebar)
            nombres_clientes = ["-- Selecciona cliente --"] + [c["nombre_cliente"] for c in clientes_disponibles]
            seleccion_cliente = st.selectbox("Cliente activo:", nombres_clientes)
            if seleccion_cliente != "-- Selecciona cliente --":
                cliente_data = next((c for c in clientes_disponibles if c["nombre_cliente"] == seleccion_cliente), None)
                if cliente_data:
                    cargar_cliente_activo(cliente_data)
                    st.caption(f"Cliente activo: {st.session_state.cliente_activo_nombre}")

            st.markdown("#### ➕ Nuevo cliente")
            nuevo_nombre_cliente = st.text_input("Nombre interno del cliente:", key="nuevo_nombre_cliente")
            nueva_marca_cliente = st.text_input("Marca del cliente:", key="nueva_marca_cliente")
            nueva_ciudad_cliente = st.text_input("Ciudad del cliente:", key="nueva_ciudad_cliente")
            lista_paises_clientes = list(ISO_CODES.keys())
            nuevo_pais_cliente = st.selectbox("País del cliente:", lista_paises_clientes, key="nuevo_pais_cliente")
            opciones_nicho_freelancer = [
                "🏡 Inmobiliaria", "👗 Moda / Retail", "🍔 Gastronomía", "💪 Fitness / Salud",
                "⚖ Servicios Legales", "💻 Tecnología / SaaS", "🎓 Educación / Cursos",
                "🚗 Automotriz", "🎬 Marca Personal / Influencer", "✍ OTRO"
            ]
            nuevo_sel_nicho = st.selectbox("Nicho del cliente:", opciones_nicho_freelancer, key="nuevo_sel_nicho")
            if nuevo_sel_nicho == "✍ OTRO":
                nuevo_nicho_cliente = st.text_input("Describe el nicho:", key="nuevo_nicho_cliente")
            else:
                nuevo_nicho_cliente = nuevo_sel_nicho
            nuevo_cliente_ideal = st.text_area("Cliente ideal del cliente:", key="nuevo_cliente_ideal")
            if st.button("💾 Guardar Nuevo Cliente"):
                clientes_actuales = db_obtener_clientes(email_sidebar)
                limite_clientes = obtener_limite_clientes_por_plan()
                if len(clientes_actuales) >= limite_clientes:
                    st.warning(f"🚫 Tu plan actual permite hasta {limite_clientes} cliente(s). Mejora tu plan para agregar más.")
                elif not nuevo_nombre_cliente.strip():
                    st.warning("Pon un nombre interno para el cliente.")
                else:
                    db_crear_cliente(
                        user_email=email_sidebar,
                        nombre_cliente=nuevo_nombre_cliente.strip(),
                        marca=nueva_marca_cliente.strip(),
                        pais=nuevo_pais_cliente,
                        ciudad=nueva_ciudad_cliente.strip(),
                        nicho=nuevo_nicho_cliente.strip(),
                        cliente_ideal=nuevo_cliente_ideal.strip()
                    )
                    st.success("Cliente guardado. Recarga o vuelve a seleccionarlo en la lista.")
        else:
            st.info("Ingresa tu email para activar modo freelancer.")


# =========================
# PDF GENERATION (ReportLab)
# =========================
def generar_pdf_reportlab(titulo, contenido, email=""):
    """Genera un PDF con formato TENTAKL.AI y retorna bytes."""
    _buf = io.BytesIO()
    _doc = SimpleDocTemplate(
        _buf,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    _styles = getSampleStyleSheet()
    _rojo = colors.HexColor("#D32F2F")

    _style_header = ParagraphStyle(
        "TentaklHeader",
        parent=_styles["Heading1"],
        fontSize=22,
        textColor=_rojo,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    _style_titulo = ParagraphStyle(
        "TentaklTitulo",
        parent=_styles["Heading2"],
        fontSize=14,
        textColor=colors.black,
        spaceBefore=6,
        spaceAfter=6,
        fontName="Helvetica-Bold",
    )
    _style_meta = ParagraphStyle(
        "TentaklMeta",
        parent=_styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        spaceAfter=2,
    )
    _style_body = ParagraphStyle(
        "TentaklBody",
        parent=_styles["Normal"],
        fontSize=10,
        leading=15,
        spaceAfter=6,
        wordWrap="CJK",
    )
    _style_h2 = ParagraphStyle(
        "TentaklH2",
        parent=_styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor("#1A237E"),
        spaceBefore=10,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    _style_h3 = ParagraphStyle(
        "TentaklH3",
        parent=_styles["Heading3"],
        fontSize=11,
        textColor=colors.HexColor("#333333"),
        spaceBefore=8,
        spaceAfter=3,
        fontName="Helvetica-Bold",
    )

    _story = []

    # Encabezado TENTAKL.AI
    _story.append(Paragraph("TENTAKL.AI", _style_header))
    _story.append(HRFlowable(width="100%", thickness=2, color=_rojo, spaceAfter=6))

    # Título del reporte
    _titulo_clean = titulo.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    _story.append(Paragraph(_titulo_clean, _style_titulo))

    # Fecha y email
    from datetime import datetime as _dt2
    _story.append(Paragraph(f"Fecha: {_dt2.now().strftime('%d/%m/%Y %H:%M')}", _style_meta))
    if email:
        _story.append(Paragraph(f"Usuario: {email}", _style_meta))
    _story.append(Spacer(1, 0.15 * inch))

    # Content — parse markdown headings and paragraphs
    for _line in contenido.split("\n"):
        _raw = _line.rstrip()
        # Remove markdown emoji-like unicode that reportlab can't render safely
        # by escaping XML special chars
        _safe = _raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if _raw.startswith("## "):
            _text = _safe[3:].strip()
            _story.append(HRFlowable(width="100%", thickness=0.5,
                                     color=colors.HexColor("#CCCCCC"), spaceAfter=4))
            _story.append(Paragraph(_text, _style_h2))
        elif _raw.startswith("### "):
            _text = _safe[4:].strip()
            _story.append(Paragraph(_text, _style_h3))
        elif _raw.startswith("# "):
            _text = _safe[2:].strip()
            _story.append(Paragraph(_text, _style_titulo))
        elif _raw.startswith("---"):
            _story.append(HRFlowable(width="100%", thickness=0.5,
                                     color=colors.HexColor("#DDDDDD"), spaceAfter=4))
        elif _raw == "":
            _story.append(Spacer(1, 0.08 * inch))
        else:
            # Bold **text** — simple replacement
            import re as _re
            _safe = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _safe)
            _story.append(Paragraph(_safe, _style_body))

    # Page numbers
    def _add_page_num(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#888888"))
        _page_str = f"Página {doc.page}"
        canvas.drawRightString(
            letter[0] - 0.75 * inch,
            0.5 * inch,
            _page_str
        )
        canvas.restoreState()

    _doc.build(_story, onFirstPage=_add_page_num, onLaterPages=_add_page_num)
    return _buf.getvalue()

# ── AUTOPILOTO SUPABASE HELPERS ──────────────────────────────────────────────
def db_get_autopiloto_usos(user_email, mes):
    if not supabase or not user_email:
        return 0
    try:
        r = supabase.table("autopiloto_usos")\
            .select("usos")\
            .eq("user_email", user_email)\
            .eq("mes", mes)\
            .limit(1).execute()
        data = r.data or []
        return data[0]["usos"] if data else 0
    except Exception:
        return 0

def db_incrementar_autopiloto(user_email, mes):
    if not supabase or not user_email:
        return
    try:
        existing = supabase.table("autopiloto_usos")\
            .select("usos")\
            .eq("user_email", user_email)\
            .eq("mes", mes)\
            .limit(1).execute()
        data = existing.data or []
        if data:
            supabase.table("autopiloto_usos")\
                .update({"usos": data[0]["usos"] + 1})\
                .eq("user_email", user_email)\
                .eq("mes", mes).execute()
        else:
            supabase.table("autopiloto_usos")\
                .insert({"user_email": user_email, "mes": mes, "usos": 1}).execute()
    except Exception as _e:
        print(f"[Autopiloto] DB error: {_e}")


# =========================================================
# TENTAKL — TU EQUIPO DE 9 AGENTES (CAMBIO 2)
# =========================================================
AGENT_COLORS = {
    "estrategia": "#2563EB", "contenido": "#16A34A", "imagenes": "#F97316",
    "publicidad": "#7C3AED", "ventas": "#0D9488", "competencia": "#EC4899",
    "gestion": "#8B5CF6", "metricas": "#D4A017", "autopiloto": "#D4A017",
}

AGENTES = {
    "estrategia": {
        "emoji": "🧠", "color": "#2563EB",
        "nombre": ("Estrategia y Diagnóstico", "Strategy & Diagnosis"),
        "desc": ("Analiza tu negocio, mercado y arma tu plan", "Analyzes your business, market and builds your plan"),
        "subfunciones": [
            ("⚡ Acciones Inteligentes de Hoy", "⚡ Today's Smart Actions", "inicio", "acciones"),
            ("🩺 Auditoría Maestra del Negocio", "🩺 Master Business Audit", "inicio", "auditoria"),
            ("🔥 Radar de Tendencias Virales", "🔥 Viral Trends Radar", "inicio", "radar"),
            ("🧠 Plan de Contenido Semanal", "🧠 Weekly Content Plan", "inicio", "plan_semanal"),
            ("🪄 Planificador con Tendencias Reales", "🪄 Real Trends Planner", "calendario", "planificador"),
        ],
    },
    "contenido": {
        "emoji": "✍️", "color": "#16A34A",
        "nombre": ("Contenido", "Content"),
        "desc": ("Reels, copies, blog, emails y storytelling", "Reels, copy, blog, emails and storytelling"),
        "subfunciones": [
            ("🎬 Experto TikTok/Reels", "🎬 TikTok/Reels Expert", "marketing", "Experto TikTok/Reels"),
            ("📖 Storytelling de Marca", "📖 Brand Storytelling", "marketing", "Storytelling de Marca"),
            ("📝 Artículo de Blog SEO", "📝 SEO Blog Article", "marketing", "Artículo de Blog SEO"),
            ("🔑 SEO y Palabras Clave", "🔑 SEO & Keywords", "marketing", "SEO y Palabras Clave"),
            ("📧 Email Marketing", "📧 Email Marketing", "power", "Email Marketing"),
            ("🚨 Plan de Crisis", "🚨 Crisis Plan", "marketing", "Plan de Crisis"),
        ],
    },
    "imagenes": {
        "emoji": "🖼️", "color": "#F97316",
        "nombre": ("Imágenes", "Images"),
        "desc": ("Creativos premium y auditoría visual", "Premium creatives and visual audit"),
        "subfunciones": [
            ("🎨 Generador de Imágenes Premium", "🎨 Premium Image Generator", "marketing", "Generador de Imagenes"),
            ("🎞 Auditoría Visual (Video/Foto)", "🎞 Visual Audit (Video/Photo)", "marketing", "Auditoría Visual (Video/Foto)"),
        ],
    },
    "publicidad": {
        "emoji": "📣", "color": "#7C3AED",
        "nombre": ("Publicidad", "Advertising"),
        "desc": ("Ads, segmentación, compliance y campañas", "Ads, targeting, compliance and campaigns"),
        "subfunciones": [
            ("🎯 Segmentación de Ads", "🎯 Ads Segmentation", "marketing", "Segmentación Ads"),
            ("🛡 Compliance Checker", "🛡 Compliance Checker", "marketing", "Compliance Checker"),
            ("🧪 Simulador de Campaña", "🧪 Campaign Simulator", "marketing", "Simulador de Campaña"),
            ("🛍 Campaña por Catálogo", "🛍 Catalog Campaign", "marketing", "Campaña de Catálogo"),
            ("🤝 Influencer Marketing", "🤝 Influencer Marketing", "power", "Influencer Marketing"),
            ("📰 PR Digital", "📰 Digital PR", "power", "PR Digital"),
        ],
    },
    "ventas": {
        "emoji": "💰", "color": "#0D9488",
        "nombre": ("Ventas", "Sales"),
        "desc": ("Embudos, precios, ofertas y cierres", "Funnels, pricing, offers and closing"),
        "subfunciones": [
            ("🌀 Embudo de Ventas", "🌀 Sales Funnel", "marketing", "Embudo de Ventas"),
            ("🧠 Psicólogo de Precios", "🧠 Price Psychology", "ventas", "Psicólogo de Precios"),
            ("🥊 Mata-Objeciones", "🥊 Objection Buster", "ventas", "Mata-Objeciones"),
            ("🏷 Calculadora de Descuentos", "🏷 Discount Calculator", "ventas", "Calculadora Descuentos"),
            ("📄 Cotizaciones", "📄 Quotes", "admin", "Cotizaciones"),
        ],
    },
    "competencia": {
        "emoji": "🎯", "color": "#EC4899",
        "nombre": ("Competencia", "Competitors"),
        "desc": ("Espionaje, gaps y posicionamiento", "Spying, gaps and positioning"),
        "subfunciones": [
            ("🕵 Inteligencia Competitiva", "🕵 Competitive Intelligence", "marketing", "🕵 Inteligencia Competitiva"),
            ("🔍 Auditoría SEO Completa", "🔍 Complete SEO Audit", "power", "Auditoría SEO Completa"),
        ],
    },
    "gestion": {
        "emoji": "📋", "color": "#8B5CF6",
        "nombre": ("Gestión", "Management"),
        "desc": ("CRM, contratos, marca e integraciones", "CRM, contracts, brand and integrations"),
        "subfunciones": [
            ("👥 CRM con IA", "👥 AI CRM", "crm", "crm"),
            ("📜 Contratos", "📜 Contracts", "admin", "Contratos"),
            ("📏 Reglas de Marca", "📏 Brand Rules", "admin", "Reglas de Marca"),
            ("🔗 Integraciones (tiendas y GA)", "🔗 Integrations (stores & GA)", "admin", "Integraciones"),
            ("💬 Gestión de Comunidad", "💬 Community Management", "power", "Gestión de Comunidad"),
        ],
    },
    "metricas": {
        "emoji": "📊", "color": "#D4A017",
        "nombre": ("Métricas", "Metrics"),
        "desc": ("KPIs, ROI, analítica y optimización", "KPIs, ROI, analytics and optimization"),
        "subfunciones": [
            ("📈 Analista ROI (CSV)", "📈 ROI Analyst (CSV)", "admin", "Analista ROI (CSV)"),
            ("📊 Analizador de Métricas", "📊 Metrics Analyzer", "admin", "Analizador de Métricas"),
            ("🎯 Tracker de KPIs", "🎯 KPI Tracker", "power", "Tracker de KPIs"),
            ("🎯 Optimizador Landing CRO", "🎯 Landing Page Optimizer (CRO)", "power", "Optimizador Landing CRO"),
        ],
    },
}


# ══════════════════════════════════════════════════════════════════
# CENTRO DE MANDO: PULPO INTERACTIVO SVG (FASE 1)
# ══════════════════════════════════════════════════════════════════
_PULPO_ESTADO_TXT = {
    "es": {"waiting": "Esperando", "analyzing": "Analizando...", "working": "Trabajando...",
           "completed": "Terminado ✓", "error": "Error — reintentar"},
    "en": {"waiting": "Waiting", "analyzing": "Analyzing...", "working": "Working...",
           "completed": "Done ✓", "error": "Error — retry"},
}

_PULPO_NODOS = [
    # id, path tentáculo, cx, cy, relleno suave, color, grad(x1,y1,x2,y2,start)
    ("estrategia",  "M445 395 C 350 330, 280 250, 205 175", 175, 150, "#EAF1FE", "#2563EB", (430, 400, 175, 150, "#7C3AED")),
    ("contenido",   "M435 430 C 340 415, 250 390, 178 350", 150, 330, "#EAF7EE", "#16A34A", (420, 430, 150, 330, "#7C3AED")),
    ("imagenes",    "M440 470 C 350 490, 265 505, 192 515", 165, 520, "#FFF1E8", "#F97316", (430, 470, 165, 520, "#7C3AED")),
    ("publicidad",  "M465 500 C 400 570, 330 630, 275 670", 255, 690, "#F3EEFF", "#7C3AED", (460, 500, 255, 690, "#6D28D9")),
    ("metricas",    "M555 395 C 650 330, 720 250, 795 175", 825, 150, "#FDF7E3", "#D4A017", (570, 400, 825, 150, "#7C3AED")),
    ("gestion",     "M565 430 C 660 415, 750 390, 822 350", 850, 330, "#F3EEFF", "#8B5CF6", (580, 430, 850, 330, "#7C3AED")),
    ("competencia", "M560 470 C 650 490, 735 505, 808 515", 835, 520, "#FDEEF6", "#EC4899", (570, 470, 835, 520, "#7C3AED")),
    ("ventas",      "M535 500 C 600 570, 670 630, 725 670", 745, 690, "#E6F5F3", "#0D9488", (540, 500, 745, 690, "#6D28D9")),
]

_PULPO_CSS_JS_HEAD = """<style>
  body{font-family:'Segoe UI',system-ui,sans-serif;background:transparent;margin:0;padding:0;}
  .agent{cursor:pointer;transition:opacity .3s ease;}
  .agent .tentacle{transition:opacity .4s ease, stroke-width .3s ease;}
  .agent .node-ring{transition:all .3s ease;}
  .agent .badge-check,.agent .badge-error,.agent .spinner,.agent .progress-arc{opacity:0;}
  .agent .status-txt{font-size:11px;fill:#8A84A0;}
  .agent.waiting{filter:grayscale(1);opacity:.45;}
  .agent.analyzing .node-circle{animation:pulso 1.6s ease-in-out infinite;}
  .agent.analyzing .tentacle{animation:pulsoT 1.6s ease-in-out infinite;}
  @keyframes pulso{0%,100%{transform:scale(1);}50%{transform:scale(1.07);}}
  @keyframes pulsoT{0%,100%{opacity:1;}50%{opacity:.55;}}
  .agent .node-circle{transform-box:fill-box;transform-origin:center;}
  .agent.working .node-circle{filter:drop-shadow(0 0 10px var(--agent-color));}
  .agent.working .tentacle{stroke-width:30;filter:drop-shadow(0 0 6px var(--agent-color));}
  .agent.working .spinner{opacity:1;animation:girar 1.1s linear infinite;transform-box:fill-box;transform-origin:center;}
  .agent.working .progress-arc{opacity:1;}
  @keyframes girar{to{transform:rotate(360deg);}}
  .agent.completed .node-ring{stroke:#16A34A;stroke-width:4;}
  .agent.completed .badge-check{opacity:1;}
  .agent.error .node-ring{stroke:#DC2626;stroke-width:4;}
  .agent.error .badge-error{opacity:1;}
  .agent.error{animation:tiemble .35s ease 1;}
  @keyframes tiemble{25%{transform:translateX(-3px);}75%{transform:translateX(3px);}}
  .agent:hover .tentacle{stroke-width:32;}
  .agent:hover .node-label{font-weight:700;}
  #cuerpo-pulpo{animation:respira 5s ease-in-out infinite;transform-box:fill-box;transform-origin:center;}
  @keyframes respira{0%,100%{transform:translateY(0);}50%{transform:translateY(-8px);}}
</style>
"""

_PULPO_JS_TAIL = """<script>
const ESTADO_TXT = __ESTADO_TXT__;
const CIRCUNF = 2 * Math.PI * 52;
window.TENTAKL = {
  setState(agente, estado){
    const g = document.getElementById("agent-"+agente);
    if(!g) return;
    g.classList.remove("waiting","analyzing","working","completed","error");
    g.classList.add(estado);
    const txt = g.querySelector(".status-txt");
    if(txt) txt.textContent = ESTADO_TXT[estado] || estado;
    if(estado !== "working") this.setProgress(agente, 0);
  },
  setProgress(agente, pct){
    const g = document.getElementById("agent-"+agente);
    if(!g) return;
    const arc = g.querySelector(".progress-arc");
    if(arc) arc.setAttribute("stroke-dasharray", (CIRCUNF*pct/100) + " " + CIRCUNF);
  },
  reset(){
    document.querySelectorAll(".agent").forEach(g=>{ this.setState(g.dataset.agent, "waiting"); });
  }
};
document.querySelectorAll(".agent").forEach(g=>{
  g.addEventListener("click", ()=>{
    const id = g.dataset.agent;
    try{
      // En Streamlit Cloud el iframe es cross-origin: no se puede LEER
      // window.parent.location, pero document.referrer trae la URL del padre
      // y NAVEGAR window.top sí está permitido.
      const base = document.referrer || window.parent.location.href;
      const url = new URL(base);
      url.searchParams.set("agente", id);
      window.top.location.href = url.toString();
    }catch(e){ console.log("Clic en agente:", id, e); }
  });
});
</script>
"""


def _pulpo_html(estados=None, en=False):
    """Genera el HTML del pulpo interactivo con los estados actuales de cada agente."""
    import json as _json_p
    estados = estados or {}
    _txt = _PULPO_ESTADO_TXT["en" if en else "es"]
    _defs = ['<linearGradient id="gradCuerpo" x1="0" y1="0" x2="0" y2="1">'
             '<stop offset="0%" stop-color="#8B5CF6"/><stop offset="100%" stop-color="#6D28D9"/></linearGradient>',
             '<radialGradient id="gradMedallon" cx="50%" cy="40%" r="70%">'
             '<stop offset="0%" stop-color="#2A2545"/><stop offset="100%" stop-color="#15112B"/></radialGradient>']
    _nodos = []
    for _aid, _path, _cx, _cy, _soft, _color, _grad in _PULPO_NODOS:
        _gx1, _gy1, _gx2, _gy2, _gstart = _grad
        _defs.append(
            f'<linearGradient id="gt-{_aid}" gradientUnits="userSpaceOnUse" '
            f'x1="{_gx1}" y1="{_gy1}" x2="{_gx2}" y2="{_gy2}">'
            f'<stop offset="0%" stop-color="{_gstart}"/><stop offset="85%" stop-color="{_color}"/></linearGradient>'
        )
        _estado = estados.get(_aid, "waiting")
        if _estado not in ("waiting", "analyzing", "working", "completed", "error"):
            _estado = "waiting"
        _ag_cfg_p = AGENTES.get(_aid, {})
        _emoji_p = _ag_cfg_p.get("emoji", "🤖")
        _label_p = (_ag_cfg_p.get("nombre", (_aid, _aid))[1] if en else _ag_cfg_p.get("nombre", (_aid, _aid))[0])
        _label_corto = _label_p.split(" y ")[0].split(" & ")[0]
        _bx, _by = _cx + 37, _cy - 35
        _nodos.append(f'''
  <g class="agent {_estado}" id="agent-{_aid}" data-agent="{_aid}" style="--agent-color:{_color}">
    <path class="tentacle" d="{_path}" fill="none" stroke="url(#gt-{_aid})" stroke-width="26" stroke-linecap="round"/>
    <circle class="node-ring" cx="{_cx}" cy="{_cy}" r="52" fill="#fff" stroke="{_color}" stroke-width="2.5"/>
    <circle class="node-circle" cx="{_cx}" cy="{_cy}" r="44" fill="{_soft}"/>
    <circle class="progress-arc" cx="{_cx}" cy="{_cy}" r="52" fill="none" stroke="{_color}" stroke-width="4" stroke-linecap="round" stroke-dasharray="0 327" transform="rotate(-90 {_cx} {_cy})"/>
    <circle class="spinner" cx="{_cx}" cy="{_cy}" r="52" fill="none" stroke="{_color}" stroke-width="3" stroke-dasharray="40 287"/>
    <text x="{_cx}" y="{_cy + 10}" text-anchor="middle" font-size="30">{_emoji_p}</text>
    <g class="badge-check"><circle cx="{_bx}" cy="{_by}" r="14" fill="#16A34A"/><path d="M{_bx - 7} {_by} l5 5 l10 -10" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/></g>
    <g class="badge-error"><circle cx="{_bx}" cy="{_by}" r="14" fill="#DC2626"/><text x="{_bx}" y="{_by + 6}" text-anchor="middle" fill="#fff" font-size="16" font-weight="bold">↻</text></g>
    <text class="node-label" x="{_cx}" y="{_cy + 78}" text-anchor="middle" font-size="16" font-weight="600" fill="#15112B">{_label_corto}</text>
    <text class="status-txt" x="{_cx}" y="{_cy + 96}" text-anchor="middle">{_txt[_estado]}</text>
  </g>''')

    _cuerpo = '''
  <g id="cuerpo-pulpo">
    <ellipse cx="500" cy="330" rx="130" ry="145" fill="url(#gradCuerpo)"/>
    <ellipse cx="455" cy="245" rx="26" ry="34" fill="#A78BFA" opacity=".35"/>
    <rect x="415" y="270" width="170" height="88" rx="40" fill="#15112B"/>
    <rect x="422" y="277" width="156" height="74" rx="34" fill="#1E1938"/>
    <rect x="455" y="298" width="14" height="22" rx="3" fill="#67E8F9"/>
    <rect x="531" y="298" width="14" height="22" rx="3" fill="#67E8F9"/>
    <path d="M470 334 Q500 350 530 334" stroke="#67E8F9" stroke-width="5" fill="none" stroke-linecap="round"/>
    <circle cx="378" cy="315" r="20" fill="#5B21B6"/>
    <circle cx="622" cy="315" r="20" fill="#5B21B6"/>
    <circle cx="500" cy="452" r="42" fill="url(#gradMedallon)" stroke="#8B5CF6" stroke-width="4"/>
    <path d="M505 428 L485 458 L500 458 L492 480 L516 448 L501 448 L508 428 Z" fill="#F59E0B"/>
  </g>'''

    return (_PULPO_CSS_JS_HEAD
            + '<svg id="tentakl-svg" viewBox="0 0 1000 860" width="100%" '
            + 'style="max-width:900px;display:block;margin:0 auto;" xmlns="http://www.w3.org/2000/svg">'
            + "<defs>" + "".join(_defs) + "</defs>"
            + "".join(_nodos) + _cuerpo + "</svg>"
            + _PULPO_JS_TAIL.replace("__ESTADO_TXT__", _json_p.dumps(_txt, ensure_ascii=False)))


# ══════════════════════════════════════════════════════════════════
# COMPONENTE BIDIRECCIONAL DEL PULPO (clic sin recargar la página)
# ══════════════════════════════════════════════════════════════════
try:
    import streamlit.components.v1 as _stc_pulpo
    _PULPO_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulpo_component")
    if os.path.isdir(_PULPO_COMPONENT_DIR):
        _pulpo_component = _stc_pulpo.declare_component("tentakl_pulpo", path=_PULPO_COMPONENT_DIR)
    else:
        _pulpo_component = None
except Exception:
    _pulpo_component = None


# ══════════════════════════════════════════════════════════════════
# FASE 2: SELECCIÓN AUTOMÁTICA DE AGENTES SEGÚN EL OBJETIVO
# ══════════════════════════════════════════════════════════════════
_TAREAS_GENERICAS = {
    "estrategia": "Analiza el negocio, el mercado y define la estrategia para el objetivo",
    "contenido": "Crea el concepto, los mensajes y las piezas de contenido",
    "imagenes": "Define la dirección de arte y los briefs visuales de la campaña",
    "publicidad": "Diseña la campaña de ads con segmentación y presupuesto",
    "ventas": "Crea la oferta, los CTA y las respuestas a objeciones",
    "competencia": "Analiza a la competencia y define la diferenciación",
    "gestion": "Define el plan de seguimiento de clientes y consistencia de marca",
    "metricas": "Define los KPIs e indicadores de seguimiento del objetivo",
}

_MENSAJES_AGENTE = {
    "estrategia": ("Analizando tu negocio, mercado y objetivo...", "Analyzing your business, market and goal..."),
    "contenido": ("Creando concepto, mensajes y calendario...", "Creating concept, messages and calendar..."),
    "imagenes": ("Generando propuestas visuales...", "Generating visual proposals..."),
    "publicidad": ("Preparando campaña, segmentación y variaciones...", "Preparing campaign, targeting and variations..."),
    "ventas": ("Creando oferta, CTA y respuestas a objeciones...", "Creating offer, CTAs and objection handling..."),
    "competencia": ("Analizando a tu competencia y sus gaps...", "Analyzing your competitors and their gaps..."),
    "gestion": ("Organizando seguimiento y gestión...", "Organizing follow-up and management..."),
    "metricas": ("Preparando indicadores y plan de seguimiento...", "Preparing KPIs and tracking plan..."),
}


def _seleccion_agentes_por_reglas(objetivo):
    """Respaldo por reglas internas si Gemini falla o devuelve JSON inválido."""
    _o = (objetivo or "").lower()
    if any(_k in _o for _k in ["imagen", "foto", "banner", "flyer", "visual", "logo", "creativo"]):
        _ids = ["contenido", "imagenes"]
    elif any(_k in _o for _k in ["analiza", "metric", "métric", "roi", "kpi", "resultado", "reporte"]):
        _ids = ["metricas", "ventas", "estrategia"]
    elif any(_k in _o for _k in ["venta", "precio", "cotiza", "oferta", "descuento", "cerrar"]):
        _ids = ["estrategia", "ventas", "metricas"]
    elif any(_k in _o for _k in ["lanzar", "lanzamiento", "nuevo producto", "abrir", "empezar negocio"]):
        _ids = ["estrategia", "competencia", "contenido", "publicidad", "ventas", "metricas"]
    else:
        _ids = ["estrategia", "contenido", "publicidad", "ventas", "metricas"]
    return {"objetivo_interpretado": (objetivo or "")[:200],
            "agentes": [(_i, _TAREAS_GENERICAS[_i]) for _i in _ids]}


def seleccionar_agentes_para_objetivo(objetivo_usuario, perfil_negocio=None):
    """FASE 2: Gemini analiza el objetivo y decide qué agentes activar.
    Devuelve {"objetivo_interpretado": str, "agentes": [(id, tarea), ...]} (máx 6).
    Si el JSON de Gemini falla, cae a la selección por reglas."""
    import json as _json_sel
    import re as _re_sel
    if perfil_negocio is None:
        perfil_negocio = {
            "marca": st.session_state.get("marca_guardada", ""),
            "nicho": st.session_state.get("nicho_guardado", ""),
            "producto_servicio": st.session_state.get("producto_servicio", ""),
            "cliente_ideal": (st.session_state.get("cliente_ideal_guardado", "") or "")[:300],
            "pais": st.session_state.get("pais_guardado", ""),
            "ciudad": st.session_state.get("ciudad_guardada", ""),
            "idioma": st.session_state.get("idioma_preferido", "Español"),
            "plan": st.session_state.get("plan", "Free"),
            "links": (st.session_state.get("link_redes", "") + " " + st.session_state.get("link_web", "")).strip(),
        }
    _cat = "\n".join([f'- {_k}: {_v[1]}' for _k, _v in {
        "estrategia": ("", "diagnóstico del negocio, tendencias, plan de acción"),
        "contenido": ("", "contenido para redes, guiones, emails, blog, storytelling"),
        "imagenes": ("", "imágenes, banners, creativos y dirección visual"),
        "publicidad": ("", "campañas de ads, segmentación, presupuesto, compliance"),
        "ventas": ("", "embudos, precios, ofertas, objeciones, cotizaciones"),
        "competencia": ("", "análisis de competencia, gaps, posicionamiento"),
        "gestion": ("", "CRM, clientes, contratos, seguimiento"),
        "metricas": ("", "KPIs, ROI, analítica, optimización"),
    }.items()])
    _prompt_sel = (
        "Eres el coordinador del equipo de agentes de marketing de Tentakl.\n"
        f"AGENTES DISPONIBLES (id: especialidad):\n{_cat}\n\n"
        f"PERFIL DEL NEGOCIO: {_json_sel.dumps(perfil_negocio, ensure_ascii=False)}\n"
        f"OBJETIVO DEL USUARIO: {objetivo_usuario}\n\n"
        "Analiza el objetivo y decide QUÉ agentes son necesarios (no siempre todos: "
        "una imagen simple necesita 2, un lanzamiento completo hasta 6).\n"
        "Responde EXCLUSIVAMENTE este JSON, sin markdown ni explicación:\n"
        '{"objetivo_interpretado": "resumen de una línea", "agentes_necesarios": '
        '[{"id": "estrategia", "orden": 1, "motivo": "por qué", "tarea": "tarea específica"}]}\n'
        "Máximo 6 agentes, mínimo 1, sin repetir ids. Solo ids de la lista."
    )
    _raw_sel = generar_texto(_prompt_sel, max_out=2000, temperatura=0.2)
    try:
        _m_sel = _re_sel.search(r"\{.*\}", _raw_sel or "", _re_sel.DOTALL)
        if _m_sel:
            _data_sel = _json_sel.loads(_m_sel.group(0))
            _ags = []
            for _p_sel in sorted(_data_sel.get("agentes_necesarios", []),
                                 key=lambda _x: _x.get("orden", 99)):
                _id_sel = str(_p_sel.get("id", "")).strip().lower()
                if _id_sel in AGENTES and _id_sel not in [_a[0] for _a in _ags]:
                    _tarea_sel = str(_p_sel.get("tarea", "") or _TAREAS_GENERICAS.get(_id_sel, ""))[:300]
                    _ags.append((_id_sel, _tarea_sel))
            if _ags:
                return {
                    "objetivo_interpretado": str(_data_sel.get("objetivo_interpretado", objetivo_usuario))[:200],
                    "agentes": _ags[:6],
                }
    except Exception:
        pass
    return _seleccion_agentes_por_reglas(objetivo_usuario)


def _render_contexto_compartido(agente_actual):
    """CAMBIO 8: muestra los últimos reportes del equipo como contexto opcional."""
    _em = (st.session_state.get("user_email") or "").strip().lower()
    if not _em or not supabase:
        return
    try:
        _res = (supabase.table("reportes")
                .select("tipo_reporte,titulo,contenido,created_at")
                .eq("user_email", _em)
                .order("created_at", desc=True)
                .limit(3).execute())
        _reps = _res.data or []
    except Exception:
        return
    if not _reps:
        return
    _en_ctx = st.session_state.get("lang") == "en"
    _partes_ctx = []
    with st.expander("📎 " + ("Contexto disponible de tu equipo de agentes" if not _en_ctx else "Available context from your agent team")):
        st.caption("Marca lo que quieras que este agente tenga en cuenta:" if not _en_ctx else "Check what you want this agent to consider:")
        for _i, _r in enumerate(_reps):
            _lbl = f"{str(_r.get('titulo',''))[:70]} · {str(_r.get('created_at',''))[:10]}"
            if st.checkbox(_lbl, key=f"ctx_chk_{agente_actual}_{_i}"):
                _partes_ctx.append(f"--- {_r.get('titulo','')} ---\n{str(_r.get('contenido',''))[:800]}")
    st.session_state["ctx_compartido"] = "\n\n".join(_partes_ctx)


# ══════════════════════════════════════════════════════════════════
# FASE 4: PANEL INTERNO POR AGENTE
# ══════════════════════════════════════════════════════════════════
TIPOS_POR_AGENTE = {
    "estrategia": ["recomendacion", "diagnostico", "tendencia_adaptada", "plan_semanal", "autopiloto"],
    "contenido": ["storytelling", "seo", "blog_seo", "plan_crisis", "email_marketing"],
    "imagenes": ["imagen_banner"],
    "publicidad": ["segmentacion_ads", "compliance", "catalogo", "influencer_marketing", "pr_digital"],
    "ventas": ["embudo_ventas", "cotizacion"],
    "competencia": ["sentimiento", "auditoria_seo"],
    "gestion": ["contrato", "reglas_marca", "community_management"],
    "metricas": ["kpi_tracker", "landing_cro", "roi", "metricas", "ga_analytics"],
}

_BADGES_ESTADO = {
    "es": {"idle": "🟢 Listo", "waiting": "⚪ Esperando", "analyzing": "🔵 Analizando...",
           "working": "🟡 Trabajando...", "completed": "✅ Terminado", "error": "🔴 Error"},
    "en": {"idle": "🟢 Ready", "waiting": "⚪ Waiting", "analyzing": "🔵 Analyzing...",
           "working": "🟡 Working...", "completed": "✅ Done", "error": "🔴 Error"},
}


def _render_panel_agente(agente_id, en):
    """FASE 4: descripción, estado, tarea activa y resultados recientes del agente."""
    _ag_p = AGENTES.get(agente_id, {})
    _desc_p = _ag_p.get("desc", ("", ""))[1 if en else 0]
    _estado_p = st.session_state.get("agent_states", {}).get(agente_id, "idle")
    _badge_p = _BADGES_ESTADO["en" if en else "es"].get(_estado_p, _estado_p)
    _c_p1, _c_p2 = st.columns([3, 1])
    with _c_p1:
        st.caption(_desc_p)
    with _c_p2:
        st.caption(("Estado: " if not en else "Status: ") + _badge_p)

    # Tarea activa del Centro de Mando (si este agente está en la corrida actual)
    if st.session_state.get("cm_fase") in ("confirmar", "ejecutar"):
        for _aid_p, _tarea_p in (st.session_state.get("cm_secuencia") or []):
            if _aid_p == agente_id and _tarea_p:
                st.info(("📌 Tarea activa: " if not en else "📌 Active task: ") + _tarea_p)
                break

    # Resultados recientes de ESTE agente
    _em_p = (st.session_state.get("user_email") or "").strip().lower()
    _tipos_p = TIPOS_POR_AGENTE.get(agente_id, [])
    if _em_p and supabase and _tipos_p:
        try:
            _res_p = (supabase.table("reportes")
                      .select("tipo_reporte,titulo,contenido,created_at")
                      .eq("user_email", _em_p)
                      .in_("tipo_reporte", _tipos_p)
                      .order("created_at", desc=True)
                      .limit(3).execute())
            _reps_p = _res_p.data or []
        except Exception:
            _reps_p = []
        if _reps_p:
            with st.expander("🗂 " + ("Resultados recientes de este agente" if not en else "Recent results from this agent")):
                for _i_p, _r_p in enumerate(_reps_p):
                    st.markdown(f"**{str(_r_p.get('titulo', ''))[:70]}** · {str(_r_p.get('created_at', ''))[:10]}")
                    if st.toggle("Ver" if not en else "View", key=f"panel_ver_{agente_id}_{_i_p}"):
                        st.markdown(str(_r_p.get("contenido", ""))[:3000])
                    st.divider()


# ══════════════════════════════════════════════════════════════════
# CENTRO DE MANDO: FASES COMPARTIDAS (home + Autopiloto, FASE 5)
# ══════════════════════════════════════════════════════════════════
def _cm_render_confirmacion(_en, _plan_u):
    """Pantalla de confirmación: agentes elegidos, edición, costo, confirmar/cancelar."""
    _plan_cm = st.session_state["cm_plan"]
    st.info("🐙 " + ("TENTAKL utilizará estos agentes para: " if not _en else "TENTAKL will use these agents for: ")
            + f"**{_plan_cm.get('objetivo_interpretado', '')}**")
    _tareas_plan = dict(_plan_cm.get("agentes", []))
    for _aid_c, _tarea_c in _plan_cm.get("agentes", []):
        _agc = AGENTES.get(_aid_c, {})
        _nomc = _agc.get("nombre", (_aid_c, _aid_c))[1 if _en else 0]
        st.markdown(f"{_agc.get('emoji', '🤖')} **{_nomc}** — {_tarea_c}")

    _labels_por_id = {_k: (_v["nombre"][1] if _en else _v["nombre"][0]) for _k, _v in AGENTES.items()}
    _ids_por_label = {_v: _k for _k, _v in _labels_por_id.items()}
    _sel_edit = st.multiselect(
        "✏️ " + ("Editar selección de agentes:" if not _en else "Edit agent selection:"),
        list(_labels_por_id.values()),
        default=[_labels_por_id[_a] for _a, _t in _plan_cm.get("agentes", []) if _a in _labels_por_id],
        key="cm_edit_sel",
    )
    _ids_finales = [_ids_por_label[_l] for _l in _sel_edit if _l in _ids_por_label][:6]
    _n_ag_cm = max(len(_ids_finales), 1)
    st.caption(("💳 Costo: 8 créditos · ⏱ Tiempo aproximado: " if not _en else "💳 Cost: 8 credits · ⏱ Approx time: ")
               + f"{_n_ag_cm * 30}-{_n_ag_cm * 60} seg")
    # Aviso de imagen real + fuente si el agente Imágenes está en la selección
    if "imagenes" in _ids_finales:
        _img_ok_cm, _img_msg_cm = verificar_limite_imagenes()
        if _img_ok_cm:
            st.caption("🎨 " + ("El agente Imágenes generará 1 imagen real (usa 1 imagen de tu límite mensual, sin créditos extra)."
                                if not _en else
                                "The Images agent will generate 1 real image (uses 1 image from your monthly limit, no extra credits)."))
            _FUENTES_CM = (["✨ Desde cero", "📷 Subir foto", "🛍 De mi catálogo"]
                           if not _en else ["✨ From scratch", "📷 Upload photo", "🛍 From my catalog"])
            _cm_fuente_img = st.radio("Fuente de la imagen:" if not _en else "Image source:",
                                      _FUENTES_CM, horizontal=True, key="cm_img_fuente")
            st.session_state["cm_img_ref_bytes"] = None
            st.session_state["cm_img_ref_url"] = None
            if _cm_fuente_img == _FUENTES_CM[1]:
                _cm_up = st.file_uploader("Sube tu foto (PNG/JPG/WebP, máx 10MB):" if not _en
                                          else "Upload your photo (PNG/JPG/WebP, max 10MB):",
                                          type=["png", "jpg", "jpeg", "webp"], key="cm_img_upload")
                if _cm_up is not None:
                    if _cm_up.size > 10 * 1024 * 1024:
                        st.error("La imagen supera los 10MB." if not _en else "The image exceeds 10MB.")
                    else:
                        st.session_state["cm_img_ref_bytes"] = _cm_up.getvalue()
                        st.image(st.session_state["cm_img_ref_bytes"], width=120)
            elif _cm_fuente_img == _FUENTES_CM[2]:
                _em_cmf = (st.session_state.get("user_email") or "").strip().lower()
                _ops_cmf = [(f"📦 {_p['nombre']}", _p["imagen_url"]) for _p in db_get_catalogo(_em_cmf)
                            if (_p.get("imagen_url") or "").strip()]
                if not _ops_cmf:
                    st.warning("No hay productos con imagen en tu catálogo. Sube una foto o sincroniza tu tienda."
                               if not _en else "No products with images in your catalog. Upload a photo or sync your store.")
                else:
                    _sel_cmf = st.selectbox("Producto:" if not _en else "Product:",
                                            [_o[0] for _o in _ops_cmf], key="cm_img_cat_sel")
                    _url_cmf = next(_o[1] for _o in _ops_cmf if _o[0] == _sel_cmf)
                    st.session_state["cm_img_ref_url"] = _url_cmf
                    st.image(_url_cmf, width=120)
        else:
            st.warning(f"🎨 {_img_msg_cm} " + ("El agente Imágenes entregará solo el brief visual."
                                               if not _en else "The Images agent will deliver the visual brief only."))
    _col_cm1, _col_cm2 = st.columns(2)
    with _col_cm1:
        _btn_conf = st.button("✅ " + ("Confirmar y ejecutar (8 créditos)" if not _en else "Confirm and run (8 credits)"),
                              key="cm_btn_confirmar", use_container_width=True, type="primary")
    with _col_cm2:
        if st.button("❌ " + ("Cancelar" if not _en else "Cancel"), key="cm_btn_cancelar", use_container_width=True):
            st.session_state["cm_fase"] = None
            st.session_state["cm_plan"] = None
            st.rerun()
    if _btn_conf:
        if not _ids_finales:
            st.warning("Selecciona al menos un agente." if not _en else "Select at least one agent.")
        elif _plan_u not in ("Pro", "Agency", "Admin"):
            _mostrar_upgrade("🔒 " + ("El Centro de Mando coordinado está disponible desde el plan Pro ($39/mes):"
                                      if not _en else "The coordinated Command Center is available from the Pro plan ($39/mo):"))
        elif verificar_creditos(COSTO_CREDITOS["autopiloto"]):
            st.session_state["cm_secuencia"] = [(_i2, _tareas_plan.get(_i2, _TAREAS_GENERICAS.get(_i2, ""))) for _i2 in _ids_finales]
            st.session_state["agent_states"] = {_i2: "waiting" for _i2 in _ids_finales}
            st.session_state["cm_resultado"] = {}
            st.session_state["cm_imagenes"] = {}
            st.session_state["cm_es_reintento"] = False
            st.session_state["cm_fase"] = "ejecutar"
            st.rerun()


def _cm_render_ejecucion(_en):
    """Ejecución secuencial con estados en vivo sobre el pulpo + progreso total."""
    _sec_cm = st.session_state.get("cm_secuencia") or []
    _pedido_cm = st.session_state.get("objetivo_actual", "")
    _es_retry_cm = st.session_state.get("cm_es_reintento", False)
    _estados_cm = st.session_state.get("agent_states", {}) or {}
    _outs_cm = st.session_state.get("cm_resultado") or {}
    _pulpo_live = st.empty()
    _prog_total = st.progress(0.0, text=("Progreso total" if not _en else "Total progress"))
    _ctx_cm = ""
    _exitos_cm = 0
    _total_cm = max(len(_sec_cm), 1)
    with st.status("⚡ " + ("Tu equipo está trabajando..." if not _en else "Your team is working..."),
                   expanded=True) as _status_cm:
        for _n_cm, (_aid_r, _tarea_r) in enumerate(_sec_cm):
            _agr = AGENTES.get(_aid_r, {})
            _nomr = _agr.get("nombre", (_aid_r, _aid_r))[1 if _en else 0]
            _msgr = _MENSAJES_AGENTE.get(_aid_r, ("Trabajando...", "Working..."))[1 if _en else 0]
            _estados_cm[_aid_r] = "working"
            st.session_state["agent_states"] = _estados_cm
            with _pulpo_live.container():
                if _pulpo_component is not None:
                    try:
                        _pulpo_component(estados=_estados_cm, en=_en,
                                         key=f"pulpo_run_{_n_cm}", default=None)
                    except Exception:
                        pass
            _prog_total.progress(_n_cm / _total_cm,
                                 text=(f"Paso {_n_cm + 1}/{_total_cm}" if not _en else f"Step {_n_cm + 1}/{_total_cm}"))
            st.write(f"{_agr.get('emoji', '🤖')} **{_nomr}** — {_msgr}")
            _prompt_r = (
                f"Eres el agente {_nomr} del equipo de marketing Tentakl.\n"
                f"OBJETIVO GENERAL DEL USUARIO: {_pedido_cm}\n"
                + (f"TRABAJO PREVIO DE TUS COLEGAS (sé coherente):\n{_ctx_cm[-3000:]}\n" if _ctx_cm else "")
                + f"\nTU TAREA ESPECÍFICA: {_tarea_r}\n"
                "Entrega un resultado accionable, específico y listo para usar. "
                "No repitas lo que ya hicieron tus colegas."
            )
            # ── Plan de Contenido Semanal REAL cuando la tarea lo pide ────────
            _es_plan_semanal = (_aid_r == "estrategia" and any(
                _kw in (_tarea_r + " " + _pedido_cm).lower()
                for _kw in ["plan semanal", "plan de contenido", "calendario de contenido",
                            "weekly plan", "content plan"]))
            if _es_plan_semanal:
                _prompt_r = (
                    f"Eres estratega de contenidos.\nOBJETIVO DEL USUARIO: {_pedido_cm}\n"
                    + (f"TRABAJO PREVIO DE TUS COLEGAS:\n{_ctx_cm[-2000:]}\n" if _ctx_cm else "")
                    + "\nCrea el plan semanal en este formato EXACTO:\n\n"
                    "## 📅 PLAN DE CONTENIDO — ESTA SEMANA\n\n"
                    "| Día | Red Social | Tipo | Tema | CTA |\n"
                    "|---|---|---|---|---|\n"
                    "| Lunes | | | | |\n| Martes | | | | |\n| Miércoles | | | | |\n"
                    "| Jueves | | | | |\n| Viernes | | | | |\n\n"
                    "## 🎯 OBJETIVO DE LA SEMANA\n"
                    "- Meta principal: [número concreto]\n- Cómo medirlo: [herramienta]\n\n"
                    "## 🔥 EL POST MÁS IMPORTANTE DE LA SEMANA\n"
                    "[Copy completo del post con mayor potencial viral]\n\n"
                    "## ⏰ MEJORES HORARIOS\n"
                    "Instagram: [mejor día y hora]\nTikTok: [mejor día y hora]\n"
                    "Facebook: [mejor día y hora]\nWhatsApp: [mejor día y hora]"
                )
            _out_r = generar_texto(_prompt_r, max_out=6000 if _es_plan_semanal else 4000)
            if _out_r and _es_plan_semanal:
                _email_ps = (st.session_state.get("user_email") or "").strip().lower()
                if _email_ps:
                    try:
                        guardar_plan_semanal(_email_ps, obtener_semana_actual(), _out_r)
                        st.write("💾 " + ("Plan guardado en tu Plan de Contenido Semanal"
                                          if not _en else "Plan saved to your Weekly Content Plan"))
                    except Exception:
                        pass

            # ── Imagen REAL del agente Imágenes (GPT Image 2) ─────────────────
            if _aid_r == "imagenes" and _out_r:
                _img_ok_r, _img_msg_r = verificar_limite_imagenes()
                if not _img_ok_r:
                    _out_r += "\n\n---\n🎨 " + _img_msg_r
                else:
                    st.write("🎨 " + ("Generando imagen real de campaña (calidad "
                                      + str(get_plan_config().get("calidad_imagen", "low")) + ")..."
                                      if not _en else "Generating real campaign image..."))
                    # Referencia elegida en la confirmación (foto subida / catálogo),
                    # o el logo de marca como composición automática si existe
                    _ref_bytes_r = st.session_state.get("cm_img_ref_bytes")
                    _ref_url_r = st.session_state.get("cm_img_ref_url") or ((st.session_state.get("logo_url") or "").strip() or None)
                    try:
                        _img_b64_r, _err_img_r = generar_imagen_openai(
                            (_pedido_cm or "")[:300] + "\n" + _out_r[:500],
                            st.session_state.get("marca_guardada", ""),
                            st.session_state.get("nicho_guardado", ""),
                            st.session_state.get("pais_guardado", "Perú"),
                            formato="1024x1024",
                            calidad=get_plan_config().get("calidad_imagen", "low"),
                            imagen_referencia_url=None if _ref_bytes_r else _ref_url_r,
                            imagen_referencia_bytes=_ref_bytes_r,
                        )
                    except Exception as _ex_img_r:
                        _img_b64_r, _err_img_r = None, str(_ex_img_r)
                    if _img_b64_r:
                        registrar_uso_imagen()
                        _imgs_cm = st.session_state.get("cm_imagenes") or {}
                        _imgs_cm[_aid_r] = _img_b64_r
                        st.session_state["cm_imagenes"] = _imgs_cm
                        st.write("✅ " + ("Imagen generada (descuenta 1 de tu límite, sin créditos extra)"
                                          if not _en else "Image generated (uses 1 from your limit, no extra credits)"))
                    else:
                        _out_r += "\n\n---\n🎨 " + ("No se pudo generar la imagen esta vez; el brief visual está listo arriba."
                                                    if not _en else "The image could not be generated this time; the visual brief is ready above.")
            if _out_r:
                _exitos_cm += 1
                _estados_cm[_aid_r] = "completed"
                _outs_cm[_aid_r] = (_nomr, _agr.get("emoji", "🤖"), _out_r)
                _ctx_cm += f"\n--- {_nomr}: {_tarea_r} ---\n{_out_r[:1200]}\n"
            else:
                _estados_cm[_aid_r] = "error"
            st.session_state["agent_states"] = _estados_cm
        with _pulpo_live.container():
            if _pulpo_component is not None:
                try:
                    _pulpo_component(estados=_estados_cm, en=_en,
                                     key="pulpo_run_final", default=None)
                except Exception:
                    pass
        _prog_total.progress(1.0, text=("Completado" if not _en else "Completed"))
        _status_cm.update(label="✅ " + ("Equipo completado" if not _en else "Team finished"),
                          state="complete")
    if _exitos_cm > 0 and not _es_retry_cm:
        st.session_state["_ultima_gen_ok"] = True
        consumir(COSTO_CREDITOS["autopiloto"], tipo_accion="autopiloto")
        _email_cm = (st.session_state.get("user_email") or "").strip().lower()
        if _email_cm:
            db_incrementar_autopiloto(_email_cm, dt.now().strftime("%Y-%m"))
    if _exitos_cm > 0:
        _email_cm2 = (st.session_state.get("user_email") or "").strip().lower()
        if _email_cm2:
            _full_cm = "\n\n".join([f"## {_e2} {_n2}\n{_o2}" for _n2, _e2, _o2 in _outs_cm.values()])
            guardar_reporte(_email_cm2, "autopiloto",
                            f"Centro de Mando: {_pedido_cm[:60]} - {dt.now().strftime('%d/%m/%Y %H:%M')}",
                            _full_cm)
    st.session_state["cm_resultado"] = _outs_cm
    st.session_state["cm_es_reintento"] = False
    st.session_state["cm_fase"] = "done"
    st.rerun()


def _cm_render_done(_en):
    """Trabajo terminado: resultados, reintento gratis de errores, nuevo trabajo."""
    st.success("🐙 " + ("Trabajo terminado" if not _en else "Work finished"))
    _outs_done = st.session_state.get("cm_resultado") or {}
    _sec_done = st.session_state.get("cm_secuencia") or []
    _estados_done = st.session_state.get("agent_states", {}) or {}
    _errores_done = [(_a3, _t3) for _a3, _t3 in _sec_done if _estados_done.get(_a3) == "error"]
    if _errores_done:
        if st.button("🔄 " + ("Reintentar agentes con error (gratis)" if not _en else "Retry failed agents (free)"),
                     key="cm_btn_retry"):
            st.session_state["cm_secuencia"] = _errores_done
            st.session_state["cm_es_reintento"] = True
            st.session_state["cm_fase"] = "ejecutar"
            st.rerun()
    _imgs_done = st.session_state.get("cm_imagenes") or {}
    with st.expander("📋 " + ("Ver resultado completo" if not _en else "See full result"), expanded=bool(_outs_done)):
        for _aidd, (_nomd, _emod, _outd) in _outs_done.items():
            st.markdown(f"### {_emod} {_nomd}")
            st.markdown(_outd)
            _b64d = _imgs_done.get(_aidd)
            if _b64d:
                import base64 as _b64cm
                try:
                    if not str(_b64d).startswith("http"):
                        _bytes_d = _b64cm.b64decode(_b64d)
                        st.image(_bytes_d, use_container_width=True,
                                 caption="🎨 Imagen de campaña" if not _en else "🎨 Campaign image")
                        st.download_button("⬇️ " + ("Descargar imagen" if not _en else "Download image"),
                                           data=_bytes_d, file_name="tentakl_campana.png",
                                           mime="image/png", key=f"cm_dl_{_aidd}")
                    else:
                        st.image(_b64d, use_container_width=True,
                                 caption="🎨 Imagen de campaña" if not _en else "🎨 Campaign image")
                except Exception:
                    pass
            st.divider()
    if st.button("🆕 " + ("Nuevo trabajo" if not _en else "New task"), key="cm_btn_nuevo"):
        for _k4 in ("cm_fase", "cm_plan", "cm_secuencia", "cm_resultado", "cm_imagenes",
                    "cm_img_ref_bytes", "cm_img_ref_url", "cm_es_reintento", "objetivo_actual"):
            st.session_state.pop(_k4, None)
        st.session_state["agent_states"] = {}
        st.rerun()


_is_en_ui = st.session_state.get("lang") == "en"

# ── Puente pulpo → Streamlit: clic en un tentáculo llega como ?agente=X ──────
try:
    _qp_agente = st.query_params.get("agente")
except Exception:
    _qp_agente = None
if _qp_agente:
    if _qp_agente in AGENTES or _qp_agente == "autopiloto":
        st.session_state.agente_activo = _qp_agente
        st.session_state["_subfuncion_activa"] = ""
        st.session_state["ctx_compartido"] = ""
    try:
        del st.query_params["agente"]  # solo este param; conservar "u" (email persistido)
    except Exception:
        pass

_agente_activo = st.session_state.get("agente_activo")
_plan_ui = st.session_state.get("plan", "Free")
_es_admin_ui = ((st.session_state.get("user_email", "").strip().lower() in ADMIN_EMAILS)
                or _plan_ui == "Admin")

_es_home = _agente_activo is None
_sec_activa = None
_opcion_activa = None

if _es_home:
    # ══ CENTRO DE MANDO (FASE 1-3): objetivo + selección + ejecución ═════════
    st.markdown(
        "<h2 style='text-align:center;margin-bottom:2px;'>"
        + ("🐙 ¿Qué quieres lograr hoy?" if not _is_en_ui else "🐙 What do you want to achieve today?")
        + "</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align:center;color:#6B6580;margin-top:0;'>"
        + ("Escribe tu objetivo y tu equipo de agentes se organiza solo."
           if not _is_en_ui else "Write your goal and your agent team organizes itself.")
        + "</p>",
        unsafe_allow_html=True,
    )
    _col_obj1, _col_obj2 = st.columns([4, 1])
    with _col_obj1:
        _objetivo_home = st.text_input(
            "Objetivo", label_visibility="collapsed",
            placeholder=("Ej: Quiero lanzar una campaña de Fiestas Patrias para mi marca de maca negra"
                         if not _is_en_ui else "Ex: I want to launch a holiday campaign for my brand"),
            key="centro_mando_objetivo",
        )
    with _col_obj2:
        _btn_empezar = st.button(
            "🚀 " + ("Empezar trabajo" if not _is_en_ui else "Start working"),
            key="btn_empezar_trabajo", use_container_width=True, type="primary",
        )

    _cm_fase = st.session_state.get("cm_fase")

    if _btn_empezar:
        if not _objetivo_home.strip():
            st.warning("Escribe primero qué quieres lograr." if not _is_en_ui else "First write what you want to achieve.")
        elif not (st.session_state.get("user_email") or "").strip():
            st.warning("Ingresa tu email en el sidebar para empezar." if not _is_en_ui else "Enter your email in the sidebar to start.")
        else:
            st.session_state["objetivo_actual"] = _objetivo_home.strip()
            with st.spinner("🐙 El pulpo está analizando tu objetivo..." if not _is_en_ui else "🐙 The octopus is analyzing your goal..."):
                st.session_state["cm_plan"] = seleccionar_agentes_para_objetivo(_objetivo_home.strip())
            st.session_state["cm_fase"] = "confirmar"
            st.rerun()

    # ── Fases del Centro de Mando (compartidas con Autopiloto) ───────────────
    if _cm_fase == "confirmar" and st.session_state.get("cm_plan"):
        _cm_render_confirmacion(_is_en_ui, _plan_ui)
    elif _cm_fase == "ejecutar":
        _cm_render_ejecucion(_is_en_ui)
    elif _cm_fase == "done":
        _cm_render_done(_is_en_ui)

    # ── Pulpo interactivo (clic bidireccional, sin recarga) ───────────────────
    _pulpo_ok = _pulpo_component is not None
    if _cm_fase != "ejecutar":
        _click_pulpo = None
        if _pulpo_ok:
            try:
                _click_pulpo = _pulpo_component(
                    estados=st.session_state.get("agent_states", {}) or {},
                    en=_is_en_ui, key="pulpo_cm", default=None,
                )
            except Exception:
                _pulpo_ok = False
        if isinstance(_click_pulpo, dict):
            _ag_click = str(_click_pulpo.get("agente", ""))
            _ts_click = _click_pulpo.get("ts")
            if _ag_click in AGENTES and _ts_click and _ts_click != st.session_state.get("_pulpo_click_ts"):
                st.session_state["_pulpo_click_ts"] = _ts_click
                st.session_state.agente_activo = _ag_click
                st.session_state["_subfuncion_activa"] = ""
                st.session_state["ctx_compartido"] = ""
                st.rerun()

    # ── Accesos secundarios: fila compacta centrada, estilo ghost ────────────
    _ap_lock_home = _plan_ui in ("Free", "Starter")
    if _es_admin_ui:
        _cm_pads = st.columns([0.5, 1.3, 1.3, 1.3, 1.3, 0.5])
        _slots_modo = _cm_pads[1:5]
    else:
        _cm_pads = st.columns([1, 1.5, 1.5, 1.5, 1])
        _slots_modo = _cm_pads[1:4]
    with _slots_modo[0]:
        if st.button("🧰 " + ("Herramientas" if not _is_en_ui else "Tools"),
                     key="btn_modo_herramientas", use_container_width=True):
            st.session_state["modo_herramientas"] = not st.session_state.get("modo_herramientas", False)
            st.rerun()
    with _slots_modo[1]:
        if st.button(("⚡ Autopiloto" if not _ap_lock_home else "🔒 Autopiloto"),
                     key="btn_home_autopiloto", use_container_width=True):
            st.session_state.agente_activo = "autopiloto"
            st.rerun()
    with _slots_modo[2]:
        if st.button("📂 " + ("Reportes" if not _is_en_ui else "Reports"),
                     key="btn_home_reportes", use_container_width=True):
            st.session_state.agente_activo = "reportes"
            st.rerun()
    if _es_admin_ui:
        with _slots_modo[3]:
            if st.button("🛠 Admin", key="btn_home_admin_dash", use_container_width=True):
                st.session_state.agente_activo = "admin_dashboard"
                st.rerun()

    # ── Modo Herramientas / fallback: tarjetas por agente ────────────────────
    if st.session_state.get("modo_herramientas") or not _pulpo_ok:
        st.divider()
        st.markdown("#### 🧰 " + ("Tus agentes y herramientas" if not _is_en_ui else "Your agents and tools"))
        _orden_agentes = ["estrategia", "contenido", "imagenes", "publicidad",
                          "ventas", "competencia", "gestion", "metricas"]
        for _fila_ag in (_orden_agentes[:4], _orden_agentes[4:]):
            _cols_ag = st.columns(4)
            for _col_ag, _ag_id in zip(_cols_ag, _fila_ag):
                _ag_cfg = AGENTES[_ag_id]
                _ag_nombre = _ag_cfg["nombre"][1] if _is_en_ui else _ag_cfg["nombre"][0]
                _ag_desc = _ag_cfg["desc"][1] if _is_en_ui else _ag_cfg["desc"][0]
                with _col_ag:
                    st.markdown(f'<div style="border-top:3px solid {_ag_cfg["color"]};border-radius:4px;padding-top:6px;margin-bottom:4px;"></div>',
                                unsafe_allow_html=True)
                    if st.button(f"{_ag_cfg['emoji']} {_ag_nombre}", key=f"card_{_ag_id}",
                                 use_container_width=True):
                        st.session_state.agente_activo = _ag_id
                        st.session_state["_subfuncion_activa"] = ""
                        st.session_state["ctx_compartido"] = ""
                        st.rerun()
                    st.caption(_ag_desc)

elif _agente_activo in ("reportes", "admin_dashboard", "autopiloto"):
    if st.button("← " + ("Volver a mis agentes" if not _is_en_ui else "Back to my agents"),
                 key="btn_volver_especial"):
        st.session_state.agente_activo = None
        st.session_state["ctx_compartido"] = ""
        st.rerun()
    _sec_activa = _agente_activo

elif _agente_activo in AGENTES:
    _ag_cfg = AGENTES[_agente_activo]
    if st.button("← " + ("Volver a mis agentes" if not _is_en_ui else "Back to my agents"),
                 key="btn_volver_agente"):
        st.session_state.agente_activo = None
        st.session_state["ctx_compartido"] = ""
        st.rerun()
    _ag_nombre_v = _ag_cfg["nombre"][1] if _is_en_ui else _ag_cfg["nombre"][0]
    st.markdown(
        f"""<h3 style="border-left:6px solid {_ag_cfg['color']};padding-left:10px;">
        {_ag_cfg['emoji']} {_ag_nombre_v}</h3>""",
        unsafe_allow_html=True,
    )
    _render_panel_agente(_agente_activo, _is_en_ui)
    _render_contexto_compartido(_agente_activo)
    _sub_labels = [(s[1] if _is_en_ui else s[0]) for s in _ag_cfg["subfunciones"]]
    _sub_sel = st.selectbox("Herramienta del agente:" if not _is_en_ui else "Agent tool:",
                            _sub_labels, key=f"sub_{_agente_activo}")
    _sub_idx = _sub_labels.index(_sub_sel)
    _sec_activa = _ag_cfg["subfunciones"][_sub_idx][2]
    _opcion_activa = _ag_cfg["subfunciones"][_sub_idx][3]
    st.session_state["_subfuncion_activa"] = _ag_cfg["subfunciones"][_sub_idx][0]
    st.divider()

else:
    st.session_state.agente_activo = None
    _es_home = True

# leer desde session_state en secciones
alcance = st.session_state.get("alcance", f"NACIONAL ({pais})")
producto_servicio = st.session_state.get("producto_servicio", "")

# --- Cabecera del agente ESTRATEGIA (antes en el home) ---
if _sec_activa == "inicio":
    st.subheader(t("termometro"))

    cliente_activo_nombre = st.session_state.get("cliente_activo_nombre", "").strip()
    if cliente_activo_nombre:
        st.info(f"👤 Cliente activo: {cliente_activo_nombre}")

    if not st.session_state.get("nicho_guardado") and not st.session_state.get("producto_servicio"):
        st.markdown(t("onboarding"))

if _sec_activa == "inicio" and _opcion_activa == "acciones":
    st.markdown(t("rec_inteligente"))
    if st.button(t("btn_rec")):
        if verificar_creditos(1):
            with st.spinner("Analizando tu negocio..."):
                nicho_tab = st.session_state.get("nicho_guardado", nicho)
                cliente_tab = st.session_state.get("cliente_ideal_guardado", cliente_ideal)
                marca_tab = st.session_state.get("marca_guardada", nombre_marca)
                pais_tab = st.session_state.get("pais_guardado", pais)
                fecha_hoy = dt.now().strftime('%d/%m/%Y')
                _prompt_rec = f"""Actúa como consultor de negocios senior.
Analiza este negocio HOY ({fecha_hoy}):
Marca: {marca_tab} | Nicho: {nicho_tab} | País: {pais_tab}
Producto: {st.session_state.get('producto_servicio', '')}
Cliente ideal: {cliente_tab}

Responde en este formato EXACTO sin introducciones:

## ⚡ ACCIÓN #1 — MÁXIMO IMPACTO HOY
**Qué hacer:** [acción específica y concreta]
**Cómo:** [pasos detallados en menos de 30 minutos]
**Por qué ahora:** [razón urgente basada en el negocio]

## 🔴 ERROR QUE ESTÁS COMETIENDO HOY
[El error más costoso con solución inmediata y paso a paso]

## 💡 OPORTUNIDAD QUE NADIE ESTÁ VIENDO
[Oportunidad concreta y específica para este negocio hoy]

## 📱 POST PARA PUBLICAR HOY
[Copy completo listo para publicar con emojis y CTA fuerte]

## 📊 MÉTRICA QUE DEBES REVISAR HOY
[Qué número mirar, dónde encontrarlo y qué hacer según el resultado]

## 📋 3 TAREAS DE HOY
1. [Tarea 1 — tiempo estimado: X min]
2. [Tarea 2 — tiempo estimado: X min]
3. [Tarea 3 — tiempo estimado: X min]"""
                _resultado_rec = generar_texto(_prompt_rec, max_out=6000)
                email_tab = (st.session_state.get("user_email") or "").strip().lower()
                if email_tab:
                    guardar_reporte(email_tab, "recomendacion", f"Acciones inteligentes {dt.now().strftime('%d/%m/%Y')}", _resultado_rec)
                consumir(1)
                st.session_state["_ed_rec_hoy"] = _resultado_rec
                st.session_state["_ed_prompt_rec_hoy"] = _prompt_rec
    if st.session_state.get("_ed_rec_hoy"):
        st.markdown(st.session_state["_ed_rec_hoy"])
        _panel_edicion(st.session_state["_ed_rec_hoy"], "rec_hoy", max_tokens=6000)
    st.caption("⚡ La acción más importante hoy · 1 crédito" if st.session_state.get("lang") != "en" else "⚡ The most important action today · 1 credit")

if _sec_activa == "inicio" and _opcion_activa == "auditoria":
    st.divider()
    st.markdown("## 🩺 Auditoría Maestra del Negocio")
    st.caption("🩺 Diagnóstico profundo + potencial de mercado · 1 crédito")
    if st.button(t("btn_escanear"), key="btn_auditoria_maestra"):
        if verificar_creditos(1):
            _nicho_am = st.session_state.get("nicho_guardado", nicho)
            _producto_am = st.session_state.get("producto_servicio", "")
            _pais_am = st.session_state.get("pais_guardado", pais)
            _marca_am = st.session_state.get("marca_guardada", nombre_marca)
            _cliente_am = st.session_state.get("cliente_ideal_guardado", cliente_ideal)
            _link_redes_am = st.session_state.get("link_redes", "").strip()
            _link_web_am = st.session_state.get("link_web", "").strip()

            _prompt_scores_am = (
                f"Responde solo con 4 números del 0 al 100 separados por coma. Nada más.\n"
                f"Nicho: {_nicho_am}, País: {_pais_am}\n"
                f"Evalúa: viralidad, demanda, competencia, exito\n"
                f"Respuesta:"
            )
            _numeros_am = []
            for _intento_am in range(3):
                try:
                    _raw_am = client.models.generate_content(
                        model=MODELO_RAPIDO,
                        contents=_prompt_scores_am,
                        config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=30)
                    ).text
                    if _raw_am:
                        _numeros_am = re.findall(r'\d+', _raw_am)
                    if len(_numeros_am) >= 4:
                        break
                except Exception:
                    pass

            if len(_numeros_am) >= 4:
                _s1, _s2, _s3, _s4 = [min(int(n), 100) for n in _numeros_am[:4]]
            else:
                _s1, _s2, _s3, _s4 = 50, 50, 50, 50

            st.session_state["_am_scores"] = (_s1, _s2, _s3, _s4)

            _lineas_am = []
            if _link_redes_am:
                _lineas_am.append(f"Presencia en redes: {_link_redes_am}")
            if _link_web_am:
                _lineas_am.append(f"Web o tienda: {_link_web_am}")
            _info_am = ("\n" + "\n".join(_lineas_am)) if _lineas_am else ""

            _prompt_audit = f"""Eres consultor de negocios senior. Realiza una auditoría completa de este negocio.

Marca: {_marca_am}
Nicho: {_nicho_am}
Producto/Servicio: {_producto_am}
Cliente ideal: {_cliente_am}
País: {_pais_am}{_info_am}

Scores del mercado: Viralidad {_s1}/100, Demanda {_s2}/100, Competencia {_s3}/100, Éxito Global {_s4}/100

Entrega la auditoría completa en este formato:

## 📊 DIAGNÓSTICO ACTUAL
**Nivel del negocio:** [Inicio / Crecimiento / Escalando]
**Principal fortaleza:** [basada en los datos]
**Principal problema:** [el más urgente a resolver]

## 🔥 POTENCIAL DE MERCADO
- Viralidad del nicho: {_s1}/100 — [qué significa esto]
- Demanda actual: {_s2}/100 — [implicación práctica]
- Nivel de competencia: {_s3}/100 — [oportunidad o amenaza]
- Score de éxito estimado: {_s4}/100 — [veredicto]

## ⚠ LOS 3 ERRORES MÁS GRAVES
1. [Error 1 con solución inmediata]
2. [Error 2 con solución inmediata]
3. [Error 3 con solución inmediata]

## 🚀 MAYOR OPORTUNIDAD INMEDIATA
[Oportunidad específica con plan de acción en 3 pasos]

## 📋 PLAN DE ACCIÓN ESTA SEMANA
- Lunes: [acción concreta]
- Miércoles: [acción concreta]
- Viernes: [acción concreta y medible]

## 🏆 VEREDICTO FINAL
[Evaluación directa y honesta del estado del negocio con recomendación principal]"""

            with st.spinner("Generando auditoría completa..."):
                _resultado_am = generar_analitico(_prompt_audit, max_tokens=6000)
            _email_am = (st.session_state.get("user_email") or "").strip().lower()
            if _email_am:
                guardar_reporte(_email_am, "diagnostico", f"Auditoría Maestra {dt.now().strftime('%d/%m/%Y')}", _resultado_am)
            consumir(1)
            st.session_state["_ed_auditoria_maestra"] = _resultado_am
            st.session_state["_ed_prompt_auditoria_maestra"] = _prompt_audit

    if st.session_state.get("_am_scores"):
        _s1, _s2, _s3, _s4 = st.session_state["_am_scores"]
        _c1, _c2, _c3, _c4 = st.columns(4)
        _c1.metric("🔥 Viralidad", f"{_s1}%")
        _c2.metric("🛍 Demanda", f"{_s2}%")
        _c3.metric("⚔ Competencia", f"{_s3}%")
        _c4.metric("🏆 Éxito Global", f"{_s4}/100")

    if st.session_state.get("_ed_auditoria_maestra"):
        st.markdown(st.session_state["_ed_auditoria_maestra"])
        _panel_edicion(st.session_state["_ed_auditoria_maestra"], "auditoria_maestra", max_tokens=6000)

    st.caption("✨ Empieza aquí · 1 crédito" if st.session_state.get("lang") != "en" else "✨ Start here · 1 credit")

if _sec_activa == "inicio" and _opcion_activa == "radar":
    # ── RADAR DE TENDENCIAS VIRALES ───────────────────────────────────────────
    st.divider()
    _radar_title = "\U0001f525 Viral Trends Radar" if st.session_state.get("lang") == "en" else "\U0001f525 Radar de Tendencias Virales"
    st.subheader(_radar_title)
    st.caption("\U0001f525 Qué está viral ahora mismo · Gratis" if st.session_state.get("lang") != "en" else "\U0001f525 What's going viral right now · Free")

    _PYTRENDS_MAP = {
        "PE": "peru", "MX": "mexico", "CO": "colombia",
        "AR": "argentina", "CL": "chile", "ES": "spain", "US": "united_states",
    }
    _REDDIT_MAP = {
        "PE": "peru", "MX": "mexico", "CO": "colombia",
        "AR": "argentina", "CL": "chile", "ES": "spain", "US": "all",
        "BR": "brasil",
    }

    _pais_radar = st.session_state.get("pais_guardado", "Per\u00fa \U0001f1f5\U0001f1ea")
    _iso_radar = ISO_CODES.get(_pais_radar, "PE")
    _now_ts = dt.now().timestamp()
    _last_radar = st.session_state.get("radar_ts", 0)

    if _last_radar:
        _age_min = int((_now_ts - _last_radar) / 60)
        if _age_min < 60:
            _age_str = f"{_age_min} min"
        else:
            _age_str = f"{_age_min // 60}h {_age_min % 60}min"
        _upd_label = f"Updated {_age_str} ago" if st.session_state.get("lang") == "en" else f"Actualizado hace {_age_str}"
        st.caption(_upd_label)

    _btn_viral_lbl = "\U0001f525 See what's viral now (Free)" if st.session_state.get("lang") == "en" else "\U0001f525 Ver qu\u00e9 est\u00e1 viral ahora (Gratis)"
    _btn_refresh_lbl = "\U0001f504 Update now" if st.session_state.get("lang") == "en" else "\U0001f504 Actualizar ahora"
    _do_radar = False
    _col_rv1, _col_rv2 = st.columns([3, 1])
    with _col_rv1:
        if st.button(_btn_viral_lbl, key="btn_radar_viral"):
            _do_radar = True
    with _col_rv2:
        if st.session_state.get("tendencias_virales") and st.button(_btn_refresh_lbl, key="btn_radar_refresh"):
            _do_radar = True

    # Auto-refresh after 2 hours
    if st.session_state.get("tendencias_virales") and _last_radar and (_now_ts - _last_radar) > 7200:
        _do_radar = True

    if _do_radar:
        _spinner_msg = "Scanning viral trends..." if st.session_state.get("lang") == "en" else "Escaneando tendencias virales..."
        with st.spinner(_spinner_msg):
            _gt_list, _yt_list, _rd_list = [], [], []

            # FUENTE 1: Google Trends
            try:
                from pytrends.request import TrendReq as _TrendReq
                _pt = _TrendReq(hl='es-PE', tz=360)
                _pt_code = _PYTRENDS_MAP.get(_iso_radar, "united_states")
                _gt_df = _pt.trending_searches(pn=_pt_code)
                _gt_list = _gt_df[0].tolist()[:10]
            except Exception as _ge:
                print(f"[Radar] Google Trends: {_ge}")

            # FUENTE 2: YouTube API
            try:
                if YOUTUBE_API_KEY:
                    _yt_r = requests.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={"part": "snippet", "chart": "mostPopular",
                                "regionCode": _iso_radar, "maxResults": 5,
                                "key": YOUTUBE_API_KEY},
                        timeout=8
                    )
                    if _yt_r.status_code == 200:
                        _yt_list = [i["snippet"]["title"] for i in _yt_r.json().get("items", [])]
            except Exception as _ye:
                print(f"[Radar] YouTube: {_ye}")

            # FUENTE 3: Reddit
            try:
                _rd_sub = _REDDIT_MAP.get(_iso_radar, "all")
                _rd_r = requests.get(
                    f"https://www.reddit.com/r/{_rd_sub}/hot.json?limit=10",
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=8
                )
                if _rd_r.status_code == 200:
                    _rd_children = _rd_r.json().get("data", {}).get("children", [])
                    _rd_top = sorted(_rd_children, key=lambda x: x["data"].get("num_comments", 0), reverse=True)[:5]
                    _rd_list = [p["data"]["title"] for p in _rd_top]
            except Exception as _re:
                print(f"[Radar] Reddit: {_re}")

            if not _gt_list and not _yt_list and not _rd_list:
                _no_data = "Could not fetch trends. Try again." if st.session_state.get("lang") == "en" else "No se pudo obtener tendencias. Intenta nuevamente."
                st.warning(_no_data)
            else:
                _prompt_radar = (
                    f"Estas son las tendencias virales de HOY en {_pais_radar}:\n"
                    f"\U0001f534 Google Trends (fuente: GOOGLE VIRAL): {_gt_list}\n"
                    f"\U0001f4fa YouTube viral (fuente: YOUTUBE VIRAL): {_yt_list}\n"
                    f"\U0001f4ac Reddit trending (fuente: REDDIT VIRAL): {_rd_list}\n\n"
                    f"Selecciona las 5 m\u00e1s importantes y virales.\n"
                    f"Para cada una responde SOLO en JSON v\u00e1lido (sin texto antes ni despu\u00e9s):\n"
                    '[{"nombre": "texto corto", "descripcion": "qu\u00e9 es en 1 l\u00ednea", "score": 85, "ventana": "urgente", "fuente": "\U0001f534 GOOGLE VIRAL"}]\n'
                    f"ventana debe ser exactamente: urgente, normal, o largo.\n"
                    f"fuente debe ser exactamente uno de: \U0001f534 GOOGLE VIRAL, \U0001f4fa YOUTUBE VIRAL, \U0001f4ac REDDIT VIRAL"
                )
                _raw_trends = generar_texto(_prompt_radar, max_out=3000, modelo=MODELO_FUERTE)
                try:
                    import json as _json_mod
                    _jm = re.search(r'\[.*?\]', _raw_trends, re.DOTALL)
                    if _jm:
                        st.session_state["tendencias_virales"] = _json_mod.loads(_jm.group())
                        st.session_state["radar_ts"] = dt.now().timestamp()
                    else:
                        _parse_err = "Could not parse trends." if st.session_state.get("lang") == "en" else "No se pudo parsear tendencias."
                        st.warning(_parse_err)
                        st.markdown(_raw_trends)
                except Exception as _je:
                    st.error(f"JSON error: {_je}")
                    st.markdown(_raw_trends)

    if st.session_state.get("tendencias_virales"):
        _adaptar_lbl = "Adapt to my business (1 credit)" if st.session_state.get("lang") == "en" else "Adaptar a mi negocio (1 cr\u00e9dito)"
        for _tidx, _tr in enumerate(st.session_state["tendencias_virales"]):
            _tnombre  = _tr.get("nombre", "")
            _tdesc    = _tr.get("descripcion", "")
            _tscore   = _tr.get("score", 0)
            _tventana = _tr.get("ventana", "normal")
            _is_en_r  = st.session_state.get("lang") == "en"
            if _tventana == "urgente":
                _ticon = "\u26a1 Urgent \u2014 act in 24h" if _is_en_r else "\u26a1 Urgente \u2014 act\u00faa en 24h"
            elif _tventana == "normal":
                _ticon = "\u23f0 3 days to leverage it" if _is_en_r else "\u23f0 3 d\u00edas para aprovecharlo"
            else:
                _ticon = "\U0001f4c5 You have 1 week" if _is_en_r else "\U0001f4c5 Tienes 1 semana"
            with st.container(border=True):
                _tc1, _tc2 = st.columns([5, 1])
                with _tc1:
                    _tfuente = _tr.get("fuente", "")
                    _fuente_badge = f" `{_tfuente}`" if _tfuente else ""
                    st.markdown(f"**\U0001f525 {_tnombre}**{_fuente_badge}")
                    st.caption(_tdesc)
                    st.caption(_ticon)
                with _tc2:
                    st.metric("Score", f"{_tscore}/100")
                if st.button(_adaptar_lbl, key=f"adaptar_tr_{_tidx}"):
                    if verificar_creditos(1):
                        _nicho_r  = st.session_state.get("nicho_guardado", nicho)
                        _marca_r  = st.session_state.get("marca_guardada", "")
                        _prod_r   = st.session_state.get("producto_servicio", "")
                        _pais_r   = st.session_state.get("pais_guardado", pais)
                        _prompt_adapt = (
                            f"La tendencia viral del momento es:\n{_tnombre}: {_tdesc}\n\n"
                            f"El negocio es:\nMarca: {_marca_r}\nNicho: {_nicho_r}\n"
                            f"Qu\u00e9 vende: {_prod_r}\nPa\u00eds: {_pais_r}\n\n"
                            f"Crea 4 contenidos que adapten esta tendencia al negocio de forma NATURAL y creativa.\n"
                            f"NO fuerces la conexi\u00f3n \u2014 que sea org\u00e1nico.\n\n"
                            f"1. POST INSTAGRAM/FACEBOOK:\nCopy completo listo para publicar. Con emojis y CTA claro.\n\n"
                            f"2. HOOK TIKTOK/REELS:\nFrase de apertura para los primeros 3 segundos que enganche y conecte la tendencia.\n"
                            f"Luego desarrollo de 20-30 segundos.\n\n"
                            f"3. HISTORIA/STORY:\nTexto corto con pregunta o encuesta.\n\n"
                            f"4. \u00c1NGULO CREATIVO \u00danico:\nUna idea diferente que nadie m\u00e1s est\u00e9 haciendo para conectar esta tendencia con el negocio.\n\n"
                            f"TIMING: cu\u00e1ndo publicar cada pieza exactamente."
                        )
                        with st.spinner("Adaptando tendencia..."):
                            _adapt_res = generar_texto(_prompt_adapt, max_out=4000, modelo=MODELO_FUERTE)
                        st.markdown(_adapt_res)
                        _email_r = (st.session_state.get("user_email") or "").strip().lower()
                        if _email_r:
                            guardar_reporte(_email_r, "tendencia_adaptada", f"Tendencia: {_tnombre}", _adapt_res)
                        consumir(1)

# ── RUTAS GUIADAS: solo en el onboarding de usuarios nuevos (perfil vacío) ──
if _es_home and not st.session_state.get("nicho_guardado") and not st.session_state.get("producto_servicio"):
    # ── RUTA DEL USUARIO ──────────────────────────────────────────────────────
    st.divider()
    _ruta_title = "\U0001f5fa\ufe0f How do you want to use Tentakl today?" if st.session_state.get("lang") == "en" else "\U0001f5fa\ufe0f \u00bfC\u00f3mo quieres usar Tentakl hoy?"
    st.subheader(_ruta_title)

    _RUTAS_ES = [
        {"icon": "\U0001f3ea", "label": "Tengo una tienda", "steps": [
            ("1\ufe0f\u20e3 Configura tu perfil", "Completa tu marca, nicho y qu\u00e9 vendes en el sidebar izquierdo."),
            ("2\ufe0f\u20e3 Analiza tu competencia", "Tab MARKETING \u2192 Esp\u00eda de Competencia"),
            ("3\ufe0f\u20e3 Crea contenido de cat\u00e1logo", "Tab MARKETING \u2192 Campa\u00f1a de Cat\u00e1logo"),
            ("4\ufe0f\u20e3 Cierra m\u00e1s ventas", "Tab VENTAS \u2192 Psic\u00f3logo de Precios"),
        ]},
        {"icon": "\U0001f4bc", "label": "Soy freelancer o agencia", "steps": [
            ("1\ufe0f\u20e3 Define tu cliente ideal", "Sidebar \u2192 bot\u00f3n Detectar Cliente"),
            ("2\ufe0f\u20e3 Crea tu embudo de ventas", "Tab MARKETING \u2192 Embudo de Ventas"),
            ("3\ufe0f\u20e3 Genera cotizaciones", "Tab ADMIN \u2192 Cotizaciones"),
            ("4\ufe0f\u20e3 Protege tu trabajo", "Tab ADMIN \u2192 Contratos"),
        ]},
        {"icon": "\U0001f3ac", "label": "Soy creador de contenido", "steps": [
            ("1\ufe0f\u20e3 Planifica tu semana", "Tab INICIO \u2192 Plan de Contenido Semanal"),
            ("2\ufe0f\u20e3 Domina TikTok/Reels", "Tab MARKETING \u2192 Experto TikTok/Reels"),
            ("3\ufe0f\u20e3 Audita tu contenido", "Tab MARKETING \u2192 Auditor\u00eda Visual (Video/Foto)"),
            ("4\ufe0f\u20e3 Analiza tu audiencia", "Tab MARKETING \u2192 Analizador de Sentimiento"),
        ]},
        {"icon": "\U0001f6e0\ufe0f", "label": "Vendo servicios", "steps": [
            ("1\ufe0f\u20e3 Define tu cliente ideal", "Sidebar \u2192 bot\u00f3n Detectar Cliente"),
            ("2\ufe0f\u20e3 Construye tu marca", "Tab MARKETING \u2192 Storytelling de Marca"),
            ("3\ufe0f\u20e3 Mata las objeciones", "Tab VENTAS \u2192 Mata-Objeciones"),
            ("4\ufe0f\u20e3 Optimiza tus precios", "Tab VENTAS \u2192 Psic\u00f3logo de Precios"),
        ]},
        {"icon": "\U0001f37d\ufe0f", "label": "Tengo un restaurante", "steps": [
            ("1\ufe0f\u20e3 Configura nicho Gastronom\u00eda", "Sidebar \u2192 Nicho \u2192 Gastronom\u00eda"),
            ("2\ufe0f\u20e3 Detecta tendencias locales", "Tab INICIO \u2192 Radar de Tendencias Virales"),
            ("3\ufe0f\u20e3 Muestra tu men\u00fa", "Tab MARKETING \u2192 Campa\u00f1a de Cat\u00e1logo"),
            ("4\ufe0f\u20e3 Atrae clientes locales", "Tab MARKETING \u2192 Segmentaci\u00f3n Ads"),
        ]},
        {"icon": "\U0001f331", "label": "Estoy empezando desde cero", "steps": [
            ("1\ufe0f\u20e3 Configura tu perfil b\u00e1sico", "Sidebar \u2192 completa marca, nicho, qu\u00e9 vendes"),
            ("2\ufe0f\u20e3 Detecta tu potencial", "Tab INICIO \u2192 Escanear Potencial de Hoy"),
            ("3\ufe0f\u20e3 Planifica tu primer contenido", "Tab INICIO \u2192 Plan de Contenido Semanal"),
            ("4\ufe0f\u20e3 Conoce a tu cliente", "Tab MARKETING \u2192 Embudo de Ventas"),
        ]},
    ]
    _RUTAS_EN = [
        {"icon": "\U0001f3ea", "label": "I have a store", "steps": [
            ("1\ufe0f\u20e3 Set up your profile", "Fill in your brand, niche and what you sell in the left sidebar."),
            ("2\ufe0f\u20e3 Analyze your competition", "MARKETING Tab \u2192 Competitor Spy"),
            ("3\ufe0f\u20e3 Create catalog content", "MARKETING Tab \u2192 Catalog Campaign"),
            ("4\ufe0f\u20e3 Close more sales", "SALES Tab \u2192 Price Psychology"),
        ]},
        {"icon": "\U0001f4bc", "label": "I'm a freelancer or agency", "steps": [
            ("1\ufe0f\u20e3 Define your ideal client", "Sidebar \u2192 Detect Client button"),
            ("2\ufe0f\u20e3 Build your sales funnel", "MARKETING Tab \u2192 Sales Funnel"),
            ("3\ufe0f\u20e3 Generate quotes", "ADMIN Tab \u2192 Quotes"),
            ("4\ufe0f\u20e3 Protect your work", "ADMIN Tab \u2192 Contracts"),
        ]},
        {"icon": "\U0001f3ac", "label": "I'm a content creator", "steps": [
            ("1\ufe0f\u20e3 Plan your week", "HOME Tab \u2192 Weekly Content Plan"),
            ("2\ufe0f\u20e3 Master TikTok/Reels", "MARKETING Tab \u2192 TikTok/Reels Expert"),
            ("3\ufe0f\u20e3 Audit your content", "MARKETING Tab \u2192 Visual Audit (Video/Photo)"),
            ("4\ufe0f\u20e3 Analyze your audience", "MARKETING Tab \u2192 Sentiment Analyzer"),
        ]},
        {"icon": "\U0001f6e0\ufe0f", "label": "I sell services", "steps": [
            ("1\ufe0f\u20e3 Define your ideal client", "Sidebar \u2192 Detect Client button"),
            ("2\ufe0f\u20e3 Build your brand", "MARKETING Tab \u2192 Brand Storytelling"),
            ("3\ufe0f\u20e3 Crush objections", "SALES Tab \u2192 Objection Buster"),
            ("4\ufe0f\u20e3 Optimize your prices", "SALES Tab \u2192 Price Psychology"),
        ]},
        {"icon": "\U0001f37d\ufe0f", "label": "I have a restaurant", "steps": [
            ("1\ufe0f\u20e3 Set niche to Gastronomy", "Sidebar \u2192 Niche \u2192 Gastronomy"),
            ("2\ufe0f\u20e3 Detect local trends", "HOME Tab \u2192 Viral Trends Radar"),
            ("3\ufe0f\u20e3 Showcase your menu", "MARKETING Tab \u2192 Catalog Campaign"),
            ("4\ufe0f\u20e3 Attract local customers", "MARKETING Tab \u2192 Ads Segmentation"),
        ]},
        {"icon": "\U0001f331", "label": "I'm starting from scratch", "steps": [
            ("1\ufe0f\u20e3 Set up your basic profile", "Sidebar \u2192 fill in brand, niche, what you sell"),
            ("2\ufe0f\u20e3 Detect your potential", "HOME Tab \u2192 Scan Today's Potential"),
            ("3\ufe0f\u20e3 Plan your first content", "HOME Tab \u2192 Weekly Content Plan"),
            ("4\ufe0f\u20e3 Know your customer", "MARKETING Tab \u2192 Sales Funnel"),
        ]},
    ]

    _is_en_ruta = st.session_state.get("lang") == "en"
    _rutas_list = _RUTAS_EN if _is_en_ruta else _RUTAS_ES
    _ruta_sel = st.session_state.get("ruta_usuario", None)

    _row1 = _rutas_list[:3]
    _row2 = _rutas_list[3:]
    for _ri, _row_items in enumerate([_row1, _row2]):
        _rcols = st.columns(3)
        for _ci2, _ruta_item in enumerate(_row_items):
            with _rcols[_ci2]:
                _is_sel = _ruta_sel == _ruta_item["label"]
                if st.button(
                    f"{_ruta_item['icon']} {_ruta_item['label']}",
                    key=f"ruta_{_ri}_{_ci2}",
                    use_container_width=True,
                    type="primary" if _is_sel else "secondary"
                ):
                    st.session_state["ruta_usuario"] = _ruta_item["label"]
                    st.rerun()

    if _ruta_sel:
        _ruta_found = next((r for r in _rutas_list if r["label"] == _ruta_sel), None)
        if _ruta_found:
            _hoja_lbl = "Your roadmap:" if _is_en_ruta else "Tu hoja de ruta:"
            st.markdown(f"**{_hoja_lbl} {_ruta_found['icon']} {_ruta_found['label']}**")
            for _step_title, _step_desc in _ruta_found["steps"]:
                with st.container(border=True):
                    st.markdown(f"**{_step_title}**")
                    st.caption(_step_desc)


if _sec_activa == "inicio" and _opcion_activa == "plan_semanal":
    st.markdown(t("plan_semanal_titulo"))
    st.caption("\U0001f4c5 Planifica tu semana en 1 clic · 1 crédito" if st.session_state.get("lang") != "en" else "\U0001f4c5 Plan your week in 1 click · 1 credit")
    email_tab = (st.session_state.get("user_email") or "").strip().lower()
    if not email_tab:
        st.warning("Ingresa tu email para usar esta función")
    else:
        semana = obtener_semana_actual()
        st.info(f"📅 Semana actual: {semana}")
        plan_guardado = obtener_plan_semanal(email_tab, semana)

        # ── Memoria: contexto de ultimo Autopiloto ─────────────────────────
        _mem_ap = obtener_ultimo_reporte_tipo(email_tab, ["autopiloto", "estrategia_mes"], dias=7)
        if _mem_ap:
            import re as _re_mem
            _mem_fecha = str(_mem_ap.get("created_at", ""))[:10]
            _mem_ctx = st.session_state.get("plan_usar_autopiloto", False)
            st.info(f"Tu ultimo Autopiloto fue el {_mem_fecha}. Puedes incluir esa estrategia en el plan de esta semana.")
            _mem_col1, _mem_col2 = st.columns(2)
            with _mem_col1:
                if st.button("Si, incluir estrategia del Autopiloto", key="btn_mem_ap_si"):
                    st.session_state["plan_usar_autopiloto"] = True
                    st.session_state["plan_ctx_autopiloto"] = _mem_ap.get("contenido", "")[:600]
                    st.rerun()
            with _mem_col2:
                if st.button("No, generar plan independiente", key="btn_mem_ap_no"):
                    st.session_state["plan_usar_autopiloto"] = False
                    st.session_state.pop("plan_ctx_autopiloto", None)
        # ──────────────────────────────────────────────────────────────────────

        if plan_guardado:
            st.success("✅ Ya tienes un plan guardado para esta semana")
            st.markdown(plan_guardado["contenido"])
            _panel_edicion(plan_guardado["contenido"], "plan_guardado", max_tokens=6000)
            if st.button(t("btn_regenerar_plan")):
                if verificar_creditos(1):
                    consumir(1)
                    with st.spinner("Regenerando estrategia semanal..."):
                        nicho_plan = st.session_state.get("nicho_guardado", "")
                        cliente_plan = st.session_state.get("cliente_ideal_guardado", "")
                        marca_plan = st.session_state.get("marca_guardada", "")
                        _mem_extra_plan = ""
                        if st.session_state.get("plan_usar_autopiloto") and st.session_state.get("plan_ctx_autopiloto"):
                            _mem_extra_plan = f"\nCONTEXTO ESTRATEGIA AUTOPILOTO ANTERIOR:\n{st.session_state['plan_ctx_autopiloto']}\nSe coherente con esa estrategia.\n"
                        _prompt_plan_regen = f"""Eres estratega de contenidos para {pais}.
Marca: {marca_plan} | Nicho: {nicho_plan} | País: {pais}
Producto: {st.session_state.get('producto_servicio', '')} | Cliente: {cliente_plan}{_mem_extra_plan}

Crea el plan semanal en este formato EXACTO:

## 📅 PLAN DE CONTENIDO — ESTA SEMANA

| Día | Red Social | Tipo | Tema | CTA |
|---|---|---|---|---|
| Lunes | | | | |
| Martes | | | | |
| Miércoles | | | | |
| Jueves | | | | |
| Viernes | | | | |

## 🎯 OBJETIVO DE LA SEMANA
- Meta principal: [número concreto]
- Cómo medirlo: [herramienta]

## 🔥 EL POST MÁS IMPORTANTE DE LA SEMANA
[Copy completo del post con mayor potencial viral]

## ⏰ MEJORES HORARIOS PARA {pais}
Instagram: [mejor día y hora]
TikTok: [mejor día y hora]
Facebook: [mejor día y hora]
WhatsApp: [mejor día y hora]"""
                        nuevo_resultado = generar_texto(_prompt_plan_regen, max_out=6000)
                        guardar_plan_semanal(email_tab, semana, nuevo_resultado)
                        guardar_reporte(email_tab, "plan_semanal", f"Plan semanal regenerado {semana}", nuevo_resultado)
                        st.success("🔁 Nuevo plan generado")
                        st.session_state["_ed_plan_regen"] = nuevo_resultado
                        st.session_state["_ed_prompt_plan_regen"] = _prompt_plan_regen
            if st.session_state.get("_ed_plan_regen"):
                st.markdown(st.session_state["_ed_plan_regen"])
                _panel_edicion(st.session_state["_ed_plan_regen"], "plan_regen", max_tokens=6000)
        else:
            st.warning("Aún no tienes plan para esta semana")
            if st.button(t("btn_generar_plan")):
                with st.spinner("Generando estrategia semanal..."):
                    nicho_plan = st.session_state.get("nicho_guardado", "")
                    cliente_plan = st.session_state.get("cliente_ideal_guardado", "")
                    marca_plan = st.session_state.get("marca_guardada", "")
                    _mem_extra_plan = ""
                    if st.session_state.get("plan_usar_autopiloto") and st.session_state.get("plan_ctx_autopiloto"):
                        _mem_extra_plan = f"\nCONTEXTO ESTRATEGIA AUTOPILOTO ANTERIOR:\n{st.session_state['plan_ctx_autopiloto']}\nSe coherente con esa estrategia.\n"
                    _prompt_plan_nuevo = f"""Eres estratega de contenidos para {pais}.
Marca: {marca_plan} | Nicho: {nicho_plan} | País: {pais}
Producto: {st.session_state.get('producto_servicio', '')} | Cliente: {cliente_plan}

Crea el plan semanal en este formato EXACTO:

## 📅 PLAN DE CONTENIDO — ESTA SEMANA

| Día | Red Social | Tipo | Tema | CTA |
|---|---|---|---|---|
| Lunes | | | | |
| Martes | | | | |
| Miércoles | | | | |
| Jueves | | | | |
| Viernes | | | | |

## 🎯 OBJETIVO DE LA SEMANA
- Meta principal: [número concreto]
- Cómo medirlo: [herramienta]

## 🔥 EL POST MÁS IMPORTANTE DE LA SEMANA
[Copy completo del post con mayor potencial viral]

## ⏰ MEJORES HORARIOS PARA {pais}
Instagram: [mejor día y hora]
TikTok: [mejor día y hora]
Facebook: [mejor día y hora]
WhatsApp: [mejor día y hora]"""
                    resultado = generar_texto(_prompt_plan_nuevo, max_out=6000)
                    guardar_plan_semanal(email_tab, semana, resultado)
                    guardar_reporte(email_tab, "plan_semanal", f"Plan semanal {semana}", resultado)
                    st.success("🔥 Plan generado y guardado")
                    st.session_state["_ed_plan_nuevo"] = resultado
                    st.session_state["_ed_prompt_plan_nuevo"] = _prompt_plan_nuevo
            if st.session_state.get("_ed_plan_nuevo"):
                st.markdown(st.session_state["_ed_plan_nuevo"])
                _panel_edicion(st.session_state["_ed_plan_nuevo"], "plan_nuevo", max_tokens=6000)


# --- SECCIÓN: PLANIFICADOR CON TENDENCIAS (Estratega) ---
if _sec_activa == "calendario":
    if not st.session_state.get("user_email", "").strip():
        st.warning("⚠ Ingresa tu email en el sidebar para acceder a esta sección." if st.session_state.get("lang") != "en" else "⚠ Enter your email in the sidebar to access this section.")
        st.info("👈 Panel izquierdo → Tu Cuenta → Email" if st.session_state.get("lang") != "en" else "👈 Left panel → Your Account → Email")
    st.subheader("📅 Planificador Semanal Inteligente")
    st.write("TENTAKL usará tendencias reales (Google Trends + YouTube) para armar tu semana.")
    st.info("✅ Recomendación: genera este plan **1 vez por semana** para mantener la coherencia.")

    if st.button("🪄 Generar Estrategia de la Semana (3 Créditos)"):
        costo = 3
        if verificar_creditos(costo=costo):
            with st.spinner("Leyendo Trends + YouTube y armando tu plan maestro..."):
                trends = obtener_trends(pais, nicho)
                tendencias_txt = "\n".join([f"- {t}" for t in trends["daily"]]) if trends["daily"] else "- (No disponible hoy)"
                related_top_txt = "\n".join([f"- {t}" for t in trends["related_top"]]) if trends["related_top"] else "- (No disponible)"
                tendencias_youtube_txt = obtener_trending_youtube(pais)
                prompt = f"""
Actúa como estratega de contenidos senior.
País: {pais}. Fecha: {trends['fecha']}.
Alcance: {alcance}. Nicho: {nicho}. Marca: {nombre_marca}. Producto/Servicio: {producto_servicio}. Público: {cliente_ideal}.

🔥 TENDENCIAS EN YOUTUBE (Top videos):
{tendencias_youtube_txt}

📈 TENDENCIAS DEL DÍA (Google Trends):
{tendencias_txt}

🔎 BÚSQUEDAS RELACIONADAS TOP (7 días):
{related_top_txt}

TAREA COMPLETA:
Crea un calendario de 7 días detallado que incluya:
1) Cronograma: Qué días grabar y qué días subir.
2) 7 Ideas de videos con HOOKS VIRALES (específicos para {pais}).
3) Estrategia de tendencia: Cómo adaptar los temas de hoy a {nombre_marca}.
4) Checklist de Competencia: Puntos clave para diferenciarte.
5) CTA sugerido: Un llamado a la acción persuasivo por día.

FORMATO: Tabla Markdown profesional y detallada.
TONO: Experto, accionable y adaptado a la moneda {PAISES_MONEDA.get(pais, '$')}.
"""
                texto = generar_texto(prompt, max_out=8000)
                st.markdown(texto)
                consumir(costo=costo)

# --- SECCIÓN: HERRAMIENTAS DE MARKETING (varios agentes) ---
if _sec_activa == "marketing":
    if not st.session_state.get("user_email", "").strip():
        st.warning("⚠ Ingresa tu email en el sidebar para acceder a esta sección." if st.session_state.get("lang") != "en" else "⚠ Enter your email in the sidebar to access this section.")
        st.info("👈 Panel izquierdo → Tu Cuenta → Email" if st.session_state.get("lang") != "en" else "👈 Left panel → Your Account → Email")
    st.subheader(t("motor_atraccion"))
    st.write(t("motor_desc"))
    _mkt_keys = [
        "Auditoría Visual (Video/Foto)", "Experto TikTok/Reels", "Segmentación Ads",
        "Embudo de Ventas",
        "Storytelling de Marca", "Plan de Crisis",
        "SEO y Palabras Clave", "Artículo de Blog SEO",
        "Compliance Checker", "🕵 Inteligencia Competitiva", "Campaña de Catálogo",
        "Generador de Imagenes", "Simulador de Campaña",
    ]
    opcion_mkt = _opcion_activa

    if opcion_mkt == "Auditoría Visual (Video/Foto)":
        st.info("Sube tu contenido. La IA analizará calidad técnica, retención y ganchos.")
        archivo = st.file_uploader("Sube archivo:", type=["mp4", "jpg", "png", "jpeg"])
        st.caption("✅ Recomendación: Para videos, usa clips cortos (máx. 60s).")
        if archivo and st.button("Auditar Calidad (3 Créditos)"):
            costo = 3
            if verificar_creditos(costo=costo):
                with st.spinner("El Director Creativo está revisando..."):
                    prompt = f"""
Actúa como Productor de Cine y Experto en YouTube/TikTok.
País: {pais}. Alcance: {alcance}. Nicho: {nicho}. Producto/Servicio: {producto_servicio}. Público: {cliente_ideal}.
Analiza este contenido visual y entrégame:
1) 🎨 CALIDAD VISUAL (1-10): iluminación, encuadre, color, nitidez.
2) 🎣 GANCHO/RETENCIÓN: evalúa los primeros 3 segundos.
3) 🧠 MENSAJE: ¿queda claro qué se ofrece?
4) 🛠 ERRORES TÉCNICOS: audio, texto, ritmo.
5) ✅ PROPUESTA MEJORADA:
   - Hook alternativo (1 frase viral)
   - 3 bullets de estructura
   - CTA final claro
"""
                    texto = generar_multimodal(prompt, archivo.type, archivo.getvalue(), max_out=4000)
                    st.markdown(texto)
                    consumir(costo=costo)

    elif opcion_mkt == "Experto TikTok/Reels":
        modo = st.radio("¿Qué necesitas?", ["Ideas Virales", "Mejorar Guion", "Anti-Ban (Políticas)"])
        st.divider()
        if modo == "Ideas Virales":
            modo_ideas = st.radio(
                "¿Qué quieres hacer?",
                ["💡 Generar ideas virales nuevas", "🔍 Evaluar mi idea", "✨ Mejorar una idea que me gustó"],
                key="modo_ideas_tiktok"
            )
            if modo_ideas == "💡 Generar ideas virales nuevas":
                if st.button("Generar 5 Ideas (1 Crédito)"):
                    if verificar_creditos(1):
                        prompt = f"""Eres estratega viral de TikTok para {pais}.
Marca: {nombre_marca} | Nicho: {nicho} | Producto: {producto_servicio}

Genera 5 ideas de TikToks/Reels para esta semana:

### IDEA 1 — [Nombre del concepto]
🎣 HOOK (primeros 3 segundos): [frase exacta]
📹 ESTRUCTURA: [descripción de los 15-60 segundos]
🎵 AUDIO SUGERIDO: [tipo de audio o canción]
📊 POR QUÉ VA A FUNCIONAR: [razón basada en {pais}]

### IDEA 2 — [Nombre del concepto]
🎣 HOOK (primeros 3 segundos): [frase exacta]
📹 ESTRUCTURA: [descripción de los 15-60 segundos]
🎵 AUDIO SUGERIDO: [tipo de audio o canción]
📊 POR QUÉ VA A FUNCIONAR: [razón basada en {pais}]

### IDEA 3 — [Nombre del concepto]
🎣 HOOK (primeros 3 segundos): [frase exacta]
📹 ESTRUCTURA: [descripción de los 15-60 segundos]
🎵 AUDIO SUGERIDO: [tipo de audio o canción]
📊 POR QUÉ VA A FUNCIONAR: [razón basada en {pais}]

### IDEA 4 — [Nombre del concepto]
🎣 HOOK (primeros 3 segundos): [frase exacta]
📹 ESTRUCTURA: [descripción de los 15-60 segundos]
🎵 AUDIO SUGERIDO: [tipo de audio o canción]
📊 POR QUÉ VA A FUNCIONAR: [razón basada en {pais}]

### IDEA 5 — [Nombre del concepto]
🎣 HOOK (primeros 3 segundos): [frase exacta]
📹 ESTRUCTURA: [descripción de los 15-60 segundos]
🎵 AUDIO SUGERIDO: [tipo de audio o canción]
📊 POR QUÉ VA A FUNCIONAR: [razón basada en {pais}]"""
                        try:
                            _tiktok_res = generar_texto(prompt, max_out=6000)
                            if _tiktok_res and not _tiktok_res.startswith("❌"):
                                st.session_state["_ed_tkt_ideas"] = _tiktok_res
                                st.session_state["_ed_prompt_tkt_ideas"] = prompt
                            else:
                                st.error(f"Error generando ideas TikTok: {_tiktok_res or 'Respuesta vacía del modelo'}")
                        except Exception as _te:
                            st.error(f"Error al generar ideas TikTok: {_te}")
                        consumir(1)
                if st.session_state.get("_ed_tkt_ideas"):
                    st.markdown(st.session_state["_ed_tkt_ideas"])
                    _panel_edicion(st.session_state["_ed_tkt_ideas"], "tkt_ideas", max_tokens=6000)
            elif modo_ideas == "🔍 Evaluar mi idea":
                idea_usuario = st.text_area(
                    "Describe tu idea de video",
                    placeholder="Ej: Quiero hacer un video mostrando cómo es por dentro un departamento de lujo en construcción...",
                    height=150,
                    key="idea_evaluar_input"
                )
                if idea_usuario and st.button("Evaluar mi idea (1 Crédito)", key="btn_evaluar_idea"):
                    if verificar_creditos(1):
                        prompt = f"""Eres experto en contenido viral para TikTok e Instagram en {pais}, nicho: {nicho}.

El usuario tiene esta idea de video:
{idea_usuario}

Analiza:

## 📊 POTENCIAL VIRAL
Puntuación: [X/10]
Por qué: [razón específica para {pais}]

## ✅ LO QUE FUNCIONA
[qué tiene de bueno esta idea]

## ⚠ EL PROBLEMA
[qué podría fallar y por qué]

## 🚀 VERSIÓN MEJORADA
[la misma idea pero potenciada]

## 🎣 3 HOOKS PARA ESTA IDEA
Hook 1: [primeros 3 segundos opción A]
Hook 2: [primeros 3 segundos opción B]
Hook 3: [primeros 3 segundos opción C]

## 📅 MEJOR MOMENTO PARA PUBLICAR
[día y hora específica para {pais}]"""
                        try:
                            _eval_res = generar_texto(prompt, max_out=6000)
                            if _eval_res and not _eval_res.startswith("❌"):
                                st.session_state["_ed_tkt_eval"] = _eval_res
                                st.session_state["_ed_prompt_tkt_eval"] = prompt
                            else:
                                st.error(f"Error evaluando idea: {_eval_res or 'Respuesta vacía del modelo'}")
                        except Exception as _ee:
                            st.error(f"Error al evaluar idea: {_ee}")
                        consumir(1)
                if st.session_state.get("_ed_tkt_eval"):
                    st.markdown(st.session_state["_ed_tkt_eval"])
                    _panel_edicion(st.session_state["_ed_tkt_eval"], "tkt_eval", max_tokens=6000)
            elif modo_ideas == "✨ Mejorar una idea que me gustó":
                idea_usuario = st.text_area(
                    "¿Qué idea quieres potenciar?",
                    placeholder="Pega o describe la idea que generó Tentakl o que se te ocurrió...",
                    height=150,
                    key="idea_mejorar_input"
                )
                if idea_usuario and st.button("Potenciar mi idea (1 Crédito)", key="btn_mejorar_idea"):
                    if verificar_creditos(1):
                        prompt = f"""Eres experto en contenido viral para TikTok e Instagram en {pais}, nicho: {nicho}.
Marca: {nombre_marca} | Producto: {producto_servicio}

El usuario tiene esta idea que le gustó:
{idea_usuario}

Genera 5 variaciones mejoradas con hooks distintos:

## 🚀 VARIACIÓN 1
🎣 Hook: [primeros 3 segundos]
📹 Desarrollo: [cómo grabar el video]
🎯 Por qué funciona: [razón específica]

## 🚀 VARIACIÓN 2
🎣 Hook: [primeros 3 segundos]
📹 Desarrollo: [cómo grabar el video]
🎯 Por qué funciona: [razón específica]

## 🚀 VARIACIÓN 3
🎣 Hook: [primeros 3 segundos]
📹 Desarrollo: [cómo grabar el video]
🎯 Por qué funciona: [razón específica]

## 🚀 VARIACIÓN 4
🎣 Hook: [primeros 3 segundos]
📹 Desarrollo: [cómo grabar el video]
🎯 Por qué funciona: [razón específica]

## 🚀 VARIACIÓN 5
🎣 Hook: [primeros 3 segundos]
📹 Desarrollo: [cómo grabar el video]
🎯 Por qué funciona: [razón específica]

## 💡 CUÁL PUBLICAR PRIMERO
[recomendación con justificación para {pais}]"""
                        try:
                            _mejora_res = generar_texto(prompt, max_out=6000)
                            if _mejora_res and not _mejora_res.startswith("❌"):
                                st.session_state["_ed_tkt_mejora"] = _mejora_res
                                st.session_state["_ed_prompt_tkt_mejora"] = prompt
                            else:
                                st.error(f"Error mejorando idea: {_mejora_res or 'Respuesta vacía del modelo'}")
                        except Exception as _me:
                            st.error(f"Error al mejorar idea: {_me}")
                        consumir(1)
                if st.session_state.get("_ed_tkt_mejora"):
                    st.markdown(st.session_state["_ed_tkt_mejora"])
                    _panel_edicion(st.session_state["_ed_tkt_mejora"], "tkt_mejora", max_tokens=6000)
        elif modo == "Mejorar Guion":
            modo_guion = st.radio(
                "¿Qué quieres hacer con tu guión?",
                ["🎬 Generar guión nuevo", "✏ Mejorar mi guión existente", "✅ Revisar si mi guión funcionará"],
                key="modo_guion_tiktok"
            )
            if modo_guion == "🎬 Generar guión nuevo":
                txt = st.text_area("Pega tu guion borrador:")
                if txt and st.button("Viralizar Guion (1 Crédito)"):
                    if verificar_creditos(1):
                        prompt = f"Mejora este guion para máxima retención en {pais}.\nNicho: {nicho}. Producto/Servicio: {producto_servicio}.\nHazlo más dinámico, corta el relleno y pon un HOOK explosivo al inicio.\nGuion Original: \"{txt}\""
                        try:
                            _guion_res = generar_texto(prompt, max_out=6000)
                            if _guion_res and not _guion_res.startswith("❌"):
                                st.session_state["_ed_tkt_gnuevo"] = _guion_res
                                st.session_state["_ed_prompt_tkt_gnuevo"] = prompt
                            else:
                                st.error(f"Error mejorando guion: {_guion_res or 'Respuesta vacía del modelo'}")
                        except Exception as _ge:
                            st.error(f"Error al mejorar guion: {_ge}")
                        consumir(1)
                if st.session_state.get("_ed_tkt_gnuevo"):
                    st.markdown(st.session_state["_ed_tkt_gnuevo"])
                    _panel_edicion(st.session_state["_ed_tkt_gnuevo"], "tkt_gnuevo", max_tokens=6000)
            elif modo_guion == "✏ Mejorar mi guión existente":
                guion_usuario = st.text_area(
                    "Pega tu guión aquí",
                    placeholder="Escribe o pega el guión que ya tienes y Tentakl lo mejorará...",
                    height=200,
                    key="guion_mejorar_input"
                )
                if guion_usuario and st.button("Mejorar mi guión (1 Crédito)", key="btn_mejorar_guion"):
                    if verificar_creditos(1):
                        prompt = f"""Eres experto en TikTok y Reels para {pais}, especialista en el nicho {nicho}.

El usuario tiene este guión:
{guion_usuario}

Analiza y mejora el guión considerando:
1. ¿El hook (primeros 3 segundos) engancha?
2. ¿El ritmo es adecuado para TikTok?
3. ¿Hay llamada a la acción clara?
4. ¿Conecta con el público de {pais}?

Entrega:

## ✅ LO QUE ESTÁ BIEN
[qué partes funcionan y por qué]

## ⚠ LO QUE HAY QUE MEJORAR
[problemas específicos con solución]

## 🎬 VERSIÓN MEJORADA COMPLETA
[el guión reescrito y mejorado]

## 📊 PROBABILIDAD DE VIRAL
[del 1 al 10 con justificación]

## 💡 3 VARIACIONES ADICIONALES
[3 versiones diferentes del mismo guión]"""
                        try:
                            _mejora_guion_res = generar_texto(prompt, max_out=6000)
                            if _mejora_guion_res and not _mejora_guion_res.startswith("❌"):
                                st.session_state["_ed_tkt_gmejorar"] = _mejora_guion_res
                                st.session_state["_ed_prompt_tkt_gmejorar"] = prompt
                            else:
                                st.error(f"Error mejorando guión: {_mejora_guion_res or 'Respuesta vacía del modelo'}")
                        except Exception as _mge:
                            st.error(f"Error al mejorar guión: {_mge}")
                        consumir(1)
                if st.session_state.get("_ed_tkt_gmejorar"):
                    st.markdown(st.session_state["_ed_tkt_gmejorar"])
                    _panel_edicion(st.session_state["_ed_tkt_gmejorar"], "tkt_gmejorar", max_tokens=6000)
            elif modo_guion == "✅ Revisar si mi guión funcionará":
                guion_usuario = st.text_area(
                    "Pega tu guión aquí",
                    placeholder="Escribe o pega el guión que ya tienes y Tentakl lo mejorará...",
                    height=200,
                    key="guion_revisar_input"
                )
                if guion_usuario and st.button("Revisar mi guión (1 Crédito)", key="btn_revisar_guion"):
                    if verificar_creditos(1):
                        prompt = f"""Eres experto en TikTok y Reels para {pais}, especialista en el nicho {nicho}.

El usuario tiene este guión y quiere saber si va a funcionar:
{guion_usuario}

Haz un análisis de rendimiento predictivo:

## 🎯 DIAGNÓSTICO GENERAL
[evaluación honesta del guión]

## 📊 MÉTRICAS PREDICHAS
- Tasa de retención estimada: [%]
- Probabilidad de completar el video: [%]
- Potencial de shares: [bajo/medio/alto]
- Probabilidad viral: [X/10]

## 🎣 ANÁLISIS DEL HOOK
[los primeros 3 segundos: ¿van a funcionar? ¿por qué?]

## ⏱ ANÁLISIS DEL RITMO
[¿el ritmo mantiene la atención en TikTok?]

## 📢 ANÁLISIS DEL CTA
[¿la llamada a la acción es efectiva?]

## 🌎 ADAPTACIÓN A {pais}
[¿conecta culturalmente con el público de {pais}?]

## ✅ VEREDICTO FINAL
[¿publicar tal cual, mejorar antes, o rehacer?]

## 🔧 LOS 3 CAMBIOS URGENTES
[si hay que mejorar, ¿qué cambiar primero?]"""
                        try:
                            _revisar_guion_res = generar_texto(prompt, max_out=6000)
                            if _revisar_guion_res and not _revisar_guion_res.startswith("❌"):
                                st.session_state["_ed_tkt_grevisar"] = _revisar_guion_res
                                st.session_state["_ed_prompt_tkt_grevisar"] = prompt
                            else:
                                st.error(f"Error revisando guión: {_revisar_guion_res or 'Respuesta vacía del modelo'}")
                        except Exception as _rge:
                            st.error(f"Error al revisar guión: {_rge}")
                        consumir(1)
                if st.session_state.get("_ed_tkt_grevisar"):
                    st.markdown(st.session_state["_ed_tkt_grevisar"])
                    _panel_edicion(st.session_state["_ed_tkt_grevisar"], "tkt_grevisar", max_tokens=6000)
        elif modo == "Anti-Ban":
            txt = st.text_area("Texto que te preocupa:")
            if txt and st.button("Revisar Políticas (1 Crédito)"):
                if verificar_creditos(1):
                    prompt = f"Reescribe este texto para evitar bloqueos en TikTok/Meta Ads.\nMantén la intención de venta pero usa palabras seguras.\nTexto: \"{txt}\""
                    try:
                        _ban_res = generar_texto(prompt, max_out=6000)
                        if _ban_res and not _ban_res.startswith("❌"):
                            st.success(_ban_res)
                        else:
                            st.error(f"Error Anti-Ban: {_ban_res or 'Respuesta vacía del modelo'}")
                    except Exception as _be:
                        st.error(f"Error al revisar políticas Anti-Ban: {_be}")
                    consumir(1)

    elif opcion_mkt == "Segmentación Ads":
        st.write("Genera públicos detallados para Facebook/Instagram Ads.")
        _seg_email = (st.session_state.get("user_email") or "").strip().lower()
        _seg_catalogo = db_get_catalogo(_seg_email) if _seg_email else []
        if _seg_catalogo:
            _seg_nombres = [p["nombre"] for p in _seg_catalogo]
            _seg_sel = st.selectbox("Elige el producto a anunciar:", _seg_nombres, key="seg_ads_cat_sel")
            prod = _seg_sel
        else:
            prod = st.text_input("Producto a anunciar:", placeholder="Ej: Depas en preventa")
        objetivo = st.selectbox("Objetivo:", ["Ventas", "Leads/WhatsApp", "Tráfico"])
        moneda = PAISES_MONEDA.get(pais, "$")
        if prod and st.button("Generar Segmentación Completa (2 Créditos)"):
            if verificar_creditos(2):
                prompt = f"""Eres Trafficker Digital experto en Facebook Ads para {pais}.
Nicho: {nicho}
Producto/Servicio: {producto_servicio}
Producto específico a anunciar: {prod}
Objetivo de campaña: {objetivo}
Cliente ideal: {cliente_ideal}
Moneda local: {moneda}

Genera una estrategia de segmentación completa:

## 1. PÚBLICO FRÍO — Facebook Ads Manager
- Rango de edad exacto
- Género y porcentaje sugerido (ej: 70% mujeres / 30% hombres)
- Ciudades específicas de {pais} para segmentar
- Lista de 8-10 intereses EXACTOS para copiar en Facebook Ads Manager
- Comportamientos de compra relevantes
- Dispositivos sugeridos (móvil/escritorio y sistema operativo)

## 2. PÚBLICO TIBIO — Remarketing
- Cómo configurar el píxel para este objetivo
- Audiencias personalizadas sugeridas (visitantes web, interacción con perfil, etc.)
- Ventana de tiempo recomendada (7, 14, 30 días)

## 3. PÚBLICO CALIENTE — Lookalike
- Porcentaje de similitud recomendado (1%, 2%, 3%)
- Fuente del lookalike más efectiva para este negocio

## 4. PRESUPUESTO SUGERIDO en {moneda}
- Presupuesto mínimo diario para ver resultados
- Presupuesto óptimo para escalar
- Distribución recomendada por tipo de público (% frío / tibio / caliente)

## 5. ESTRATEGIA DE COPY POR PÚBLICO
- Mensaje clave para público frío (problema o deseo)
- Mensaje clave para público tibio (objeción o prueba social)
- Mensaje clave para público caliente (urgencia o beneficio directo)
- Formato de anuncio recomendado por temperatura (imagen/video/carrusel)
- Mejor horario para mostrar los anuncios en {pais}

Completa todas las secciones. No cortes el texto a la mitad."""
                with st.spinner("Generando estrategia de segmentación..."):
                    texto = generar_texto(prompt, max_out=6000)
                st.markdown(texto)
                email_tab = (st.session_state.get("user_email") or "").strip().lower()
                if email_tab:
                    guardar_reporte(email_tab, "segmentacion_ads", f"Segmentación: {prod}", texto)
                consumir(2)

    elif opcion_mkt == "Embudo de Ventas":
        st.write("Define el recorrido ideal para convertir desconocidos en clientes.")
        objetivo_embudo = st.text_input("¿Qué quieres vender?", placeholder="Ej: Packs de maca negra / Depas en Surco")
        if objetivo_embudo and st.button("Generar Embudo (2 Créditos)"):
            if verificar_creditos(2):
                prompt = f"Eres estratega de marketing y ventas.\nConstruye un embudo de ventas claro para:\nMarca: {nombre_marca}\nNicho: {nicho}\nProducto/Servicio: {producto_servicio}\nPaís: {pais}\nCliente ideal: {cliente_ideal}\nOferta específica: {objetivo_embudo}\nDame: etapa atracción, interés, conversión, seguimiento, contenido por etapa y CTA."
                texto = generar_texto(prompt, max_out=8000)
                st.markdown(texto)
                email_tab = (st.session_state.get("user_email") or "").strip().lower()
                if email_tab:
                    guardar_reporte(email_tab, "embudo_ventas", f"Embudo de ventas - {objetivo_embudo}", texto)
                consumir(2)

    elif opcion_mkt == "Storytelling de Marca":
        _st_marca   = st.session_state.get("marca_guardada", "") or nombre_marca
        _st_nicho   = st.session_state.get("nicho_guardado", "") or nicho
        _st_pais    = st.session_state.get("pais_guardado", "") or pais
        _st_prod    = st.session_state.get("producto_servicio", "") or producto_servicio
        _st_cliente = st.session_state.get("cliente_ideal_guardado", "") or cliente_ideal
        _st_reglas  = st.session_state.get("reglas_marca", "")
        if _st_marca or _st_nicho:
            st.info(f"✅ Perfil cargado: **{_st_marca}** | {_st_nicho} | {_st_pais}")
        st.write("Construye una historia de marca que conecte y venda.")
        historia_extra = st.text_area("¿Algo especial sobre tu historia? (opcional)", placeholder="Ej: Empecé buscando mejorar mi energía con productos naturales...", height=80)
        if st.button("Crear Storytelling (1 Crédito)"):
            if verificar_creditos(1):
                _hist_ctx = f"\nContexto adicional: {historia_extra}" if historia_extra.strip() else ""
                _reglas_ctx = f"\nSigue estas reglas de marca: {_st_reglas}" if _st_reglas else ""
                _prompt_story = f"Eres experto en branding y storytelling.\nConstruye una historia de marca para:\nMarca: {_st_marca}\nNicho: {_st_nicho}\nProducto/Servicio: {_st_prod}\nPaís: {_st_pais}\nCliente ideal: {_st_cliente}{_hist_ctx}{_reglas_ctx}\nDame: historia corta emocional, historia larga, versión para Instagram bio y frase de posicionamiento."
                texto = generar_texto(_prompt_story, max_out=8000)
                email_tab = (st.session_state.get("user_email") or "").strip().lower()
                if email_tab:
                    guardar_reporte(email_tab, "storytelling", f"Storytelling de marca - {_st_marca}", texto)
                consumir(1)
                st.session_state["_ed_storytelling"] = texto
                st.session_state["_ed_prompt_storytelling"] = _prompt_story
        if st.session_state.get("_ed_storytelling"):
            st.markdown(st.session_state["_ed_storytelling"])
            _panel_edicion(st.session_state["_ed_storytelling"], "storytelling", max_tokens=8000)

    elif opcion_mkt == "Plan de Crisis":
        st.write("Prepara una respuesta inteligente ante comentarios negativos o situaciones delicadas.")
        situacion_crisis = st.text_area("Describe la situación o pega el comentario del cliente:", placeholder="Ej: Un cliente dijo que el producto no le funcionó y está comentando en redes.")
        if situacion_crisis and st.button("Generar Plan de Crisis (1 Crédito)"):
            if verificar_creditos(1):
                prompt = (
                    f"Eres especialista en reputación de marca.\nAnaliza:\n"
                    f"Marca: {nombre_marca}\nNicho: {nicho}\nProducto/Servicio: {producto_servicio}\n"
                    f"País: {pais}\nSituación: {situacion_crisis}\n"
                    f"Dame:\n"
                    f"## 🚨 RESPUESTA PÚBLICA SUGERIDA\n[Texto listo para publicar]\n\n"
                    f"## 📩 MENSAJE PRIVADO AL CLIENTE\n[Texto listo para enviar por DM]\n\n"
                    f"## ❌ ERRORES QUE NO COMETER\n[Lista de 3-5 errores comunes]\n\n"
                    f"## 💡 CÓMO CONVERTIRLO EN OPORTUNIDAD\n[Estrategia concreta]\n\n"
                    f"## 🎯 TONO RECOMENDADO\n[Empático / Profesional / Directo — con justificación]"
                )
                texto = generar_texto(prompt, max_out=5000)
                st.markdown(texto)
                email_tab = (st.session_state.get("user_email") or "").strip().lower()
                if email_tab:
                    guardar_reporte(email_tab, "plan_crisis", f"Plan de crisis - {nombre_marca}", texto)
                consumir(1)

    elif opcion_mkt == "SEO y Palabras Clave":
        st.write("Genera palabras clave, meta tags y copies para Google Ads optimizados para tu negocio.")
        producto_seo = st.text_input("¿Qué producto o servicio quieres posicionar?", placeholder="Ej: clases de yoga online para mujeres")
        if producto_seo and st.button("Generar SEO Completo (2 Créditos)"):
            if verificar_creditos(2):
                reglas = st.session_state.get("reglas_marca", "")
                reglas_txt = f"\nReglas de marca a respetar:\n{reglas}" if reglas else ""
                prompt = f"""Eres experto en SEO y Google Ads para el mercado de {pais}.
Producto/Servicio: {producto_seo}
Nicho: {nicho}
País objetivo: {pais}{reglas_txt}

Genera:
1. 10 palabras clave con volumen estimado (alto/medio/bajo) y dificultad (alta/media/baja)
2. Meta título optimizado (máx 60 caracteres)
3. Meta descripción optimizada (máx 160 caracteres)
4. 3 copies completos para Google Ads con titular, descripción 1 y descripción 2

Sé específico para el mercado de {pais}. Completa todas las oraciones. No cortes el texto a la mitad."""
                with st.spinner("Generando estrategia SEO..."):
                    texto = generar_texto(prompt, max_out=4000)
                st.markdown(texto)
                email_tab = (st.session_state.get("user_email") or "").strip().lower()
                if email_tab:
                    guardar_reporte(email_tab, "seo", f"SEO: {producto_seo}", texto)
                consumir(2)

    elif opcion_mkt == "Artículo de Blog SEO":
        st.write("Genera un artículo completo optimizado para SEO con estructura H1/H2/H3.")
        tema_blog = st.text_input("Tema del artículo:", placeholder="Ej: Cómo elegir los mejores lentes según tu tipo de rostro")
        if tema_blog and st.button("Generar Artículo Completo (3 Créditos)"):
            if verificar_creditos(3):
                reglas = st.session_state.get("reglas_marca", "")
                reglas_txt = f"\nReglas de marca a respetar:\n{reglas}" if reglas else ""
                _prompt_blog = f"""Eres redactor SEO experto para el mercado de {pais}.
Tema: {tema_blog}
Nicho: {nicho}
Marca: {nombre_marca}
País: {pais}{reglas_txt}

Escribe el artículo COMPLETO en una sola respuesta con esta estructura:

# [H1: Título principal optimizado para SEO]

[Introducción de 2-3 párrafos que enganchen al lector y presenten el tema]

## [H2: Sección 1 — subtítulo con keyword]
[3-4 párrafos completos desarrollando esta sección]

## [H2: Sección 2 — subtítulo con keyword]
[3-4 párrafos completos desarrollando esta sección]

## [H2: Sección 3 — subtítulo con keyword]
[3-4 párrafos completos desarrollando esta sección]

## Conclusión
[2 párrafos de cierre con CTA claro hacia {producto_servicio}]

**Meta título SEO:** (máx 60 caracteres)
**Meta descripción:** (máx 160 caracteres)

Completa TODAS las secciones. No cortes el texto a la mitad. Usa lenguaje natural y persuasivo."""

                with st.spinner("Redactando artículo completo..."):
                    _texto_blog = generar_texto(_prompt_blog, max_out=8000)
                email_tab = (st.session_state.get("user_email") or "").strip().lower()
                if email_tab:
                    guardar_reporte(email_tab, "blog_seo", f"Blog: {tema_blog}", _texto_blog)
                consumir(3)
                st.session_state["_ed_blog_seo"] = _texto_blog
                st.session_state["_ed_prompt_blog_seo"] = _prompt_blog
        if st.session_state.get("_ed_blog_seo"):
            st.markdown(st.session_state["_ed_blog_seo"])
            _panel_edicion(st.session_state["_ed_blog_seo"], "blog_seo", max_tokens=8000)

    elif opcion_mkt == "Compliance Checker":
        st.write("Verifica tu copy, genera anuncios seguros o consigue ideas sin riesgo de rechazo en Meta y TikTok.")
        _cc_modo = st.radio(
            "Que necesitas?",
            ["Verificar mi copy existente", "Generar anuncio seguro desde cero", "Dame 3 ideas seguras para este producto"],
            key="cc_modo_radio",
            horizontal=True
        )

        if _cc_modo == "Verificar mi copy existente":
            _copy_check = st.text_area(
                "Pega tu copy de anuncio aqu\u00ed:",
                placeholder="Ej: \u00a1Pierde 10 kilos en 2 semanas garantizado! Oferta exclusiva...",
                key="cc_copy_verificar"
            )
            if _copy_check and st.button("Verificar Compliance (1 Credito)", key="btn_cc_verificar"):
                if verificar_creditos(1):
                    _prompt_cc_ver = f"""Eres experto en pol\u00edticas publicitarias de Facebook Ads, Instagram Ads y TikTok Ads.
Analiza este copy de anuncio:

"{_copy_check}"

Nicho: {nicho}
Pa\u00eds: {pais}

Entrega el an\u00e1lisis completo en este formato:

## \ud83d\udd0d FRASES PROBLEM\u00c1TICAS DETECTADAS
[Lista cada frase peligrosa con la pol\u00edtica espec\u00edfica que viola y por qu\u00e9]

## \u2705 VERSI\u00d3N CORREGIDA COMPLETA
[El copy reescrito completo sin frases peligrosas, manteniendo el mensaje original]

## \ud83d\udcca SCORE DE SEGURIDAD: [n\u00famero del 0 al 100]
**Veredicto:** [breve explicaci\u00f3n del score]

S\u00e9 espec\u00edfico. Completa todas las secciones."""
                    with st.spinner("Analizando compliance..."):
                        _res_cc_ver = generar_analitico(_prompt_cc_ver, max_tokens=6000)
                    _email_cc = (st.session_state.get("user_email") or "").strip().lower()
                    if _email_cc:
                        guardar_reporte(_email_cc, "compliance", f"Compliance check - {dt.now().strftime('%d/%m/%Y')}", _res_cc_ver)
                    consumir(1)
                    st.session_state["_ed_cc_ver"] = _res_cc_ver
                    st.session_state["_ed_prompt_cc_ver"] = _prompt_cc_ver
            if st.session_state.get("_ed_cc_ver"):
                st.markdown(st.session_state["_ed_cc_ver"])
                _panel_edicion(st.session_state["_ed_cc_ver"], "cc_ver", max_tokens=6000)

        elif _cc_modo == "Generar anuncio seguro desde cero":
            _cc_producto = st.text_input(
                "\u00bfQu\u00e9 quieres anunciar?",
                placeholder="Ej: Suplemento de magnesio para mejorar el sue\u00f1o - S/45",
                value=st.session_state.get("compliance_producto", ""),
                key="compliance_producto"
            )
            if _cc_producto and st.button("Generar anuncio seguro (1 credito)", key="btn_cc_seguro"):
                if verificar_creditos(1):
                    _marca_cc = st.session_state.get("marca_guardada", "")
                    _pais_cc = st.session_state.get("pais_guardado", pais)
                    _prompt_cc_seg = f"""Eres experto en publicidad digital y pol\u00edticas de Meta y TikTok Ads.
Genera un anuncio publicitario completo y 100% seguro para:
Producto/Servicio: {_cc_producto}
Negocio: {_marca_cc}
Pa\u00eds: {_pais_cc}
Nicho: {nicho}

## \ud83d\udcf1 VERSI\u00d3N FEED (Facebook/Instagram)
**Titular:** [gancho sin frases prohibidas]
**Texto principal:** [2-3 p\u00e1rrafos persuasivos y seguros]
**CTA:** [llamada a la acci\u00f3n clara]

## \ud83d\udcf2 VERSI\u00d3N STORY
**Texto corto:** [1 oraci\u00f3n impactante]
**CTA:** [acci\u00f3n directa]

## \u2705 SCORE DE SEGURIDAD ESTIMADO: [n\u00famero del 0 al 100]
**Frases que evitamos y por qu\u00e9:** [lista breve]

Completa todas las secciones."""
                    with st.spinner("Generando anuncio seguro..."):
                        _res_cc_seg = generar_analitico(_prompt_cc_seg, max_tokens=6000)
                    _email_cc = (st.session_state.get("user_email") or "").strip().lower()
                    if _email_cc:
                        guardar_reporte(_email_cc, "compliance", f"Anuncio seguro - {_cc_producto[:40]}", _res_cc_seg)
                    consumir(1)
                    st.session_state["_ed_cc_seg"] = _res_cc_seg
                    st.session_state["_ed_prompt_cc_seg"] = _prompt_cc_seg
            if st.session_state.get("_ed_cc_seg"):
                st.markdown(st.session_state["_ed_cc_seg"])
                _panel_edicion(st.session_state["_ed_cc_seg"], "cc_seg", max_tokens=6000)

        elif _cc_modo == "Dame 3 ideas seguras para este producto":
            _cc_producto_ideas = st.text_input(
                "\u00bfQu\u00e9 quieres promocionar?",
                placeholder="Ej: Curso de fotograf\u00eda online - $97",
                key="cc_producto_ideas"
            )
            if _cc_producto_ideas and st.button("Dame 3 ideas seguras (1 credito)", key="btn_cc_ideas"):
                if verificar_creditos(1):
                    _pais_cc_i = st.session_state.get("pais_guardado", pais)
                    _prompt_cc_ideas = f"""Eres experto en publicidad digital para el mercado de {_pais_cc_i}.
El usuario quiere anunciar: {_cc_producto_ideas}
Nicho: {nicho}

Genera exactamente 3 ideas de anuncios creativos 100% seguros para Facebook, Instagram y TikTok Ads.

## \ud83d\udca1 IDEA 1 \u2014 [\u00c1ngulo: beneficio principal]
**Titular:** (m\u00e1x 40 caracteres)
**Texto principal:** (2-3 oraciones completas y persuasivas)
**CTA:** (llamada a la acci\u00f3n clara)
**Por qu\u00e9 es segura:** (breve explicaci\u00f3n)

## \ud83d\udca1 IDEA 2 \u2014 [\u00c1ngulo: problema que resuelve]
**Titular:** (m\u00e1x 40 caracteres)
**Texto principal:** (2-3 oraciones completas y persuasivas)
**CTA:** (llamada a la acci\u00f3n clara)
**Por qu\u00e9 es segura:** (breve explicaci\u00f3n)

## \ud83d\udca1 IDEA 3 \u2014 [\u00c1ngulo: prueba social]
**Titular:** (m\u00e1x 40 caracteres)
**Texto principal:** (2-3 oraciones completas y persuasivas)
**CTA:** (llamada a la acci\u00f3n clara)
**Por qu\u00e9 es segura:** (breve explicaci\u00f3n)

Completa todas las secciones."""
                    with st.spinner("Generando ideas seguras..."):
                        _res_cc_ideas = generar_analitico(_prompt_cc_ideas, max_tokens=6000)
                    _email_cc = (st.session_state.get("user_email") or "").strip().lower()
                    if _email_cc:
                        guardar_reporte(_email_cc, "compliance", f"Ideas seguras - {_cc_producto_ideas[:40]}", _res_cc_ideas)
                    consumir(1)
                    st.session_state["_ed_cc_ideas"] = _res_cc_ideas
                    st.session_state["_ed_prompt_cc_ideas"] = _prompt_cc_ideas
            if st.session_state.get("_ed_cc_ideas"):
                st.markdown(st.session_state["_ed_cc_ideas"])
                _panel_edicion(st.session_state["_ed_cc_ideas"], "cc_ideas", max_tokens=6000)

    elif opcion_mkt == "🕵 Inteligencia Competitiva":
        st.write("Analiza a tu competencia por nombre o link para descubrir sus debilidades y los gaps que tú puedes aprovechar.")
        _ic_input = st.text_input(
            "Nombre o link del competidor:",
            placeholder="Ej: 'Clinica Dental Sonrisa' o instagram.com/competidor",
            key="ic_input"
        )
        # ── Memoria: analisis previo del mismo competidor ──────────────────
        if _ic_input:
            _ic_email_mem = (st.session_state.get("user_email") or "").strip().lower()
            if _ic_email_mem:
                _ic_prev = obtener_ultimo_reporte_tipo(_ic_email_mem, ["sentimiento"], dias=60)
                if _ic_prev and _ic_input.lower()[:15] in _ic_prev.get("titulo", "").lower():
                    _ic_prev_fecha = str(_ic_prev.get("created_at", ""))[:10]
                    st.info(f"Ya analizaste este competidor el {_ic_prev_fecha}.")
                    _ic_col1, _ic_col2 = st.columns(2)
                    with _ic_col1:
                        if st.button("Ver analisis anterior", key="btn_ic_prev_ver"):
                            st.session_state["_ed_intel_comp"] = _ic_prev.get("contenido", "")
                    with _ic_col2:
                        st.button("Hacer analisis nuevo", key="btn_ic_nuevo_ok")
        # ─────────────────────────────────────────────────────────────────────
        _ic_url = st.text_input(
            "URL del sitio web del competidor (opcional, para análisis real):",
            placeholder="Ej: competidor.com",
            key="ic_url_scrape"
        )
        if _ic_input and st.button("🕵 Analizar Competidor (2 Creditos)", key="btn_ic_analizar"):
            if verificar_creditos(2):
                _pais_ic = st.session_state.get("pais_guardado", pais)
                # ── CAMBIO 5: scraping real del sitio del competidor ──────────
                _ic_scrape_txt = ""
                if _ic_url.strip():
                    with st.spinner("🌐 Leyendo el sitio del competidor..."):
                        _ic_sc = scrapear_url(_ic_url)
                    if _ic_sc.get("error"):
                        st.warning(f"🌐 {_ic_sc['error']} El análisis seguirá sin datos del sitio.")
                    else:
                        _ic_scrape_txt = ("\n\nDATOS REALES EXTRAÍDOS DE SU SITIO WEB (usa esto como fuente principal):\n"
                                          + _scrape_a_texto(_ic_sc))
                        st.success(f"✅ Sitio leído: {_ic_sc['title'][:60]}")
                _prompt_ic = f"""Eres analista de inteligencia competitiva de marketing digital experto en el mercado de {_pais_ic}.

Competidor a analizar: {_ic_input}{_ic_scrape_txt}
Nicho del usuario: {nicho}
Producto/Servicio propio: {producto_servicio}
País: {_pais_ic}

Realiza un análisis de inteligencia competitiva completo y estructurado:

## 🎯 PERFIL DEL COMPETIDOR
- Posicionamiento probable en el mercado
- Segmento de clientes que ataca
- Propuesta de valor aparente

## ⚠ DEBILIDADES DETECTADAS
[Las 3-5 principales debilidades o gaps típicos de competidores en este nicho en {_pais_ic}]

## 💬 QUEJAS FRECUENTES DE SUS CLIENTES
[Lo que los clientes suelen reclamar de negocios similares en este nicho — basado en patrones del mercado]

## ✅ QUÉ HACE BIEN (para aprender)
[2-3 fortalezas típicas de competidores posicionados en este nicho]

## 🚀 3 OPORTUNIDADES DE DIFERENCIACIÓN
1. [Oportunidad 1 — cómo explotarla con tu negocio]
2. [Oportunidad 2 — cómo explotarla con tu negocio]
3. [Oportunidad 3 — cómo explotarla con tu negocio]

## 📢 ÁNGULOS DE ATAQUE PARA TUS ANUNCIOS
1. **Ángulo 1:** [mensaje específico que golpea la debilidad del competidor]
2. **Ángulo 2:** [mensaje específico que golpea la debilidad del competidor]
3. **Ángulo 3:** [mensaje específico que golpea la debilidad del competidor]

## 🏆 ESTRATEGIA RECOMENDADA
[Plan concreto de 3 acciones para ganarle mercado a este competidor en los próximos 30 días]

Sé concreto, directo y accionable. Basa todo en patrones reales del mercado de {_pais_ic} para el nicho {nicho}."""
                with st.spinner("Analizando inteligencia competitiva..."):
                    _res_ic = generar_analitico(_prompt_ic, max_tokens=6000)
                _email_ic = (st.session_state.get("user_email") or "").strip().lower()
                if _email_ic:
                    guardar_reporte(_email_ic, "sentimiento", f"Inteligencia Competitiva: {_ic_input}", _res_ic)
                consumir(2)
                st.session_state["_ed_intel_comp"] = _res_ic
                st.session_state["_ed_prompt_intel_comp"] = _prompt_ic
        if st.session_state.get("_ed_intel_comp"):
            st.markdown(st.session_state["_ed_intel_comp"])
            _panel_edicion(st.session_state["_ed_intel_comp"], "intel_comp", max_tokens=6000)

    elif opcion_mkt == "Campaña de Catálogo":
        moneda_cat = PAISES_MONEDA.get(pais, "$")
        reglas_cat = st.session_state.get("reglas_marca", "")
        reglas_cat_txt = f"\nReglas de marca:\n{reglas_cat}" if reglas_cat else ""
        user_email_cat = (st.session_state.get("user_email") or "").strip().lower()

        # ── Cargar catálogo (con cache en session_state) ──────────────────────
        if (
            "catalogo_guardado" not in st.session_state
            or st.session_state.get("catalogo_guardado_email") != user_email_cat
        ):
            if user_email_cat:
                st.session_state["catalogo_guardado"] = db_get_catalogo(user_email_cat)
                st.session_state["catalogo_guardado_email"] = user_email_cat
            else:
                st.session_state["catalogo_guardado"] = []

        catalogo_db = st.session_state.get("catalogo_guardado", [])
        tiene_catalogo = len(catalogo_db) > 0

        # ── Helper: parsear línea "Nombre - Precio" ───────────────────────────
        def _parsear_linea(linea):
            linea = linea.strip().lstrip("-•*").strip()
            partes = linea.split(" - ", 1)
            nombre_p = partes[0].strip()
            precio_p = partes[1].strip() if len(partes) > 1 else ""
            return nombre_p, precio_p

        # ── Helper: guardar lista de strings en Supabase ──────────────────────
        def _guardar_lista(lineas, fuente_txt):
            if not user_email_cat:
                st.warning("Ingresa tu email primero para guardar el catálogo.")
                return 0
            guardados = 0
            for linea in lineas:
                nombre_p, precio_p = _parsear_linea(linea)
                if nombre_p:
                    if db_guardar_producto(user_email_cat, nombre_p, precio_p, fuente=fuente_txt):
                        guardados += 1
            # Sincronizar imagen_url desde la tienda conectada (fuentes de tienda)
            if fuente_txt in ("tienda", "woocommerce", "shopify", "tiendanube"):
                _n_img_sync = db_actualizar_imagenes_desde_tienda(user_email_cat)
                if _n_img_sync:
                    st.caption(f"🖼 {_n_img_sync} imagen(es) de producto sincronizadas desde tu tienda")
            # Refrescar cache
            st.session_state["catalogo_guardado"] = db_get_catalogo(user_email_cat)
            st.session_state["catalogo_guardado_email"] = user_email_cat
            return guardados

        # ══════════════════════════════════════════════════════════════════════
        # TIENE CATÁLOGO GUARDADO
        # ══════════════════════════════════════════════════════════════════════
        if tiene_catalogo:
            st.success(f"✅ Tienes **{len(catalogo_db)}** producto(s) en tu catálogo")

            opciones_cat = []
            for p in catalogo_db:
                label = p["nombre"]
                if p.get("precio"):
                    label += f" - {p['precio']}"
                opciones_cat.append(label)

            productos_seleccionados = st.multiselect(
                "Selecciona los productos para tu campaña (máx 10):",
                options=opciones_cat,
                default=opciones_cat[:min(5, len(opciones_cat))],
                key="cat_multiselect_db"
            )
            if len(productos_seleccionados) > 10:
                st.warning("Máximo 10 productos. Se usarán los primeros 10.")
                productos_seleccionados = productos_seleccionados[:10]

            col_b1, col_b2, col_b3 = st.columns(3)
            with col_b1:
                btn_generar = st.button("🚀 Generar Campaña (3 Créditos)", key="cat_btn_generar", use_container_width=True)
            with col_b2:
                btn_agregar = st.button("➕ Agregar más productos", key="cat_btn_agregar", use_container_width=True)
            with col_b3:
                btn_gestionar = st.button("🗑 Gestionar catálogo", key="cat_btn_gestionar", use_container_width=True)

            if btn_agregar:
                st.session_state["cat_modo"] = "agregar"
            if btn_gestionar:
                st.session_state["cat_modo"] = "gestionar"

            # ── Modo: Agregar más ─────────────────────────────────────────────
            if st.session_state.get("cat_modo") == "agregar":
                st.markdown("---")
                st.markdown("#### ➕ Agregar productos al catálogo")
                fuente_add = st.selectbox(
                    "Fuente:",
                    ["Importar desde mi tienda", "Lista manual", "API de Shopify", "API de WooCommerce", "API de TiendaNube"],
                    key="cat_fuente_add"
                )
                if fuente_add == "Importar desde mi tienda":
                    _cfg_tienda_cat = obtener_config_tienda(user_email_cat)
                    if not _cfg_tienda_cat:
                        st.info("Ve a Tab Admin → Conectar Tienda para importar tus productos automáticamente")
                    else:
                        with st.spinner("Cargando productos de tu tienda..."):
                            _prods_tienda_cat = obtener_productos_tienda(user_email_cat)
                        if not _prods_tienda_cat:
                            st.warning("Tu tienda no tiene productos publicados.")
                        else:
                            st.success(f"\u2705 {len(_prods_tienda_cat)} productos encontrados en tu tienda")
                        if st.button("Seleccionar todos", key="cat_tienda_all_add"):
                            st.session_state["cat_tienda_sel_add"] = [p["nombre"] for p in _prods_tienda_cat]
                        _cols_t = st.columns([1, 3, 2])
                        _tienda_sel_nombres = []
                        for _pt in _prods_tienda_cat:
                            _check_key = f"cat_tienda_chk_add_{_pt['id']}"
                            _checked = st.session_state.get("cat_tienda_sel_add") and _pt["nombre"] in st.session_state.get("cat_tienda_sel_add", [])
                            with st.container():
                                _cc1, _cc2, _cc3 = st.columns([1, 3, 2])
                                with _cc1:
                                    if _pt.get("foto_url"):
                                        st.image(_pt["foto_url"], width=60)
                                with _cc2:
                                    st.markdown(f"**{_pt['nombre']}**")
                                with _cc3:
                                    if st.checkbox(f"{moneda_cat}{_pt['precio']}", key=_check_key, value=bool(_checked)):
                                        _tienda_sel_nombres.append(_pt["nombre"])
                        if _tienda_sel_nombres and st.button("\U0001f4be Guardar seleccionados", key="cat_tienda_save_add"):
                            n = _guardar_lista(_tienda_sel_nombres, "tienda")
                            st.success(f"\u2705 {n} producto(s) guardados.")
                            st.session_state.pop("cat_modo", None)
                            st.rerun()

                elif fuente_add == "Lista manual":
                    nueva_lista = st.text_area(
                        "Pega los nuevos productos (uno por línea):",
                        placeholder="- Producto Nuevo S/99 - Descripción\n- Otro Producto S/45",
                        height=150, key="cat_add_manual_txt"
                    )
                    if nueva_lista and st.button("💾 Guardar en mi catálogo", key="cat_save_add_manual"):
                        lineas = [l for l in nueva_lista.strip().split("\n") if l.strip()]
                        n = _guardar_lista(lineas, "manual")
                        st.success(f"✅ {n} producto(s) agregados.")
                        st.session_state.pop("cat_modo", None)
                        st.rerun()

                elif fuente_add == "API de Shopify":
                    sh_url = st.text_input("URL Shopify:", placeholder="mitienda.myshopify.com", key="cat_sh_url_add")
                    sh_key = st.text_input("Access Token:", type="password", key="cat_sh_key_add")
                    if sh_url and sh_key and st.button("Conectar Shopify", key="cat_sh_connect_add"):
                        with st.spinner("Cargando desde Shopify..."):
                            try:
                                base = ("https://" + sh_url.rstrip("/")) if not sh_url.startswith("http") else sh_url.rstrip("/")
                                r = requests.get(f"{base}/admin/api/2024-01/products.json?limit=100",
                                                 headers={"X-Shopify-Access-Token": sh_key}, timeout=15)
                                if r.status_code == 200:
                                    prods_sh = r.json().get("products", [])
                                    lineas_sh = [f"{p.get('title','')} - {moneda_cat}{p.get('variants',[{}])[0].get('price','')}" for p in prods_sh]
                                    st.session_state["cat_prods_temp"] = lineas_sh
                                    st.success(f"{len(lineas_sh)} productos cargados.")
                                else:
                                    st.error(f"Error {r.status_code}: {r.text[:200]}")
                            except Exception as ex:
                                st.error(f"Error: {ex}")
                    if st.session_state.get("cat_prods_temp"):
                        sel_sh = st.multiselect("Selecciona los que quieres guardar:", st.session_state["cat_prods_temp"], key="cat_sh_sel_add")
                        if sel_sh and st.button("💾 Guardar seleccionados", key="cat_sh_save_add"):
                            n = _guardar_lista(sel_sh, "shopify")
                            st.success(f"✅ {n} producto(s) guardados.")
                            st.session_state.pop("cat_modo", None)
                            st.session_state.pop("cat_prods_temp", None)
                            st.rerun()

                elif fuente_add == "API de WooCommerce":
                    woo_url = st.text_input("URL WordPress:", placeholder="mitienda.com", key="cat_woo_url_add")
                    woo_ck = st.text_input("Consumer Key:", type="password", key="cat_woo_ck_add")
                    woo_cs = st.text_input("Consumer Secret:", type="password", key="cat_woo_cs_add")
                    if woo_url and woo_ck and woo_cs and st.button("Conectar WooCommerce", key="cat_woo_connect_add"):
                        with st.spinner("Cargando desde WooCommerce..."):
                            try:
                                base_woo = ("https://" + woo_url.rstrip("/")) if not woo_url.startswith("http") else woo_url.rstrip("/")
                                r_woo = requests.get(f"{base_woo}/wp-json/wc/v3/products",
                                                     params={"per_page": 100}, auth=(woo_ck, woo_cs), timeout=15)
                                if r_woo.status_code == 200:
                                    lineas_woo = [f"{p.get('name','')} - {moneda_cat}{p.get('price','')}" for p in r_woo.json()]
                                    st.session_state["cat_prods_temp"] = lineas_woo
                                    st.success(f"{len(lineas_woo)} productos cargados.")
                                else:
                                    st.error(f"Error {r_woo.status_code}: {r_woo.text[:200]}")
                            except Exception as ex:
                                st.error(f"Error: {ex}")
                    if st.session_state.get("cat_prods_temp"):
                        sel_woo = st.multiselect("Selecciona los que quieres guardar:", st.session_state["cat_prods_temp"], key="cat_woo_sel_add")
                        if sel_woo and st.button("💾 Guardar seleccionados", key="cat_woo_save_add"):
                            n = _guardar_lista(sel_woo, "woocommerce")
                            st.success(f"✅ {n} producto(s) guardados.")
                            st.session_state.pop("cat_modo", None)
                            st.session_state.pop("cat_prods_temp", None)
                            st.rerun()

                elif fuente_add == "API de TiendaNube":
                    tn_id = st.text_input("ID de tienda:", placeholder="123456", key="cat_tn_id_add")
                    tn_tok = st.text_input("Token:", type="password", key="cat_tn_tok_add")
                    if tn_id and tn_tok and st.button("Conectar TiendaNube", key="cat_tn_connect_add"):
                        with st.spinner("Cargando desde TiendaNube..."):
                            try:
                                r_tn = requests.get(
                                    f"https://api.tiendanube.com/v1/{tn_id}/products",
                                    headers={"Authentication": f"bearer {tn_tok}", "User-Agent": "TENTAKL-AI/1.0"},
                                    params={"per_page": 100}, timeout=15
                                )
                                if r_tn.status_code == 200:
                                    lineas_tn = []
                                    for p in r_tn.json():
                                        nombre_tn = (p.get("name") or {}).get("es", "") or str(p.get("name", ""))
                                        precio_tn = (p.get("variants") or [{}])[0].get("price", "")
                                        lineas_tn.append(f"{nombre_tn} - {moneda_cat}{precio_tn}" if precio_tn else nombre_tn)
                                    st.session_state["cat_prods_temp"] = lineas_tn
                                    st.success(f"{len(lineas_tn)} productos cargados.")
                                else:
                                    st.error(f"Error {r_tn.status_code}: {r_tn.text[:200]}")
                            except Exception as ex:
                                st.error(f"Error: {ex}")
                    if st.session_state.get("cat_prods_temp"):
                        sel_tn = st.multiselect("Selecciona los que quieres guardar:", st.session_state["cat_prods_temp"], key="cat_tn_sel_add")
                        if sel_tn and st.button("💾 Guardar seleccionados", key="cat_tn_save_add"):
                            n = _guardar_lista(sel_tn, "tiendanube")
                            st.success(f"✅ {n} producto(s) guardados.")
                            st.session_state.pop("cat_modo", None)
                            st.session_state.pop("cat_prods_temp", None)
                            st.rerun()

            # ── Modo: Gestionar ───────────────────────────────────────────────
            elif st.session_state.get("cat_modo") == "gestionar":
                st.markdown("---")
                st.markdown("#### 🗑 Gestionar mi catálogo")

                # Agregar producto manual
                with st.expander("➕ Agregar producto manualmente"):
                    gc_nombre = st.text_input("Nombre:", key="gc_nombre_new")
                    gc_precio = st.text_input("Precio:", key="gc_precio_new")
                    gc_desc = st.text_input("Descripción (opcional):", key="gc_desc_new")
                    if gc_nombre and st.button("Agregar producto", key="gc_add_btn"):
                        if db_guardar_producto(user_email_cat, gc_nombre.strip(), gc_precio.strip(), gc_desc.strip()):
                            st.session_state["catalogo_guardado"] = db_get_catalogo(user_email_cat)
                            st.success(f"✅ '{gc_nombre}' agregado.")
                            st.rerun()

                # Lista de todos los productos
                todos_cat = db_get_catalogo_todos(user_email_cat)
                if not todos_cat:
                    st.info("No hay productos.")
                else:
                    st.caption(f"Total: {len(todos_cat)} productos (incluyendo desactivados)")
                    for prod in todos_cat:
                        pid = prod["id"]
                        activo_p = prod.get("activo", True)
                        c1, c2, c3, c4, c5 = st.columns([3, 2, 1, 1, 1])
                        with c1:
                            n_edit = st.text_input("", value=prod.get("nombre", ""), key=f"gc_ne_{pid}", label_visibility="collapsed")
                        with c2:
                            p_edit = st.text_input("", value=prod.get("precio", ""), key=f"gc_pe_{pid}", label_visibility="collapsed")
                        with c3:
                            if st.button("💾", key=f"gc_sv_{pid}", help="Guardar"):
                                db_actualizar_producto(pid, {"nombre": n_edit, "precio": p_edit})
                                st.session_state["catalogo_guardado"] = db_get_catalogo(user_email_cat)
                                st.rerun()
                        with c4:
                            toggle_lbl = "✅" if activo_p else "❌"
                            if st.button(toggle_lbl, key=f"gc_tg_{pid}", help="Activar/Desactivar"):
                                db_actualizar_producto(pid, {"activo": not activo_p})
                                st.session_state["catalogo_guardado"] = db_get_catalogo(user_email_cat)
                                st.rerun()
                        with c5:
                            if st.button("🗑", key=f"gc_dl_{pid}", help="Eliminar"):
                                db_eliminar_producto(pid)
                                st.session_state["catalogo_guardado"] = db_get_catalogo(user_email_cat)
                                st.rerun()

            # ── Generar campaña ───────────────────────────────────────────────
            if btn_generar and productos_seleccionados:
                if verificar_creditos(3):
                    catalogo_txt = "\n".join(f"- {p}" for p in productos_seleccionados)
                    prompt_catalogo = f"""Eres experto en marketing digital y publicidad pagada para {pais}.
Nicho: {nicho}
Cliente ideal: {cliente_ideal}
País: {pais}
Moneda local: {moneda_cat}{reglas_cat_txt}

Catálogo de productos/servicios:
{catalogo_txt}

Para CADA producto o servicio genera:

### [Nombre del producto]

**A) ANUNCIO FACEBOOK/INSTAGRAM**
- Titular gancho (basado en problema o deseo del cliente ideal)
- Texto principal completo (3-4 líneas con emojis estratégicos)
- CTA específico

**B) CAPTION TIKTOK**
- Gancho inicial (primera línea que detiene el scroll)
- Texto completo
- Hashtags específicos para {pais} (8-10 hashtags)

**C) MENSAJE WHATSAPP BUSINESS**
- Saludo + presentación
- *Precio* destacado con negritas
- Beneficios en bullets (máx 4)
- CTA con llamada a la acción

**D) SEGMENTACIÓN ESPECÍFICA**
- Público exacto para ese producto en {pais}
- 5 intereses exactos para copiar en Facebook Ads Manager
- Presupuesto mínimo diario sugerido en {moneda_cat}

---

Al final agrega:
## ESTRATEGIA GENERAL DE CAMPAÑA
- Orden de lanzamiento recomendado de los productos
- Cómo hacer una campaña de catálogo cohesionada
- Temporadas o fechas clave en {pais} para activar cada producto

Completa todas las secciones. No cortes el texto a la mitad."""
                    with st.spinner("Generando campaña de catálogo..."):
                        texto_cat = generar_texto(prompt_catalogo, max_out=4000)
                    if user_email_cat:
                        guardar_reporte(user_email_cat, "catalogo", f"Campaña catálogo - {dt.now().strftime('%d/%m/%Y')}", texto_cat)
                    consumir(3)
                    st.session_state["_ed_cat_camp"] = texto_cat
                    st.session_state["_ed_prompt_cat_camp"] = prompt_catalogo
            if st.session_state.get("_ed_cat_camp"):
                st.markdown(st.session_state["_ed_cat_camp"])
                _panel_edicion(st.session_state["_ed_cat_camp"], "cat_camp", max_tokens=4000)
                # ── Puente: crear banner real con la imagen de un producto ─────
                _prods_img_pc = [_p for _p in catalogo_db if (_p.get("imagen_url") or "").strip()]
                if _prods_img_pc:
                    st.divider()
                    _is_en_pc = st.session_state.get("lang") == "en"
                    st.markdown("🎨 " + ("**¿Quieres el banner real de un producto de esta campaña?**"
                                         if not _is_en_pc else "**Want the real banner for a product in this campaign?**"))
                    if st.button("🖼️ " + ("Crear banner con imagen real del producto (5 créditos)"
                                          if not _is_en_pc else "Create banner with the real product image (5 credits)"),
                                 key="btn_puente_banner"):
                        st.session_state.agente_activo = "imagenes"
                        st.session_state["sub_imagenes"] = ("🎨 Generador de Imágenes Premium"
                                                            if not _is_en_pc else "🎨 Premium Image Generator")
                        st.session_state["ig2_fuente"] = ("🛍 De mi catálogo" if not _is_en_pc
                                                          else "🛍 From my catalog")
                        st.rerun()

        # ══════════════════════════════════════════════════════════════════════
        # SIN CATÁLOGO — AGREGAR PRIMERA VEZ
        # ══════════════════════════════════════════════════════════════════════
        else:
            st.info("Aún no tienes productos guardados. Agrega tu catálogo:")
            fuente_new = st.selectbox(
                "¿Cómo tienes tu catálogo?",
                ["Importar desde mi tienda", "Lista de productos o servicios", "API de Shopify", "API de WooCommerce", "API de TiendaNube"],
                index=0, key="cat_fuente_new"
            )
            st.divider()

            if fuente_new == "Importar desde mi tienda":
                _cfg_tienda_new = obtener_config_tienda(user_email_cat)
                if not _cfg_tienda_new:
                    st.info("Ve a Tab Admin → Conectar Tienda para importar tus productos automáticamente")
                else:
                    with st.spinner("Cargando productos de tu tienda..."):
                        _prods_tienda_new = obtener_productos_tienda(user_email_cat)
                    if not _prods_tienda_new:
                        st.info("No se encontraron productos publicados en tu tienda. Verifica que tienes productos activos en WooCommerce.")
                    else:
                        st.success(f"\u2705 {len(_prods_tienda_new)} productos encontrados en tu tienda")
                        if st.button("Seleccionar todos", key="cat_tienda_all_new"):
                            st.session_state["cat_tienda_sel_new"] = [p["nombre"] for p in _prods_tienda_new]
                    _tienda_sel_new_nombres = []
                    for _pt in (_prods_tienda_new or []):
                        _check_key_n = f"cat_tienda_chk_new_{_pt['id']}"
                        _checked_n = _pt["nombre"] in st.session_state.get("cat_tienda_sel_new", [])
                        _cc1n, _cc2n, _cc3n = st.columns([1, 3, 2])
                        with _cc1n:
                            if _pt.get("foto_url"):
                                st.image(_pt["foto_url"], width=60)
                        with _cc2n:
                            st.markdown(f"**{_pt['nombre']}**")
                        with _cc3n:
                            if st.checkbox(f"{moneda_cat}{_pt['precio']}", key=_check_key_n, value=bool(_checked_n)):
                                _tienda_sel_new_nombres.append(_pt["nombre"])
                    if _tienda_sel_new_nombres and st.button("\U0001f4be Guardar seleccionados", key="cat_tienda_save_new"):
                        n = _guardar_lista(_tienda_sel_new_nombres, "tienda")
                        st.success(f"\u2705 {n} producto(s) guardados.")
                        st.session_state.pop("cat_prods_temp", None)
                        st.rerun()

            elif fuente_new == "Lista de productos o servicios":
                st.info("Pega tu lista — uno por línea con nombre, precio y descripción opcional.")
                lista_raw = st.text_area(
                    "Tu catálogo:",
                    placeholder="Ej:\n- Citrato Magnesio S/45 - Para el sueño\n- Omega 3 S/89 - Para el corazón\n- Vitamina C S/35 - Para defensas",
                    height=200, key="cat_lista_raw_new"
                )
                if lista_raw:
                    # Preview de productos detectados
                    lineas_prev = [l.strip().lstrip("-•*").strip() for l in lista_raw.strip().split("\n") if l.strip()]
                    st.markdown(f"**Vista previa — {len(lineas_prev)} producto(s) detectados:**")
                    for lp in lineas_prev[:20]:
                        st.caption(f"• {lp}")
                    if len(lineas_prev) > 20:
                        st.caption(f"... y {len(lineas_prev)-20} más")
                    if st.button("💾 Guardar en mi catálogo", key="cat_save_new_manual"):
                        if not user_email_cat:
                            st.warning("Ingresa tu email en el sidebar para guardar.")
                        else:
                            n = _guardar_lista(lineas_prev, "manual")
                            st.success(f"✅ {n} producto(s) guardados. Recarga para verlos.")
                            st.rerun()

            elif fuente_new == "API de Shopify":
                sh_url_n = st.text_input("URL de tu tienda Shopify:", placeholder="mitienda.myshopify.com", key="cat_sh_url_n")
                sh_key_n = st.text_input("Access Token:", type="password", key="cat_sh_key_n")
                if sh_url_n and sh_key_n and st.button("Cargar desde Shopify", key="cat_sh_btn_n"):
                    with st.spinner("Conectando con Shopify..."):
                        try:
                            base = ("https://" + sh_url_n.rstrip("/")) if not sh_url_n.startswith("http") else sh_url_n.rstrip("/")
                            r = requests.get(f"{base}/admin/api/2024-01/products.json?limit=100",
                                             headers={"X-Shopify-Access-Token": sh_key_n}, timeout=15)
                            if r.status_code == 200:
                                prods_sh_n = r.json().get("products", [])
                                lineas_sh_n = [f"{p.get('title','')} - {moneda_cat}{p.get('variants',[{}])[0].get('price','')}" for p in prods_sh_n]
                                st.session_state["cat_prods_temp"] = lineas_sh_n
                                st.success(f"{len(lineas_sh_n)} productos cargados.")
                            else:
                                st.error(f"Error {r.status_code}: {r.text[:200]}")
                        except Exception as ex:
                            st.error(f"Error: {ex}")
                if st.session_state.get("cat_prods_temp"):
                    sel_sh_n = st.multiselect("Selecciona los que quieres guardar:", st.session_state["cat_prods_temp"],
                                               default=st.session_state["cat_prods_temp"][:20], key="cat_sh_sel_n")
                    if sel_sh_n and st.button("💾 Guardar seleccionados en catálogo", key="cat_sh_save_n"):
                        n = _guardar_lista(sel_sh_n, "shopify")
                        st.success(f"✅ {n} producto(s) guardados.")
                        st.session_state.pop("cat_prods_temp", None)
                        st.rerun()

            elif fuente_new == "API de WooCommerce":
                woo_url_n = st.text_input("URL de tu tienda WordPress:", placeholder="mitienda.com", key="cat_woo_url_n")
                woo_ck_n = st.text_input("Consumer Key:", type="password", key="cat_woo_ck_n")
                woo_cs_n = st.text_input("Consumer Secret:", type="password", key="cat_woo_cs_n")
                if woo_url_n and woo_ck_n and woo_cs_n and st.button("Cargar desde WooCommerce", key="cat_woo_btn_n"):
                    with st.spinner("Conectando con WooCommerce..."):
                        try:
                            base_woo_n = ("https://" + woo_url_n.rstrip("/")) if not woo_url_n.startswith("http") else woo_url_n.rstrip("/")
                            r_woo_n = requests.get(f"{base_woo_n}/wp-json/wc/v3/products",
                                                   params={"per_page": 100}, auth=(woo_ck_n, woo_cs_n), timeout=15)
                            if r_woo_n.status_code == 200:
                                lineas_woo_n = [f"{p.get('name','')} - {moneda_cat}{p.get('price','')}" for p in r_woo_n.json()]
                                st.session_state["cat_prods_temp"] = lineas_woo_n
                                st.success(f"{len(lineas_woo_n)} productos cargados.")
                            else:
                                st.error(f"Error {r_woo_n.status_code}: {r_woo_n.text[:200]}")
                        except Exception as ex:
                            st.error(f"Error: {ex}")
                if st.session_state.get("cat_prods_temp"):
                    sel_woo_n = st.multiselect("Selecciona los que quieres guardar:", st.session_state["cat_prods_temp"],
                                                default=st.session_state["cat_prods_temp"][:20], key="cat_woo_sel_n")
                    if sel_woo_n and st.button("💾 Guardar seleccionados en catálogo", key="cat_woo_save_n"):
                        n = _guardar_lista(sel_woo_n, "woocommerce")
                        st.success(f"✅ {n} producto(s) guardados.")
                        st.session_state.pop("cat_prods_temp", None)
                        st.rerun()

            elif fuente_new == "API de TiendaNube":
                tn_id_n = st.text_input("ID de tu tienda:", placeholder="123456", key="cat_tn_id_n")
                tn_tok_n = st.text_input("Token:", type="password", key="cat_tn_tok_n")
                if tn_id_n and tn_tok_n and st.button("Cargar desde TiendaNube", key="cat_tn_btn_n"):
                    with st.spinner("Conectando con TiendaNube..."):
                        try:
                            r_tn_n = requests.get(
                                f"https://api.tiendanube.com/v1/{tn_id_n}/products",
                                headers={"Authentication": f"bearer {tn_tok_n}", "User-Agent": "TENTAKL-AI/1.0"},
                                params={"per_page": 100}, timeout=15
                            )
                            if r_tn_n.status_code == 200:
                                lineas_tn_n = []
                                for p in r_tn_n.json():
                                    nombre_tn = (p.get("name") or {}).get("es", "") or str(p.get("name", ""))
                                    precio_tn = (p.get("variants") or [{}])[0].get("price", "")
                                    lineas_tn_n.append(f"{nombre_tn} - {moneda_cat}{precio_tn}" if precio_tn else nombre_tn)
                                st.session_state["cat_prods_temp"] = lineas_tn_n
                                st.success(f"{len(lineas_tn_n)} productos cargados.")
                            else:
                                st.error(f"Error {r_tn_n.status_code}: {r_tn_n.text[:200]}")
                        except Exception as ex:
                            st.error(f"Error: {ex}")
                if st.session_state.get("cat_prods_temp"):
                    sel_tn_n = st.multiselect("Selecciona los que quieres guardar:", st.session_state["cat_prods_temp"],
                                               default=st.session_state["cat_prods_temp"][:20], key="cat_tn_sel_n")
                    if sel_tn_n and st.button("💾 Guardar seleccionados en catálogo", key="cat_tn_save_n"):
                        n = _guardar_lista(sel_tn_n, "tiendanube")
                        st.success(f"✅ {n} producto(s) guardados.")
                        st.session_state.pop("cat_prods_temp", None)
                        st.rerun()

    elif opcion_mkt == "Generador de Imagenes":
        st.subheader("🎨 Generador de Imágenes Profesional")
        st.caption("Crea 3 variaciones fotográficas de alta calidad — texto incluido en la imagen")

        _ig2_email = (st.session_state.get("user_email") or "").strip().lower()
        _ig2_plan  = st.session_state.get("plan", "Free")
        _ig2_marca = st.session_state.get("marca_guardada", nombre_marca)
        _ig2_nicho = st.session_state.get("nicho_guardado", nicho)
        _ig2_pais  = st.session_state.get("pais_guardado", pais)
        _ig2_prod  = st.session_state.get("producto_servicio", "")
        _ig2_cli   = st.session_state.get("cliente_ideal_guardado", "")

        _ig2_cfg = get_plan_config(_ig2_plan)
        _ig2_limite = int(_ig2_cfg["imagenes_limite"])
        _ig2_usadas = st.session_state.get("imagenes_usadas", 0)
        _ig2_ok_limite, _ig2_msg_limite = verificar_limite_imagenes()

        if not _ig2_ok_limite:
            _mostrar_upgrade(f"🐙 {_ig2_msg_limite}")
        else:
            st.caption(f"Imágenes disponibles: {_ig2_limite - _ig2_usadas}/{_ig2_limite} este mes")

            # PASO 1 — Fuente de la imagen: subir foto / catálogo / desde cero
            _ig2_foto_url = None
            _ig2_foto_bytes = None
            _ig2_nombre_prod = ""
            _ig2_precio_prod = ""
            _ig2_usar_producto = False
            _is_en_ig = st.session_state.get("lang") == "en"

            _FUENTES_IMG = (["✨ Generar desde cero", "📷 Subir foto", "🛍 De mi catálogo"]
                            if not _is_en_ig else
                            ["✨ Generate from scratch", "📷 Upload photo", "🛍 From my catalog"])
            _ig2_fuente = st.radio(
                "Fuente de la imagen:" if not _is_en_ig else "Image source:",
                _FUENTES_IMG, horizontal=True, key="ig2_fuente",
            )

            if _ig2_fuente == _FUENTES_IMG[1]:  # 📷 Subir foto
                _ig2_up = st.file_uploader(
                    "Sube tu foto (PNG/JPG/WebP, máx 10MB):" if not _is_en_ig
                    else "Upload your photo (PNG/JPG/WebP, max 10MB):",
                    type=["png", "jpg", "jpeg", "webp"], key="ig2_upload",
                )
                if _ig2_up is not None:
                    if _ig2_up.size > 10 * 1024 * 1024:
                        st.error("La imagen supera los 10MB. Comprímela e intenta de nuevo."
                                 if not _is_en_ig else "The image exceeds 10MB. Compress it and try again.")
                    else:
                        _ig2_foto_bytes = _ig2_up.getvalue()
                        _ig2_usar_producto = True
                        st.image(_ig2_foto_bytes, width=150,
                                 caption="Tu foto de referencia" if not _is_en_ig else "Your reference photo")

            elif _ig2_fuente == _FUENTES_IMG[2]:  # 🛍 De mi catálogo
                _ig2_opciones_cat = []
                for _p_cat in db_get_catalogo(_ig2_email):
                    if (_p_cat.get("imagen_url") or "").strip():
                        _ig2_opciones_cat.append((
                            f"📦 {_p_cat['nombre']}" + (f" - {_p_cat.get('precio')}" if _p_cat.get("precio") else ""),
                            _p_cat["imagen_url"], _p_cat["nombre"], str(_p_cat.get("precio", "")),
                        ))
                if obtener_config_tienda(_ig2_email):
                    with st.spinner("Cargando productos de tu tienda..." if not _is_en_ig
                                    else "Loading products from your store..."):
                        _ig2_prods_t = obtener_productos_tienda(_ig2_email) or []
                    for _p_t in _ig2_prods_t:
                        if _p_t.get("foto_url"):
                            _ig2_opciones_cat.append((
                                f"🏪 {_p_t['nombre']} - {_p_t.get('precio', '')}",
                                _p_t["foto_url"], _p_t["nombre"], str(_p_t.get("precio", "")),
                            ))
                if not _ig2_opciones_cat:
                    st.warning("No encontré productos con imagen en tu catálogo ni en tu tienda. "
                               "Sube una foto manualmente (opción 📷) o sincroniza tu tienda desde Gestión → Integraciones."
                               if not _is_en_ig else
                               "No products with images found in your catalog or store. "
                               "Upload a photo manually (📷 option) or sync your store from Management → Integrations.")
                else:
                    _ig2_sel_cat = st.selectbox(
                        "Elige el producto:" if not _is_en_ig else "Choose the product:",
                        [_o[0] for _o in _ig2_opciones_cat], key="ig2_cat_sel",
                    )
                    _ig2_obj_cat = next(_o for _o in _ig2_opciones_cat if _o[0] == _ig2_sel_cat)
                    _ig2_foto_url = _ig2_obj_cat[1]
                    _ig2_nombre_prod = _ig2_obj_cat[2]
                    _ig2_precio_prod = _ig2_obj_cat[3]
                    _ig2_usar_producto = True
                    st.image(_ig2_foto_url, width=150,
                             caption="Imagen del producto" if not _is_en_ig else "Product image")
                    st.info(("Generando campaña para: " if not _is_en_ig else "Creating campaign for: ") + _ig2_nombre_prod)

            else:  # ✨ Generar desde cero — logo de marca opcional
                if (st.session_state.get("logo_url") or "").strip():
                    if st.checkbox("🎨 " + ("Incluir mi logo real en la imagen (composición = edición)"
                                            if not _is_en_ig else "Include my real logo in the image (composition = edit)"),
                                   value=True, key="ig2_usar_logo"):
                        _ig2_foto_url = st.session_state["logo_url"]
                        _ig2_usar_producto = True

            # PASO 2 — Campos de la UI
            _ig2_desc = st.text_area(
                "¿Qué imagen quieres?" if not _ig2_usar_producto else "Descripción adicional (opcional):",
                placeholder="Ej: Campaña de polos para fiestas patrias con descuento",
                height=100,
                key="ig2_desc"
            )

            _ig2_texto_img = st.text_input(
                "Texto para incluir en la imagen (opcional)",
                placeholder="Ej: 20% OFF | Fiestas Patrias",
                key="ig2_texto_img"
            )

            _ig2_red = st.selectbox(
                "Formato / Red social" if not _is_en_ig else "Format / Social network",
                ["Instagram Post (1:1)",
                 "Instagram Story / TikTok (9:16)",
                 "Facebook Post (16:9)",
                 "YouTube Thumbnail (16:9)",
                 "Pinterest (2:3)",
                 "LinkedIn (1.91:1)",
                 "Twitter / X (16:9)",
                 "WhatsApp Estado (9:16)",
                 "Banner web horizontal (16:9) — 1920x1080",
                 "Banner cabecera web (3:1) — 1500x500",
                 "Leaderboard display (728x90)",
                 "Banner rectángulo (300x250)",
                 "Portada / hero de tienda (2:1) — 1200x600"],
                key="ig2_red"
            )

            _ig2_formatos_map = {
                "Instagram Post (1:1)":            "1024x1024",
                "Instagram Story / TikTok (9:16)": "1024x1792",
                "Facebook Post (16:9)":            "1792x1024",
                "YouTube Thumbnail (16:9)":        "1792x1024",
                "Pinterest (2:3)":                 "1024x1536",
                "LinkedIn (1.91:1)":               "1792x1024",
                "Twitter / X (16:9)":              "1792x1024",
                "WhatsApp Estado (9:16)":          "1024x1792",
                # Formatos web / banner → size soportado más cercano (proporción reforzada en el prompt)
                "Banner web horizontal (16:9) — 1920x1080": "1792x1024",
                "Banner cabecera web (3:1) — 1500x500":     "1792x1024",
                "Leaderboard display (728x90)":             "1792x1024",
                "Banner rectángulo (300x250)":              "1024x1024",
                "Portada / hero de tienda (2:1) — 1200x600":"1792x1024",
            }

            # Proporción real a forzar en el prompt para los formatos no cuadrados/no estándar
            _ig2_ratio_map = {
                "Banner web horizontal (16:9) — 1920x1080": "a 16:9 wide horizontal web banner (1920x1080)",
                "Banner cabecera web (3:1) — 1500x500":     "an ultra-wide 3:1 website header banner (1500x500), key elements arranged horizontally with generous side margins",
                "Leaderboard display (728x90)":             "a very wide ~8:1 leaderboard display banner (728x90), all elements laid out horizontally in a single strip",
                "Banner rectángulo (300x250)":              "a compact 6:5 medium-rectangle display banner (300x250), tight centered composition",
                "Portada / hero de tienda (2:1) — 1200x600":"a wide 2:1 store hero cover banner (1200x600)",
            }

            # Calidad de imagen según plan (planes_config): Free low, Starter medium, Pro/Agency high
            _ig2_calidad  = _ig2_cfg["calidad_imagen"]
            _ig2_creditos = COSTO_CREDITOS["imagen"]
            st.caption(f"Imágenes disponibles: {max(_ig2_limite - int(_ig2_usadas), 0)}/{_ig2_limite} este mes · calidad {_ig2_calidad}")

            if st.button(f"🎨 Generar imagen premium ({_ig2_creditos} créditos)", key="btn_ig2_gen"):
                if not _ig2_desc:
                    st.warning("Describe qué imagen quieres")
                elif verificar_creditos(_ig2_creditos):
                    # Auto-detectar dirección creativa
                    _texto_all   = (_ig2_desc + " " + _ig2_nicho + " " + _ig2_prod).lower()
                    _obj_det     = next((v for k, v in _CD_OBJETIVOS.items() if k in _texto_all),
                                        "high-conversion premium brand campaign")
                    _estilo_det  = next((v for k, v in _CD_ESTILOS.items() if k in _texto_all),
                                        "premium commercial advertising aesthetic, modern brand photography")
                    _emocion_det = next((v for k, v in _CD_EMOCIONES.items() if k in _texto_all),
                                        "aspirational confident premium brand energy")
                    _pais_det    = _CD_PAISES.get(_ig2_pais, _CD_PAISES["default"])

                    # Reglas de tipografía (con o sin texto pedido por el usuario)
                    if _ig2_texto_img:
                        _typo_rules = (
                            f'CRITICAL: Render this exact text in the image with bold premium '
                            f'sans-serif typography, perfectly integrated: "{_ig2_texto_img}". '
                            f'Clean hierarchy, premium spacing, luxury branding alignment, '
                            f'strong headline placement, minimal but powerful CTA.'
                        )
                    else:
                        _typo_rules = (
                            "Include elegant integrated typography if contextually appropriate. "
                            "Use clean hierarchy, premium spacing, luxury branding alignment. "
                            "If no text fits naturally, use pure visual storytelling power."
                        )

                    # Construir el prompt final
                    if _ig2_usar_producto and _ig2_nombre_prod:
                        _prompt_final = f"""You are an elite creative director.
Take this exact product and create a premium marketing campaign image.
The product MUST be the hero and clearly visible in the final image.

Brand: {_ig2_marca}
Product: {_ig2_nombre_prod}
Price: S/{_ig2_precio_prod}
Country: {_ig2_pais}
Platform: {_ig2_red}

Style: Premium commercial photography, cinematic lighting, professional marketing campaign.
The product is real — maintain its exact appearance but place it in a premium marketing context.

{_ig2_desc if _ig2_desc else ""}

{_typo_rules}

Quality: Award-winning commercial photography, Sony A7R IV quality, high conversion ad."""
                    else:
                        _pedido_enriquecido = (
                            f"{_ig2_desc}. "
                            f"Visual style: {_estilo_det}. "
                            f"Emotional direction: {_emocion_det}. "
                            f"Cultural context: {_pais_det}."
                        )
                        _prompt_final = CREATIVE_DIRECTOR_PROMPT.format(
                            marca=_ig2_marca,
                            nicho=_ig2_nicho,
                            pais=_ig2_pais,
                            plataforma=_ig2_red,
                            objetivo=_obj_det,
                            cliente_ideal=_ig2_cli or "premium adults 25-45",
                            pedido_usuario=_pedido_enriquecido,
                            typography_rules=_typo_rules,
                        )

                    # Reforzar la proporción exacta para banners web (size API es aproximado)
                    _ig2_ratio_hint = _ig2_ratio_map.get(_ig2_red)
                    if _ig2_ratio_hint:
                        _prompt_final += (
                            f"\n\nIMPORTANT COMPOSITION: Design this specifically as {_ig2_ratio_hint}. "
                            f"Arrange every element to fit this aspect ratio with safe margins, no cropping of text or product."
                        )

                    with st.spinner("Generando imagen premium de alta calidad..."):
                        try:
                            _img_b64, _err = generar_imagen_openai(
                                _prompt_final, _ig2_marca, _ig2_nicho, _ig2_pais,
                                formato=_ig2_formatos_map[_ig2_red],
                                calidad=_ig2_calidad,
                                imagen_referencia_url=_ig2_foto_url if _ig2_usar_producto else None,
                                imagen_referencia_bytes=_ig2_foto_bytes if _ig2_usar_producto else None,
                            )
                        except Exception as _ex_gen:
                            _img_b64, _err = None, str(_ex_gen)

                    if _err == "sin_api_key":
                        st.error("Configura OPENAI_API_KEY en Streamlit Secrets")
                    elif _err:
                        st.error(f"Error al generar imagen: {_err}")
                    elif _img_b64:
                        import base64 as _b64mod
                        try:
                            _cap_img = f"Campaña premium: {_ig2_desc[:50]}"
                            if not _img_b64.startswith("http"):
                                _img_bytes = _b64mod.b64decode(_img_b64)
                                _img_src = "data:image/png;base64," + _b64mod.b64encode(_img_bytes).decode()
                            else:
                                _img_bytes = None
                                _img_src = _img_b64
                            # Contenedor centrado, máx ~500px, esquinas redondeadas
                            st.markdown(
                                f'<div style="display:flex;flex-direction:column;align-items:center;margin:14px 0;">'
                                f'<img src="{_img_src}" style="max-width:500px;width:100%;height:auto;'
                                f'border-radius:14px;box-shadow:0 4px 18px rgba(0,0,0,.14);" />'
                                f'<div style="color:#6B6580;font-size:13px;margin-top:6px;">{_cap_img}</div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                            if _img_bytes is not None:
                                _cdl, _cdc, _cdr = st.columns([1, 2, 1])
                                with _cdc:
                                    st.download_button(
                                        "⬇️ Descargar imagen" if not _is_en_ig else "⬇️ Download image",
                                        data=_img_bytes,
                                        file_name=f"tentakl_img_{_ig2_marca}.png",
                                        mime="image/png",
                                        key="ig2_dl_0",
                                        use_container_width=True,
                                    )
                        except Exception as _show_err:
                            st.error(f"Error al mostrar imagen: {_show_err}")

                        with st.expander("📋 Copiar prompt para Midjourney / DALL-E"):
                            st.caption("Haz click en el ícono de copiar (esquina superior derecha del bloque):")
                            st.code(_prompt_final, language=None)

                        consumir(_ig2_creditos,
                                 tipo_accion="edicion_imagen" if _ig2_usar_producto else "imagen")
                        registrar_uso_imagen()

                        if _ig2_email:
                            guardar_reporte(
                                _ig2_email,
                                "imagen_banner",
                                f"Imagen premium: {_ig2_desc[:60]} | {_ig2_red}",
                                _prompt_final
                            )
                    else:
                        st.error("La API no retornó imagen. Intenta con otra descripción.")


    # ── SIMULADOR DE CAMPAÑA ──────────────────────────────────────────────────
    elif opcion_mkt == "Simulador de Campaña":
        _is_en_sim = st.session_state.get("lang") == "en"

        if _is_en_sim:
            st.subheader("🧪 Campaign Simulator")
            _sim_camp_lbl  = "Your complete campaign:"
            _sim_camp_ph   = "Paste your campaign copy, price, offer and value proposition"
            _sim_obj_lbl   = "Campaign objective:"
            _sim_obj_opts  = ["Sales", "Leads", "Brand Awareness", "Engagement", "App Downloads"]
            _sim_btn       = "🧪 Simulate and improve campaign (5 credits)"
            _sim_warn_camp = "Paste your campaign text first."
            _sim_spin      = "Simulating campaign..."
        else:
            st.subheader("🧪 Simulador de Campaña")
            _sim_camp_lbl  = "Tu campaña completa:"
            _sim_camp_ph   = "Pega el copy de tu campaña, precio, oferta y propuesta de valor"
            _sim_obj_lbl   = "Objetivo de la campaña:"
            _sim_obj_opts  = ["Ventas", "Leads", "Reconocimiento de marca", "Engagement", "Descargas de app"]
            _sim_btn       = "🧪 Simular y mejorar campaña (5 créditos)"
            _sim_warn_camp = "Pega el texto de tu campaña primero."
            _sim_spin      = "Simulando campaña..."

        # ── Memoria: compliance anterior ───────────────────────────────────
        _sim_email_mem = (st.session_state.get("user_email") or "").strip().lower()
        if _sim_email_mem:
            _sim_mem = obtener_ultimo_reporte_tipo(_sim_email_mem, ["compliance"], dias=30)
            if _sim_mem:
                _sim_mem_fecha = str(_sim_mem.get("created_at", ""))[:10]
                _sim_mem_resumen = _sim_mem.get("contenido", "")[:300]
                st.warning(f"Compliance anterior ({_sim_mem_fecha}): {_sim_mem_resumen[:200]}... Asegurate de no repetir frases rechazadas.")
        # ─────────────────────────────────────────────────────────────────────
        _sim_camp_txt = st.text_area(
            _sim_camp_lbl,
            placeholder=_sim_camp_ph,
            height=180,
            key="sim_camp_txt",
        )
        _sim_obj_sel = st.selectbox(_sim_obj_lbl, _sim_obj_opts, key="sim_obj_sel")

        if st.button(_sim_btn, key="btn_sim_camp"):
            if not _sim_camp_txt.strip():
                st.warning(_sim_warn_camp)
            elif len(_sim_camp_txt) > 4000:
                st.warning("⚠ Texto demasiado largo, máximo 4000 caracteres.")
            elif verificar_creditos(5):
                _sim_marca  = st.session_state.get("marca_guardada", nombre_marca)
                _sim_nicho  = st.session_state.get("nicho_guardado", nicho)
                _sim_pais   = st.session_state.get("pais_guardado", pais)
                _sim_moneda = PAISES_MONEDA.get(_sim_pais, "$")
                _sim_cliente = st.session_state.get("cliente_ideal_guardado", cliente_ideal)
                _sim_txt_clean = _sanitizar(_sim_camp_txt)
                _sim_prefix = "Respond ONLY in English. Adapt all monetary examples to USD.\n\n" if _is_en_sim else ""

                _sim_prompt = (
                    _sim_prefix +
                    f"Eres un experto en marketing de respuesta directa y optimización de campañas.\n"
                    f"Marca: {_sim_marca} | Nicho: {_sim_nicho} | País: {_sim_pais} | Moneda: {_sim_moneda}\n"
                    f"Cliente ideal: {_sim_cliente[:300]}\n"
                    f"Objetivo de la campaña: {_sim_obj_sel}\n\n"
                    f"CAMPAÑA A ANALIZAR:\n{_sim_txt_clean}\n\n"
                    f"Genera el análisis en este formato EXACTO:\n\n"
                    f"## 📊 DIAGNÓSTICO\n"
                    f"- **Claridad del mensaje (1-10):** [puntuación y razón]\n"
                    f"- **Fuerza del CTA (1-10):** [puntuación y razón]\n"
                    f"- **Relevancia para el público (1-10):** [puntuación y razón]\n"
                    f"- **Propuesta de valor (1-10):** [puntuación y razón]\n"
                    f"- **Score total estimado:** [X/40 — nivel: Débil/Regular/Buena/Excelente]\n\n"
                    f"## 🔧 MEJORAS RECOMENDADAS\n"
                    f"1. [cambio específico al copy]\n"
                    f"2. [cambio específico al precio/oferta]\n"
                    f"3. [cambio específico al CTA]\n\n"
                    f"## ✅ VERSIÓN MEJORADA DE LA CAMPAÑA\n"
                    f"[Reescribe la campaña completa aplicando todas las mejoras]"
                )

                with st.spinner(_sim_spin):
                    _sim_res = generar_texto(_sim_prompt, max_out=5000, modelo=MODELO_FUERTE)

                st.markdown(_sim_res)

                _sim_email = (st.session_state.get("user_email") or "").strip().lower()
                if _sim_email:
                    guardar_reporte(
                        _sim_email,
                        "simulador_campana",
                        f"Simulador {_sim_obj_sel} — {_sim_marca}",
                        _sim_res,
                    )

                consumir(5)


# --- SECCIÓN: VENTAS (agente Comercial) ---
if _sec_activa == "ventas":
    if not st.session_state.get("user_email", "").strip():
        st.warning("⚠ Ingresa tu email en el sidebar para acceder a esta sección." if st.session_state.get("lang") != "en" else "⚠ Enter your email in the sidebar to access this section.")
        st.info("👈 Panel izquierdo → Tu Cuenta → Email" if st.session_state.get("lang") != "en" else "👈 Left panel → Your Account → Email")
    st.subheader(t("cerrador"))
    opcion_vta = _opcion_activa

    if opcion_vta == "Psicólogo de Precios":
        p = st.number_input("Precio a optimizar:", min_value=0.0, value=0.0)
        if p > 0 and st.button("Optimizar (1 Crédito)"):
            if verificar_creditos(1):
                prompt = (
                    f"Neuromarketing y psicología de precios.\nNicho: {nicho}. Producto: {producto_servicio}. País: {pais}.\nPrecio a optimizar: {p}\n\n"
                    f"Dame:\n"
                    f"## 💰 PRECIO PSICOLÓGICO RECOMENDADO\n[Precio exacto + por qué]\n\n"
                    f"## 🧠 GATILLOS MENTALES A USAR\n[Lista con ejemplos concretos]\n\n"
                    f"## 📝 CÓMO PRESENTARLO EN TU WEB/POST\n[Texto listo para copiar]\n\n"
                    f"## ⚖ COMPARACIÓN DE VALOR\n[Cómo anclar el precio frente a alternativas]\n\n"
                    f"## 🎯 COPY DEL PRECIO (listo para usar)\n[Frase para Instagram/WhatsApp]"
                )
                st.markdown(generar_texto(prompt, max_out=6000))
                consumir(1)

    elif opcion_vta == "Mata-Objeciones":
        obj = st.text_input("¿Qué excusa puso el cliente?")
        if obj and st.button("Generar Respuesta (1 Crédito)"):
            if verificar_creditos(1):
                prompt = (
                    f"Eres experto en ventas y cierre de objeciones.\nNicho: {nicho}. Producto: {producto_servicio}. País: {pais}.\n"
                    f"El cliente dice: '{obj}'\n\n"
                    f"Dame:\n"
                    f"## 💬 RESPUESTA GANADORA\n[Texto completo listo para enviar/decir]\n\n"
                    f"## 🔄 VARIANTE B (tono diferente)\n[Segunda opción]\n\n"
                    f"## 🧠 POR QUÉ FUNCIONA\n[Técnica de venta usada]\n\n"
                    f"## ⚡ CTA DE CIERRE\n[Frase final para cerrar la venta]"
                )
                st.markdown(generar_texto(prompt, max_out=6000))
                consumir(1)

    elif opcion_vta == "Calculadora Descuentos":
        orig = st.number_input("Precio Original:", value=100.0)
        desc = st.number_input("% de Descuento:", value=20.0)
        if st.button("Analizar Impacto"):
            _precio_final = orig * (1 - desc/100)
            _col_d1, _col_d2, _col_d3 = st.columns(3)
            _col_d1.metric("Precio Final", f"{_precio_final:.2f}")
            _col_d2.metric("Ahorro", f"{orig - _precio_final:.2f}")
            _col_d3.metric("Descuento", f"{desc:.0f}%")
            if verificar_creditos(1):
                prompt = (
                    f"Finanzas y psicología de descuentos.\nNicho: {nicho}. Producto: {producto_servicio}. País: {pais}.\n"
                    f"Precio original: {orig} → con {desc}% descuento → precio final: {_precio_final:.2f}\n\n"
                    f"Dame:\n"
                    f"## ✅ ANÁLISIS DEL DESCUENTO\n[¿Es viable? ¿Cuándo usarlo?]\n\n"
                    f"## 🛡 3 TIPS PARA NO PERDER PERCEPCIÓN DE VALOR\n\n"
                    f"## 📢 COPY PARA PUBLICAR EL DESCUENTO\n[Texto listo para redes]"
                )
                st.markdown(generar_texto(prompt, max_out=6000))
                consumir(1)

# --- SECCIÓN: OFICINA VIRTUAL (varios agentes) ---
if _sec_activa == "admin":
    if not st.session_state.get("user_email", "").strip():
        st.warning("⚠ Ingresa tu email en el sidebar para acceder a esta sección." if st.session_state.get("lang") != "en" else "⚠ Enter your email in the sidebar to access this section.")
        st.info("👈 Panel izquierdo → Tu Cuenta → Email" if st.session_state.get("lang") != "en" else "👈 Left panel → Your Account → Email")
    st.subheader(t("oficina"))
    opcion_adm = _opcion_activa

    if opcion_adm == "Analista ROI (CSV)":
        csv = st.file_uploader("Sube tu archivo (Excel o CSV):", type=["csv", "xlsx"])
        if csv and st.button("Analizar Reporte (2 Créditos)"):
            if verificar_creditos(2):
                try:
                    df = pd.read_csv(csv, encoding="utf-8-sig") if csv.name.endswith(".csv") else pd.read_excel(csv)
                    _roi_tabla = df.head(15).to_string()
                    _roi_cols = list(df.columns)
                    prompt = (
                        f"Eres analista de marketing digital experto.\n"
                        f"Nicho: {nicho} | País: {pais} | Producto: {producto_servicio}\n\n"
                        f"DATOS DEL REPORTE:\n{_roi_tabla}\n\n"
                        f"Columnas detectadas: {_roi_cols}\n\n"
                        f"Dame:\n"
                        f"## 📊 RESUMEN DE MÉTRICAS\n"
                        f"(si hay columnas de gasto e ingresos, calcula ROI, ROAS y CPA por campaña)\n\n"
                        f"## 🏆 CAMPAÑA GANADORA\n[Cuál tiene mejor rendimiento y por qué]\n\n"
                        f"## ⚠ CAMPAÑA A OPTIMIZAR O PAUSAR\n[Cuál rinde menos y qué hacer]\n\n"
                        f"## 💡 3 ACCIONES CONCRETAS\n1.\n2.\n3.\n\n"
                        f"## 📈 PROYECCIÓN\n[Si duplicas el presupuesto de la mejor campaña, qué esperar]"
                    )
                    _roi_res = generar_analitico(prompt, max_tokens=8000)
                    st.markdown(_roi_res)
                    consumir(2)
                except Exception as _roi_err:
                    st.error(f"No se pudo leer el archivo: {_roi_err}")

    elif opcion_adm == "Cotizaciones":
        _cot_marca  = st.session_state.get("marca_guardada", nombre_marca)
        _cot_pais   = st.session_state.get("pais_guardado", pais)
        _cot_moneda = PAISES_MONEDA.get(_cot_pais, "$")
        c = st.text_input("Nombre del Cliente:", placeholder="Ej: María García / Empresa XYZ")
        d = st.text_area("Detalles / Ítems del servicio:", height=120,
                         placeholder="Ej:\n- Diseño de logo: $300\n- Manual de marca: $200\n- 10 posts para redes: $150")
        _cot_valid = st.date_input("Válida hasta:", key="cot_validez")
        if c and d and st.button("📄 Generar Cotización (1 Crédito)", key="btn_cotizacion"):
            if verificar_creditos(1):
                prompt = (
                    f"Genera una cotización profesional completa.\n"
                    f"Empresa que cotiza: {_cot_marca} | País: {_cot_pais} | Moneda: {_cot_moneda}\n"
                    f"Cliente: {c}\n"
                    f"Válida hasta: {_cot_valid}\n\n"
                    f"ÍTEMS/SERVICIOS:\n{d}\n\n"
                    f"Genera el documento con este formato:\n"
                    f"# COTIZACIÓN — {_cot_marca}\n\n"
                    f"**Fecha:** [fecha actual] | **Válida hasta:** {_cot_valid}\n"
                    f"**Para:** {c}\n\n"
                    f"## DETALLE DE SERVICIOS\n"
                    f"| Ítem | Descripción | Precio |\n|---|---|---|\n"
                    f"[llena la tabla con los ítems]\n\n"
                    f"**SUBTOTAL:**\n**IVA/IGV (si aplica):**\n**TOTAL:**\n\n"
                    f"## CONDICIONES\n"
                    f"- Forma de pago: [50% adelanto / 50% entrega]\n"
                    f"- Tiempo de entrega: [días hábiles]\n"
                    f"- Revisiones incluidas: [número]\n\n"
                    f"## TÉRMINOS\n[2-3 cláusulas cortas y profesionales para {_cot_pais}]\n\n"
                    f"---\n*{_cot_marca} | {_cot_pais}*"
                )
                with st.spinner("Generando cotización..."):
                    texto = generar_texto(prompt, max_out=5000)
                st.markdown(texto)
                _cot_email = (st.session_state.get("user_email") or "").strip().lower()
                if _cot_email:
                    guardar_reporte(_cot_email, "cotizacion", f"Cotización {c} — {_cot_marca}", texto)
                consumir(1)

    elif opcion_adm == "Contratos":
        _cont_marca  = st.session_state.get("marca_guardada", nombre_marca)
        _cont_pais   = st.session_state.get("pais_guardado", pais)
        _cont_moneda = PAISES_MONEDA.get(_cont_pais, "$")
        tipo = st.text_input("Tipo de Contrato:", placeholder="Ej: Servicio de Marketing, Colaboración con Influencer, Prestación de Servicios")
        _cont_parte_b = st.text_input("Nombre de la otra parte (cliente/proveedor):", placeholder="Ej: María García / Empresa XYZ")
        _cont_monto   = st.text_input(f"Monto del contrato ({_cont_moneda}):", placeholder=f"Ej: {_cont_moneda}1500")
        if tipo and st.button("📝 Redactar Contrato (2 Créditos)", key="btn_contrato"):
            if verificar_creditos(2):
                prompt = (
                    f"Eres abogado especialista en derecho comercial de {_cont_pais}.\n"
                    f"Redacta un borrador completo de contrato de '{tipo}'.\n\n"
                    f"PARTES:\n"
                    f"- Parte A (prestador): {_cont_marca} — {nicho} | {_cont_pais}\n"
                    f"- Parte B (cliente/proveedor): {_cont_parte_b}\n"
                    f"- Monto: {_cont_monto}\n\n"
                    f"ESTRUCTURA DEL CONTRATO:\n"
                    f"# CONTRATO DE {tipo.upper()}\n\n"
                    f"## 1. PARTES\n## 2. OBJETO\n## 3. OBLIGACIONES DE CADA PARTE\n"
                    f"## 4. PRECIO Y FORMA DE PAGO\n## 5. PLAZO Y ENTREGABLES\n"
                    f"## 6. PROPIEDAD INTELECTUAL\n## 7. CONFIDENCIALIDAD\n"
                    f"## 8. RESCISIÓN\n## 9. RESOLUCIÓN DE CONFLICTOS\n"
                    f"## 10. FIRMAS\n\n"
                    f"Adapta el lenguaje legal a {_cont_pais}. Hazlo profesional pero claro."
                )
                with st.spinner("Redactando contrato..."):
                    texto = generar_texto(prompt, max_out=6000)
                st.markdown(texto)
                _cont_email = (st.session_state.get("user_email") or "").strip().lower()
                if _cont_email:
                    guardar_reporte(_cont_email, "contrato", f"Contrato {tipo} — {_cont_parte_b}", texto)
                consumir(2)

    elif opcion_adm == "Reglas de Marca":
        st.write("Define las reglas de comunicación de tu marca. Se usarán en todos los prompts de la app.")
        tono_voz = st.text_input("Tono de voz:", placeholder="Ej: cercano, profesional, divertido, motivador...")
        palabras_si = st.text_area("Palabras que SÍ usa tu marca:", placeholder="Ej: tú, lograr, transformar, resultados, comunidad...", height=80)
        palabras_no = st.text_area("Palabras que NO usa tu marca:", placeholder="Ej: barato, problema, difícil, imposible, garantizado...", height=80)
        valores_marca = st.text_area("Valores de marca:", placeholder="Ej: autenticidad, innovación, cercanía con el cliente...", height=80)
        reglas_actuales = st.session_state.get("reglas_marca", "")
        if reglas_actuales:
            st.success("✅ Reglas de marca activas — se aplican a todos los prompts")
            st.caption(reglas_actuales)
        if st.button("Guardar Reglas de Marca (1 Crédito)"):
            if verificar_creditos(1):
                reglas_texto = ""
                if tono_voz:
                    reglas_texto += f"Tono de voz: {tono_voz}\n"
                if palabras_si:
                    reglas_texto += f"Palabras que SÍ usa: {palabras_si}\n"
                if palabras_no:
                    reglas_texto += f"Palabras que NO usa: {palabras_no}\n"
                if valores_marca:
                    reglas_texto += f"Valores de marca: {valores_marca}\n"
                if reglas_texto.strip():
                    st.session_state.reglas_marca = reglas_texto.strip()
                    prompt_reglas = f"""Eres experto en branding y manual de marca.
Basándote en estos datos, genera un resumen ejecutivo de las reglas de comunicación de la marca:
Marca: {nombre_marca}
Nicho: {nicho}
{reglas_texto}
Escribe las reglas de forma clara y aplicable para redactar contenido."""
                    with st.spinner("Generando manual de marca..."):
                        texto = generar_texto(prompt_reglas, max_out=6000)
                    st.markdown(texto)
                    email_tab = (st.session_state.get("user_email") or "").strip().lower()
                    if email_tab:
                        guardar_reporte(email_tab, "reglas_marca", f"Reglas de marca - {nombre_marca}", texto)
                        db_guardar_reglas_marca(email_tab, reglas_texto.strip())
                    st.success("✅ Reglas de marca guardadas en tu perfil")
                    consumir(1)
                else:
                    st.warning("Completa al menos un campo antes de guardar.")

    elif opcion_adm == "Analizador de Métricas":
        st.write("Sube una captura de pantalla de tus métricas y recibe un análisis completo con recomendaciones.")

        tipo_metrica = st.selectbox(
            "¿Qué métricas quieres analizar?",
            ["📱 Instagram / TikTok", "📢 Facebook Ads / Meta Ads",
             "🔍 Google Ads", "🛒 Ventas de mi tienda", "📊 Cualquier reporte con números"],
            key="adm_tipo_metrica"
        )
        imagen_metricas = st.file_uploader(
            "Sube una captura de pantalla de tus métricas:",
            type=["jpg", "png", "jpeg"],
            key="adm_img_metricas"
        )

        if imagen_metricas and st.button("🔍 Analizar Métricas (2 Créditos)", key="adm_btn_metricas"):
            if verificar_creditos(2):
                prompt_metricas = f"""Eres un analista experto en marketing digital.
Analiza esta imagen de métricas y extrae todos los números que puedas ver.

Tipo de reporte: {tipo_metrica}
Negocio: {nicho} en {pais}
Objetivo del negocio: {producto_servicio}

Dame:
1. RESUMEN DE MÉTRICAS:
   Lista todos los números que encontraste
   (alcance, impresiones, clics, conversiones,
   gasto, ventas, ROI, etc.)

2. ANÁLISIS DE RENDIMIENTO:
   ¿Qué está funcionando bien?
   ¿Qué está fallando?
   Compara con benchmarks del sector {nicho}

3. ROI CALCULADO:
   Si hay datos de gasto y ventas calcula:
   - ROI = (Ganancia - Inversión) / Inversión x 100
   - ROAS = Ingresos / Gasto en ads
   - Costo por resultado

4. RECOMENDACIONES CONCRETAS:
   3 acciones específicas para mejorar
   estas métricas la próxima semana

5. SEMÁFORO DE RESULTADOS:
   🟢 Lo que va bien
   🟡 Lo que necesita atención
   🔴 Lo que hay que cambiar urgente

Sé muy específico con los números que ves en la imagen."""

                with st.spinner("Analizando métricas con IA..."):
                    file_bytes = imagen_metricas.read()
                    mime = "image/png" if imagen_metricas.name.endswith(".png") else "image/jpeg"
                    resultado_metricas = generar_multimodal(prompt_metricas, mime, file_bytes, temperatura=0.2, max_out=4000)

                st.markdown(resultado_metricas)
                st.session_state["ultimo_analisis_metricas"] = resultado_metricas
                consumir(2)

        if st.session_state.get("ultimo_analisis_metricas"):
            email_adm = (st.session_state.get("user_email") or "").strip().lower()
            if email_adm and st.button("💾 Guardar análisis en Mis Reportes", key="adm_save_metricas"):
                guardar_reporte(
                    email_adm,
                    "analisis_metricas",
                    f"Análisis de métricas {tipo_metrica} - {dt.now().strftime('%d/%m/%Y')}",
                    st.session_state["ultimo_analisis_metricas"]
                )
                st.success("✅ Análisis guardado en Mis Reportes.")


    elif opcion_adm == "Integraciones":
        _is_en_int = st.session_state.get("lang") == "en"
        _email_int = (st.session_state.get("user_email") or "").strip().lower()

        if not _email_int:
            st.warning("Ingresa tu email para usar integraciones." if not _is_en_int else "Enter your email to use integrations.")
        else:
            # ── SECCIÓN 1 — Estado Google Analytics ─────────────────────────────
            st.markdown("### 📊 Google Analytics")

            # Check connection status from Supabase
            _ga_conectado = False
            _ga_record = {}
            if supabase:
                try:
                    _r = supabase.table("integraciones").select("*") \
                        .eq("user_email", _email_int) \
                        .eq("tipo", "google_analytics") \
                        .eq("activo", True) \
                        .limit(1).execute()
                    if _r.data:
                        _ga_conectado = True
                        _ga_record = _r.data[0]
                except Exception:
                    pass

            if _ga_conectado:
                st.success("✅ Google Analytics conectado" if not _is_en_int else "✅ Google Analytics connected")
                _ga_pid = _ga_record.get("account_id", "")
                _ga_key = _ga_record.get("access_token", "")
                st.caption(f"Property ID: {_ga_pid}")

                _periodos = ["7daysAgo", "30daysAgo", "90daysAgo"]
                _periodos_lbl = ["Últimos 7 días", "Últimos 30 días", "Últimos 90 días"] if not _is_en_int else ["Last 7 days", "Last 30 days", "Last 90 days"]
                _sel_periodo = st.selectbox("Período:" if not _is_en_int else "Period:", _periodos_lbl, key="ga_periodo")
                _periodo_val = _periodos[_periodos_lbl.index(_sel_periodo)]

                _col_ga1, _col_ga2 = st.columns([3, 1])
                with _col_ga1:
                    _btn_analizar = st.button("📊 Analizar mis métricas (2 créditos)" if not _is_en_int else "📊 Analyze my metrics (2 credits)", key="ga_analizar")
                with _col_ga2:
                    _btn_desc = st.button("🔌 Desconectar" if not _is_en_int else "🔌 Disconnect", key="ga_desconectar")

                if _btn_desc:
                    if supabase:
                        try:
                            supabase.table("integraciones").update({"activo": False}) \
                                .eq("user_email", _email_int).eq("tipo", "google_analytics").execute()
                            st.success("Desconectado." if not _is_en_int else "Disconnected.")
                            st.rerun()
                        except Exception as _e:
                            st.error(str(_e))

                if _btn_analizar:
                    if verificar_creditos(2):
                        # ── Try real GA API ─────────────────────────────────────────
                        _ga_data = None
                        _usando_demo = False
                        try:
                            _url_ga = f"https://analyticsdata.googleapis.com/v1beta/properties/{_ga_pid}:runReport"
                            _headers_ga = {"X-goog-api-key": _ga_key, "Content-Type": "application/json"}
                            _body_ga = {
                                "dateRanges": [{"startDate": _periodo_val, "endDate": "today"}],
                                "metrics": [
                                    {"name": "sessions"}, {"name": "activeUsers"},
                                    {"name": "bounceRate"}, {"name": "averageSessionDuration"},
                                    {"name": "screenPageViewsPerSession"}, {"name": "newUsers"}
                                ],
                                "dimensions": [{"name": "sessionDefaultChannelGroup"}]
                            }
                            _resp_ga = requests.post(_url_ga, json=_body_ga, headers=_headers_ga, timeout=15)
                            if _resp_ga.status_code == 200:
                                _raw = _resp_ga.json()
                                _totals = {}
                                _channels = {}
                                for _row in _raw.get("rows", []):
                                    _ch = _row["dimensionValues"][0]["value"]
                                    _vals = [v["value"] for v in _row["metricValues"]]
                                    _channels[_ch] = int(float(_vals[0]))
                                    for _i, _mk in enumerate(["sessions","activeUsers","bounceRate","avgDuration","pagesPerSession","newUsers"]):
                                        _totals[_mk] = _totals.get(_mk, 0) + float(_vals[_i])
                                _ga_data = {
                                    "sessions": int(_totals.get("sessions", 0)),
                                    "activeUsers": int(_totals.get("activeUsers", 0)),
                                    "newUsers": int(_totals.get("newUsers", 0)),
                                    "bounceRate": round(_totals.get("bounceRate", 0) / max(len(_raw.get("rows", [])), 1), 1),
                                    "avgDuration": int(_totals.get("avgDuration", 0) / max(len(_raw.get("rows", [])), 1)),
                                    "pagesPerSession": round(_totals.get("pagesPerSession", 0) / max(len(_raw.get("rows", [])), 1), 1),
                                    "channels": _channels,
                                }
                            else:
                                _usando_demo = True
                        except Exception:
                            _usando_demo = True

                        if _usando_demo or _ga_data is None:
                            st.warning("⚠ Mostrando datos de ejemplo. Configura tu API key para ver datos reales." if not _is_en_int else "⚠ Showing sample data. Configure your API key to see real data.")
                            _ga_data = {
                                "sessions": 1250, "activeUsers": 890, "newUsers": 340,
                                "bounceRate": 68.5, "avgDuration": 125, "pagesPerSession": 2.3,
                                "channels": {"Organic Search": 35, "Direct": 28, "Social": 22, "Referral": 15}
                            }

                        st.session_state["ga_data"] = _ga_data
                        consumir(2)

                # Show metrics if available
                _gd = st.session_state.get("ga_data")
                if _gd:
                    st.markdown("---")
                    st.markdown("#### 📊 Métricas" if not _is_en_int else "#### 📊 Metrics")
                    _gc1, _gc2, _gc3 = st.columns(3)
                    _gc1.metric("Sesiones" if not _is_en_int else "Sessions", f"{_gd['sessions']:,}")
                    _gc2.metric("Usuarios activos" if not _is_en_int else "Active users", f"{_gd['activeUsers']:,}")
                    _gc3.metric("Usuarios nuevos" if not _is_en_int else "New users", f"{_gd['newUsers']:,}")
                    _gc4, _gc5, _gc6 = st.columns(3)
                    _gc4.metric("Tasa de rebote" if not _is_en_int else "Bounce rate",
                                f"{_gd['bounceRate']}%",
                                delta="-5%" if _gd['bounceRate'] < 70 else "+5%",
                                delta_color="normal" if _gd['bounceRate'] < 70 else "inverse")
                    _dur_m = _gd['avgDuration'] // 60
                    _dur_s = _gd['avgDuration'] % 60
                    _gc5.metric("Duración prom." if not _is_en_int else "Avg. duration", f"{_dur_m}m {_dur_s}s")
                    _gc6.metric("Páginas/sesión" if not _is_en_int else "Pages/session", f"{_gd['pagesPerSession']}")

                    # Pie chart de canales
                    if _gd.get("channels"):
                        try:
                            import plotly.express as px
                            _df_ch = {"Canal": list(_gd["channels"].keys()), "Sesiones": list(_gd["channels"].values())}
                            _fig = px.pie(
                                _df_ch, values="Sesiones", names="Canal",
                                title="Fuentes de tráfico" if not _is_en_int else "Traffic sources",
                                color_discrete_sequence=px.colors.qualitative.Set2
                            )
                            _fig.update_layout(height=320)
                            st.plotly_chart(_fig, use_container_width=True)
                        except ImportError:
                            st.write(_gd["channels"])

                    # Gemini analysis
                    if st.button("🧠 Analizar con IA" if not _is_en_int else "🧠 AI Analysis", key="ga_ia_btn"):
                        _nicho_ga  = st.session_state.get("nicho_guardado", "")
                        _pais_ga   = st.session_state.get("pais_guardado", "")
                        _prompt_ga = (
                            f"Eres un analista web experto en marketing digital.\n\n"
                            f"Analiza estas métricas del sitio web:\n"
                            f"- Sesiones: {_gd['sessions']}\n"
                            f"- Usuarios activos: {_gd['activeUsers']}\n"
                            f"- Usuarios nuevos: {_gd['newUsers']}\n"
                            f"- Tasa de rebote: {_gd['bounceRate']}%\n"
                            f"- Duración promedio: {_gd['avgDuration']} segundos\n"
                            f"- Páginas por sesión: {_gd['pagesPerSession']}\n"
                            f"- Fuentes de tráfico: {_gd['channels']}\n"
                            f"- Período: {_sel_periodo}\n"
                            f"- Nicho: {_nicho_ga} en {_pais_ga}\n\n"
                            f"Dame EXACTAMENTE esto sin introducciones:\n\n"
                            f"## 📊 DIAGNÓSTICO GENERAL\n"
                            f"[Qué está bien y qué está mal comparado con benchmarks del sector {_nicho_ga}]\n\n"
                            f"## 🔴 PROBLEMA PRINCIPAL\n"
                            f"[El problema más urgente con su causa exacta]\n\n"
                            f"## ✅ SOLUCIÓN CONCRETA\n"
                            f"[Pasos específicos numerados para arreglarlo]\n\n"
                            f"## 📈 OPORTUNIDAD DETECTADA\n"
                            f"[La mayor oportunidad de crecimiento basada en los datos]\n\n"
                            f"## 🎯 3 ACCIONES PARA ESTA SEMANA\n"
                            f"1. [acción específica]\n"
                            f"2. [acción específica]\n"
                            f"3. [acción específica]\n\n"
                            f"## 📉 MÉTRICA A MEJORAR PRIMERO\n"
                            f"[Una sola métrica con objetivo numérico]"
                        )
                        _res_ga = generar_analitico(_prompt_ga, max_tokens=4000)
                        st.session_state["ga_ia_result"] = _res_ga

                    if st.session_state.get("ga_ia_result"):
                        st.markdown(st.session_state["ga_ia_result"])
                        from datetime import datetime as _dt_ga
                        _fecha_ga = _dt_ga.now().strftime("%d/%m/%Y")
                        if st.button("💾 Guardar análisis en Mis Reportes" if not _is_en_int else "💾 Save to My Reports", key="ga_save_rep"):
                            guardar_reporte(
                                _email_int, "google_analytics",
                                f"📊 Análisis GA — {_fecha_ga}",
                                st.session_state["ga_ia_result"]
                            )
                            st.success("✅ Guardado en Mis Reportes.")

            else:
                # NOT CONNECTED — show instructions + form
                st.info(
                    "📊 **Conecta Google Analytics** para que Tentakl analice el tráfico de tu web:\n\n"
                    "**Paso 1:** Ve a analytics.google.com\n"
                    "**Paso 2:** Admin → Configuración de propiedad\n"
                    "**Paso 3:** Copia tu ID de propiedad (G-XXXXXXXX)\n"
                    "**Paso 4:** Ve a console.cloud.google.com\n"
                    "**Paso 5:** Crea un proyecto → Habilita **Google Analytics Data API**\n"
                    "**Paso 6:** Crea credenciales → API Key\n"
                    "**Paso 7:** Pega ambos datos abajo" if not _is_en_int else
                    "📊 **Connect Google Analytics** so Tentakl can analyze your web traffic:\n\n"
                    "**Step 1:** Go to analytics.google.com\n"
                    "**Step 2:** Admin → Property settings\n"
                    "**Step 3:** Copy your property ID (G-XXXXXXXX)\n"
                    "**Step 4:** Go to console.cloud.google.com\n"
                    "**Step 5:** Create project → Enable **Google Analytics Data API**\n"
                    "**Step 6:** Create credentials → API Key\n"
                    "**Step 7:** Paste both below"
                )

                _ga_pid_inp = st.text_input(
                    "ID de propiedad de Google Analytics" if not _is_en_int else "Google Analytics property ID",
                    placeholder="G-XXXXXXXXXX",
                    value=st.session_state.get("ga_property_id", ""),
                    key="ga_property_id"
                )
                _ga_key_inp = st.text_input(
                    "API Key de Google" if not _is_en_int else "Google API Key",
                    placeholder="AIzaSy...",
                    type="password",
                    key="ga_api_key"
                )

                if st.button("🔗 Conectar Google Analytics" if not _is_en_int else "🔗 Connect Google Analytics", key="ga_conectar"):
                    if not _ga_pid_inp.strip():
                        st.warning("Ingresa el ID de propiedad." if not _is_en_int else "Enter the property ID.")
                    elif not _ga_key_inp.strip():
                        st.warning("Ingresa la API Key." if not _is_en_int else "Enter the API Key.")
                    elif supabase:
                        try:
                            supabase.table("integraciones").upsert({
                                "user_email": _email_int,
                                "tipo": "google_analytics",
                                "account_id": _ga_pid_inp.strip(),
                                "access_token": _ga_key_inp.strip(),
                                "activo": True,
                            }, on_conflict="user_email,tipo").execute()
                            st.success("✅ Google Analytics conectado" if not _is_en_int else "✅ Google Analytics connected")
                            st.rerun()
                        except Exception as _e:
                            st.error(f"Error: {_e}")
                    else:
                        st.warning("Supabase no configurado.")

            # ── SECCIÓN 2 — Conectar mi Tienda ──────────────────────────────
            st.markdown("---")
            st.markdown("### \U0001f6d2 Conectar mi Tienda" if not _is_en_int else "### \U0001f6d2 Connect my Store")

            _config_tienda = obtener_config_tienda(_email_int)
            _tienda_conectada = _config_tienda is not None

            if _tienda_conectada:
                _tplat = _config_tienda["plataforma"]
                _turl = _config_tienda["url"]
                _twoo_ck = _config_tienda["consumer_key"]
                _twoo_cs = _config_tienda["consumer_secret"]
                st.success(f"\u2705 {_tplat} conectado: {_turl}" if not _is_en_int else f"\u2705 {_tplat} connected: {_turl}")
                st.caption("Tienda activa — disponible en Campaña de Catálogo" if not _is_en_int else "Active store — available in Catalog Campaign")
                if st.button("\U0001f50c Desconectar tienda" if not _is_en_int else "\U0001f50c Disconnect store", key="tienda_desconectar"):
                    if supabase:
                        try:
                            supabase.table("integraciones_tienda").update({"activa": False}) \
                                .eq("user_email", _email_int).execute()
                            st.success("Desconectado." if not _is_en_int else "Disconnected.")
                            st.rerun()
                        except Exception as _te:
                            st.error(str(_te))

                # -- Gestión de productos -------------------------------------------------------
                st.markdown("---")
                st.markdown("#### 📦 Gestión de productos")

                _base_url_t = ("https://" + _turl.rstrip("/")) if not _turl.startswith("http") else _turl.rstrip("/")

                if st.button("🔄 Cargar productos", key="tienda_cargar_prods"):
                    with st.spinner("Cargando productos..."):
                        try:
                            if _tplat == "WooCommerce":
                                _rp = requests.get(
                                    f"{_base_url_t}/wp-json/wc/v3/products",
                                    params={"per_page": 50, "status": "publish"},
                                    auth=(_twoo_ck, _twoo_cs), timeout=15
                                )
                                if _rp.status_code == 200:
                                    st.session_state["tienda_productos"] = _rp.json()
                                    st.success(f"\u2705 {len(st.session_state['tienda_productos'])} productos cargados")
                                else:
                                    st.error(f"Error {_rp.status_code}: {_rp.text[:200]}")
                        except Exception as _ep:
                            st.error(f"Error al cargar: {_ep}")

                _tienda_prods = st.session_state.get("tienda_productos", [])
                if _tienda_prods:
                    _prod_nombres = [
                        f"{p.get('name', p.get('title', 'Sin nombre'))} (ID: {p.get('id','')})"
                        for p in _tienda_prods
                    ]
                    _prod_idx = st.selectbox(
                        "Selecciona un producto:",
                        range(len(_prod_nombres)),
                        format_func=lambda i: _prod_nombres[i],
                        key="tienda_prod_sel"
                    )
                    _prod_sel = _tienda_prods[_prod_idx]
                    _prod_id  = _prod_sel.get("id")

                    _tc1, _tc2 = st.columns(2)
                    with _tc1:
                        st.markdown("**💲 Actualizar precio:**")
                        _precio_act = _prod_sel.get("regular_price", "")
                        _nuevo_precio = st.text_input("Nuevo precio:", value=_precio_act, key="tienda_nuevo_precio")
                        if st.button("💲 Actualizar precio", key="tienda_btn_precio"):
                            with st.spinner("Actualizando precio..."):
                                try:
                                    _ru = requests.put(
                                        f"{_base_url_t}/wp-json/wc/v3/products/{_prod_id}",
                                        json={"regular_price": _nuevo_precio},
                                        auth=(_twoo_ck, _twoo_cs), timeout=15
                                    )
                                    if _ru.status_code in (200, 201):
                                        st.success("\u2705 Precio actualizado")
                                        st.session_state.pop("tienda_productos", None)
                                    else:
                                        st.error(f"Error {_ru.status_code}: {_ru.text[:200]}")
                                except Exception as _epu:
                                    st.error(f"Error: {_epu}")

                    with _tc2:
                        st.markdown("**📝 Actualizar descripción:**")
                        _desc_act = _prod_sel.get("description", "")
                        _nueva_desc = st.text_area("Nueva descripción:", value=_desc_act[:500], height=120, key="tienda_nueva_desc")
                        if st.button("📝 Actualizar descripción", key="tienda_btn_desc"):
                            with st.spinner("Actualizando descripción..."):
                                try:
                                    _rd = requests.put(
                                        f"{_base_url_t}/wp-json/wc/v3/products/{_prod_id}",
                                        json={"description": _nueva_desc},
                                        auth=(_twoo_ck, _twoo_cs), timeout=15
                                    )
                                    if _rd.status_code in (200, 201):
                                        st.success("\u2705 Descripción actualizada")
                                        st.session_state.pop("tienda_productos", None)
                                    else:
                                        st.error(f"Error {_rd.status_code}: {_rd.text[:200]}")
                                except Exception as _edu:
                                    st.error(f"Error: {_edu}")

            else:
                _ti_plat = st.selectbox(
                    "Plataforma" if not _is_en_int else "Platform",
                    ["WooCommerce"], key="int_tienda_plat"
                )
                _ti_url = st.text_input(
                    "URL de tu tienda:" if not _is_en_int else "Your store URL:",
                    placeholder="https://mitienda.com",
                    key="int_tienda_url"
                )
                _ti_ck = st.text_input("Consumer Key:", placeholder="ck_...", key="int_woo_ck")
                _ti_cs = st.text_input("Consumer Secret:", placeholder="cs_...", type="password", key="int_woo_cs")
                # Google Analytics is optional — only URL, CK and CS are required
                _ti_ok = bool(_ti_url.strip() and _ti_ck.strip() and _ti_cs.strip())

                if st.button("\U0001f517 Conectar Tienda" if not _is_en_int else "\U0001f517 Connect Store", key="tienda_conectar"):
                    if not _ti_url.strip() or not _ti_ck.strip() or not _ti_cs.strip():
                        st.warning("Completa URL, Consumer Key y Consumer Secret" if not _is_en_int else "Fill in URL, Consumer Key and Consumer Secret")
                    else:
                        try:
                            guardar_config_tienda(_email_int, _ti_plat, _ti_url.strip(), _ti_ck.strip(), _ti_cs.strip())
                            with st.spinner("Verificando conexion..."):
                                _prods_test = obtener_productos_tienda(_email_int)
                            if _prods_test is not None:
                                st.success(f"Conectado! {len(_prods_test)} productos encontrados")
                            else:
                                st.warning("Credenciales guardadas, pero no se pudo conectar a la tienda. Verifica la URL y las claves.")
                            st.rerun()
                        except Exception as _te_det:
                            st.error(f"Error detallado: {str(_te_det)}")

            # ── SECCIÓN 3 — Próximamente ────────────────────────────────────
            st.markdown("---")
            st.markdown("### \U0001f504 Otras integraciones" if not _is_en_int else "### \U0001f504 Other integrations")
            _ic1, _ic2 = st.columns(2)
            with _ic1:
                st.info("\U0001f4d8 Facebook Business\n\U0001f51c Próximamente")
                st.info("\U0001f4f8 Instagram Business\n\U0001f51c Próximamente")
                st.info("\U0001f3b5 TikTok for Business\n\U0001f51c Próximamente")
            with _ic2:
                st.info("\U0001f4e7 Mailchimp\n\U0001f51c Próximamente")
                st.info("\U0001f6d2 Shopify Analytics\n\U0001f51c Próximamente")
                st.info("\U0001f4ca Google Ads\n\U0001f51c Próximamente")


# --- SECCIÓN: MIS REPORTES ---
if _sec_activa == "reportes":
    if not st.session_state.get("user_email", "").strip():
        st.warning("⚠ Ingresa tu email en el sidebar para acceder a esta sección." if st.session_state.get("lang") != "en" else "⚠ Enter your email in the sidebar to access this section.")
        st.info("👈 Panel izquierdo → Tu Cuenta → Email" if st.session_state.get("lang") != "en" else "👈 Left panel → Your Account → Email")
    st.subheader("📂 Mis Reportes")
    cliente_activo_nombre_rep = st.session_state.get("cliente_activo_nombre", "").strip()
    if cliente_activo_nombre_rep:
        st.caption(f"Mostrando reportes del cliente: {cliente_activo_nombre_rep}")

    email_rep = (st.session_state.get("user_email") or "").strip().lower()
    if not email_rep:
        st.warning("Ingresa tu email en la barra lateral para ver tus reportes.")
    else:
        reportes = obtener_reportes(email_rep)
        if not reportes:
            st.info("Aun no tienes reportes guardados.")
        else:
            # ── Filtro por tipo ────────────────────────────────────────────
            _tipos_disponibles = sorted(set(r.get("tipo_reporte", "general") for r in reportes))
            _filtro_opts = ["Todos"] + _tipos_disponibles
            _filtro_sel = st.selectbox("Filtrar por tipo:", _filtro_opts, key="rep_filtro_tipo")
            if _filtro_sel != "Todos":
                reportes = [r for r in reportes if r.get("tipo_reporte") == _filtro_sel]
            st.caption(f"Mostrando {len(reportes)} reporte(s)")
            # ──────────────────────────────────────────────────────────────
            for _ri, rep in enumerate(reportes):
                titulo_rep = rep.get("titulo", "Reporte sin titulo")
                tipo_rep = rep.get("tipo_reporte", "general")
                contenido_rep = rep.get("contenido", "")
                with st.expander(f"{titulo_rep} ({tipo_rep})"):
                    st.markdown(contenido_rep)
                    _rep_btn_col1, _rep_btn_col2 = st.columns(2)
                    with _rep_btn_col1:
                        try:
                            _pdf_bytes = generar_pdf_reportlab(titulo_rep, contenido_rep, email_rep)
                            _fname = titulo_rep[:40].replace(" ", "_").replace("/", "-") + ".pdf"
                            st.download_button(
                                label="Descargar PDF",
                                data=_pdf_bytes,
                                file_name=_fname,
                                mime="application/pdf",
                                key=f"dl_pdf_{_ri}",
                            )
                        except Exception as _pdf_err:
                            st.caption(f"PDF no disponible: {_pdf_err}")
                    with _rep_btn_col2:
                        if st.button("Usar como contexto", key=f"btn_ctx_{_ri}"):
                            st.session_state["contexto_reporte_activo"] = contenido_rep[:600]
                            st.session_state["contexto_reporte_titulo"] = titulo_rep
                            st.success(f"Contexto cargado: {titulo_rep[:50]}. Las proximas funciones lo usaran automaticamente.")

# ── KPI HELPERS ────────────────────────────────────────────────────────────────
def db_guardar_kpis(user_email, semana_key, ventas, seguidores, alcance_kpi, clics, leads, conversion):
    if not supabase:
        return False
    try:
        supabase.table("kpis_semanales").upsert({
            "user_email": user_email,
            "semana": semana_key,
            "ventas": float(ventas or 0),
            "seguidores": int(seguidores or 0),
            "alcance": int(alcance_kpi or 0),
            "clics": int(clics or 0),
            "leads": int(leads or 0),
            "conversion": float(conversion or 0),
        }, on_conflict="user_email,semana").execute()
        return True
    except Exception as _e:
        st.error(f"Error guardando KPIs: {_e}")
        return False

def db_obtener_kpis(user_email):
    if not supabase:
        return []
    try:
        r = supabase.table("kpis_semanales")\
            .select("*")\
            .eq("user_email", user_email)\
            .order("semana", desc=True)\
            .limit(8)\
            .execute()
        return r.data or []
    except Exception:
        return []

# --- SECCIÓN: POWER TOOLS (varios agentes) ---
if _sec_activa == "power":
    if not st.session_state.get("user_email", "").strip():
        st.warning("⚠ Ingresa tu email en el sidebar para acceder a esta sección." if st.session_state.get("lang") != "en" else "⚠ Enter your email in the sidebar to access this section.")
        st.info("👈 Panel izquierdo → Tu Cuenta → Email" if st.session_state.get("lang") != "en" else "👈 Left panel → Your Account → Email")
    _is_en_pw = st.session_state.get("lang") == "en"

    if _is_en_pw:
        st.subheader("\u26a1 POWER TOOLS")
        st.caption("Advanced tools for pros.")
    else:
        st.subheader("\u26a1 POWER TOOLS")
        st.caption("Herramientas avanzadas para profesionales.")

    opcion_power = _opcion_activa

    # ── 1. EMAIL MARKETING ────────────────────────────────────────────────────
    if opcion_power == "Email Marketing":
        if _is_en_pw:
            st.subheader("\U0001f4e7 Email Marketing")
            _em_tipos_disp = ["Welcome", "Abandoned Cart", "Reactivation", "Launch", "Newsletter"]
            _em_tipos_keys = ["welcome", "abandoned cart", "reactivation", "launch", "newsletter"]
            _em_tipo_lbl = "Email type:"
            _em_desc_lbl = "Describe your business and goal:"
            _em_desc_ph  = "Ex: I sell handmade jewelry. Goal: reactivate customers inactive 30+ days."
            _em_btn      = "\u26a1 Generate 5-email sequence (2 credits)"
        else:
            st.subheader("\U0001f4e7 Email Marketing")
            _em_tipos_disp = ["Bienvenida", "Carrito Abandonado", "Reactivaci\u00f3n", "Lanzamiento", "Newsletter"]
            _em_tipos_keys = ["bienvenida", "carrito abandonado", "reactivaci\u00f3n", "lanzamiento", "newsletter"]
            _em_tipo_lbl = "Tipo de email:"
            _em_desc_lbl = "Describe tu negocio y objetivo:"
            _em_desc_ph  = "Ej: Vendo joyer\u00eda artesanal. Objetivo: reactivar clientes inactivos m\u00e1s de 30 d\u00edas."
            _em_btn      = "\u26a1 Generar secuencia de 5 emails (2 cr\u00e9ditos)"

        # ── Memoria: contexto de ultimo catalogo/autopiloto ───────────────
        _em_email_mem = (st.session_state.get("user_email") or "").strip().lower()
        if _em_email_mem:
            _em_mem = obtener_ultimo_reporte_tipo(_em_email_mem, ["campaña_catalogo", "autopiloto"], dias=30)
            if _em_mem:
                _em_mem_fecha = str(_em_mem.get("created_at", ""))[:10]
                _em_mem_tipo  = _em_mem.get("tipo_reporte", "reporte")
                with st.expander(f"Contexto disponible: ultimo {_em_mem_tipo} ({_em_mem_fecha}) — click para usar"):
                    st.caption(_em_mem.get("contenido", "")[:400])
                    if st.button("Usar este contexto en el email", key="btn_em_mem_usar"):
                        st.session_state["em_ctx_previo"] = _em_mem.get("contenido", "")[:600]
                        st.success("Contexto cargado. Se incluira en el proximo email generado.")
        # ─────────────────────────────────────────────────────────────────────
        _em_tipo_sel = st.selectbox(_em_tipo_lbl, _em_tipos_disp, key="em_tipo")
        if st.button(_em_btn, key="btn_email_gen"):
            _em_nicho  = st.session_state.get("nicho_guardado", nicho)
            _em_marca  = st.session_state.get("marca_guardada", "")
            _em_pais   = st.session_state.get("pais_guardado", pais)
            _em_ciudad = st.session_state.get("ciudad_guardada", "")
            _em_prod   = st.session_state.get("producto_servicio", "")
            _em_client = st.session_state.get("cliente_ideal_guardado", "")
            if not _em_nicho and not _em_marca and not _em_prod:
                st.warning("Para usar esta función completa tu perfil en el sidebar primero ⚠" if not _is_en_pw else "Complete your business profile in the sidebar first ⚠")
            elif verificar_creditos(2):
                _em_ctx_extra = ""
                if st.session_state.get("em_ctx_previo"):
                    _em_ctx_extra = f"\nCONTEXTO PREVIO DEL NEGOCIO:\n{st.session_state['em_ctx_previo'][:500]}"
                _em_desc = (
                    f"Marca: {_em_marca}. Nicho: {_em_nicho}. "
                    f"Ubicación: {_em_ciudad}, {_em_pais}. "
                    f"Producto/Servicio: {_em_prod}. "
                    f"Cliente ideal: {_em_client}."
                ).strip()
                _em_moneda = PAISES_MONEDA.get(_em_pais, "$")
                _em_key    = _em_tipos_keys[_em_tipos_disp.index(_em_tipo_sel)]
                _em_prefix = "Respond ONLY in English. Adapt to US/global market.\n\n" if _is_en_pw else ""
                _em_prompt = (_em_prefix +
                    f"Crea una secuencia de 5 emails de tipo \"{_em_key}\" para este negocio:\n"
                    f"Marca: {_em_marca} | Nicho: {_em_nicho} | Pa\u00eds: {_em_pais} | Moneda: {_em_moneda}\n"
                    f"Descripci\u00f3n: {_em_desc}\n\n"
                    f"Para CADA uno de los 5 emails incluye:\n"
                    f"EMAIL N\u00b0[n\u00famero]:\n"
                    f"ASUNTO: [l\u00ednea de asunto optimizada, m\u00e1x 50 chars]\n"
                    f"PREVIEW TEXT: [texto de vista previa, m\u00e1x 40 chars]\n"
                    f"---\nCUERPO COMPLETO:\n[texto completo del email]\n---\n"
                    f"CTA: [llamada a acci\u00f3n espec\u00edfica y urgente]\n"
                    f"\U0001f4c5 MEJOR MOMENTO: [d\u00eda y hora exacta para enviar]\n"
                    f"\U0001f4a1 TIP ANTI-SPAM: [1 consejo para evitar carpeta de spam]\n"
                    f"================\n")
                with st.spinner("Generando secuencia..." if not _is_en_pw else "Generating sequence..."):
                    _em_res = generar_texto(_em_prompt, max_out=6000, modelo=MODELO_FUERTE)
                _em_email = (st.session_state.get("user_email") or "").strip().lower()
                if _em_email:
                    guardar_reporte(_em_email, "email_marketing",
                                    f"Secuencia {_em_tipo_sel} - {_em_marca}", _em_res)
                consumir(2)
                st.session_state["_ed_email_mkt"] = _em_res
                st.session_state["_ed_prompt_email_mkt"] = _em_prompt
        if st.session_state.get("_ed_email_mkt"):
            st.markdown(st.session_state["_ed_email_mkt"])
            _panel_edicion(st.session_state["_ed_email_mkt"], "email_mkt", max_tokens=6000)

    # ── 2. GESTIÓN DE COMUNIDAD ───────────────────────────────────────────────
    elif opcion_power == "Gesti\u00f3n de Comunidad":
        if _is_en_pw:
            st.subheader("\U0001f4ac Community Management")
            _cm_lbl = "Paste your comments, one per line:"
            _cm_ph  = "Is there delivery to downtown?\nThis product is terrible, very disappointed\nBest service I've ever tried!"
            _cm_btn = "\U0001f4ac Generate responses (1 credit)"
        else:
            st.subheader("\U0001f4ac Gesti\u00f3n de Comunidad")
            _cm_lbl = "Pega tus comentarios, uno por l\u00ednea:"
            _cm_ph  = "\u00bfTienen delivery a Miraflores?\nEste producto es mal\u00edsimo, me decepcion\u00f3\n\u00a1El mejor servicio que he probado!"
            _cm_btn = "\U0001f4ac Generar respuestas (1 cr\u00e9dito)"

        _cm_texto = st.text_area(_cm_lbl, placeholder=_cm_ph, height=150, key="cm_texto")
        if st.button(_cm_btn, key="btn_cm_gen"):
            if not _cm_texto.strip():
                st.warning("Pega al menos un comentario." if not _is_en_pw else "Paste at least one comment.")
            elif len(_cm_texto) > 3000:
                st.warning("⚠ Texto demasiado largo, máximo 3000 caracteres")
            elif verificar_creditos(1):
                _cm_texto = _sanitizar(_cm_texto)
                _cm_marca  = st.session_state.get("marca_guardada", "")
                _cm_nicho  = st.session_state.get("nicho_guardado", nicho)
                _cm_reglas = st.session_state.get("reglas_marca", "")
                _cm_prefix = "Respond ONLY in English.\n\n" if _is_en_pw else ""
                _cm_reglas_txt = f"\nReglas de marca a respetar:\n{_cm_reglas}\n" if _cm_reglas else ""
                _cm_prompt = (_cm_prefix +
                    f"Eres el community manager de la marca \"{_cm_marca}\" ({_cm_nicho}).\n"
                    f"{_cm_reglas_txt}\n"
                    f"Para cada comentario genera una respuesta profesional y hum\u00e4na.\n"
                    f"Formato para cada uno:\n"
                    f"COMENTARIO: [texto original]\n"
                    f"RESPUESTA SUGERIDA: [respuesta completa lista para copiar]\n"
                    f"TONO USADO: [emp\u00e1tico / profesional / entusiasta / resolutivo]\n"
                    f"---\n\nComentarios:\n{_cm_texto}")
                with st.spinner("Generando respuestas..." if not _is_en_pw else "Generating responses..."):
                    _cm_res = generar_texto(_cm_prompt, max_out=4000, modelo=MODELO_FUERTE)
                st.markdown(_cm_res)
                _cm_email = (st.session_state.get("user_email") or "").strip().lower()
                if _cm_email:
                    guardar_reporte(_cm_email, "community_management",
                                    f"Respuestas CM - {_cm_marca}", _cm_res)
                consumir(1)

    # ── 3. INFLUENCER MARKETING ───────────────────────────────────────────────
    elif opcion_power == "Influencer Marketing":
        if _is_en_pw:
            st.subheader("\U0001f31f Influencer Marketing")
            _inf_presup_lbl  = "Available budget (in your local currency):"
            _inf_obj_lbl     = "Objective:"
            _inf_obj_opts    = ["Awareness", "Sales", "Followers"]
            _inf_plat_lbl    = "Platform:"
            _inf_plat_opts   = ["Instagram", "TikTok", "YouTube"]
            _inf_btn         = "\U0001f31f Generate influencer strategy (2 credits)"
        else:
            st.subheader("\U0001f31f Influencer Marketing")
            _inf_presup_lbl  = "Presupuesto disponible (en moneda local):"
            _inf_obj_lbl     = "Objetivo:"
            _inf_obj_opts    = ["Awareness", "Ventas", "Seguidores"]
            _inf_plat_lbl    = "Plataforma:"
            _inf_plat_opts   = ["Instagram", "TikTok", "YouTube"]
            _inf_btn         = "\U0001f31f Generar estrategia de influencer (2 cr\u00e9ditos)"

        _inf_pais    = st.session_state.get("pais_guardado", pais)
        _inf_moneda  = PAISES_MONEDA.get(_inf_pais, "$")
        _inf_presup  = st.text_input(_inf_presup_lbl, placeholder=f"Ej: 500 {_inf_moneda}", key="inf_presup")
        _inf_obj     = st.selectbox(_inf_obj_lbl, _inf_obj_opts, key="inf_obj")
        _inf_plat    = st.selectbox(_inf_plat_lbl, _inf_plat_opts, key="inf_plat")
        if st.button(_inf_btn, key="btn_inf_gen"):
            if not _inf_presup.strip():
                st.warning("Ingresa tu presupuesto." if not _is_en_pw else "Enter your budget.")
            elif verificar_creditos(2):
                _inf_nicho  = st.session_state.get("nicho_guardado", nicho)
                _inf_marca  = st.session_state.get("marca_guardada", "")
                _inf_prod   = st.session_state.get("producto_servicio", "")
                _inf_prefix = "Respond ONLY in English. Adapt to global market.\n\n" if _is_en_pw else ""
                _inf_prompt = (_inf_prefix +
                    f"Crea una estrategia completa de influencer marketing para:\n"
                    f"Marca: {_inf_marca} | Nicho: {_inf_nicho} | Pa\u00eds: {_inf_pais}\n"
                    f"Qu\u00e9 vende: {_inf_prod}\n"
                    f"Presupuesto: {_inf_presup} {_inf_moneda}\n"
                    f"Objetivo: {_inf_obj} | Plataforma: {_inf_plat}\n\n"
                    f"Genera:\n"
                    f"1. PERFIL DEL INFLUENCER IDEAL:\n"
                    f"   - Tama\u00f1o de audiencia recomendado\n"
                    f"   - Nicho espec\u00edfico y tipo de contenido\n"
                    f"   - Engagement m\u00ednimo requerido (%)\n"
                    f"   - Ejemplos de perfiles reales a buscar\n\n"
                    f"2. TIPO RECOMENDADO (mega/macro/micro/nano):\n"
                    f"   Justificaci\u00f3n + precio estimado en {_inf_moneda}\n\n"
                    f"3. BRIEF CREATIVO COMPLETO:\n"
                    f"   Mensaje clave, formato, hashtags, do's y don'ts\n\n"
                    f"4. CONTRATO B\u00c1SICO (texto plano):\n"
                    f"   Cl\u00e1usulas esenciales de entregables, pago, exclusividad\n\n"
                    f"5. KPIs PARA MEDIR RESULTADO:\n"
                    f"   M\u00e9tricas espec\u00edficas y metas realistas\n\n"
                    f"6. TEMPLATE DE DM PARA CONTACTAR:\n"
                    f"   Mensaje directo listo para enviar\n")
                with st.spinner("Creando estrategia..." if not _is_en_pw else "Creating strategy..."):
                    _inf_res = generar_texto(_inf_prompt, max_out=6000, modelo=MODELO_FUERTE)
                st.markdown(_inf_res)
                _inf_email = (st.session_state.get("user_email") or "").strip().lower()
                if _inf_email:
                    guardar_reporte(_inf_email, "influencer_marketing",
                                    f"Influencer {_inf_plat} - {_inf_marca}", _inf_res)
                consumir(2)

    # ── 4. AUDITORÍA SEO COMPLETA ─────────────────────────────────────────────
    elif opcion_power == "Auditor\u00eda SEO Completa":
        if _is_en_pw:
            st.subheader("\U0001f50d Complete SEO Audit")
            _seo_pag_lbl  = "Page type:"
            _seo_pag_opts = ["Homepage", "Product", "Blog", "Services"]
            _seo_man_lbl  = "\U0001f4cb Paste your page content here"
            _seo_man_ph   = ("Copy and paste: titles, descriptions, main texts, product names, "
                             "testimonials, any visible text on your website...")
            _seo_btn      = "\U0001f50d Run SEO Audit (3 credits)"
        else:
            st.subheader("\U0001f50d Auditor\u00eda SEO Completa")
            _seo_pag_lbl  = "Tipo de p\u00e1gina:"
            _seo_pag_opts = ["Inicio", "Producto", "Blog", "Servicios"]
            _seo_man_lbl  = "\U0001f4cb Pega aqu\u00ed el contenido de tu p\u00e1gina web"
            _seo_man_ph   = ("Copia y pega: t\u00edtulos, descripciones, textos principales, "
                             "nombres de productos, testimonios, cualquier texto visible en tu web...")
            _seo_btn      = "\U0001f50d Ejecutar Auditor\u00eda SEO (3 cr\u00e9ditos)"

        _seo_pag = st.selectbox(_seo_pag_lbl, _seo_pag_opts, key="seo_pag")
        # \u2500\u2500 CAMBIO 5: analizar la URL real de la p\u00e1gina \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        _seo_url = st.text_input("\U0001F310 URL de tu p\u00e1gina (recomendado, an\u00e1lisis real):" if not _is_en_pw
                                  else "\U0001F310 Your page URL (recommended, real analysis):",
                                  placeholder="Ej: mitienda.com" if not _is_en_pw else "Ex: mystore.com",
                                  key="seo_url_scrape")
        _seo_man = st.text_area(_seo_man_lbl, placeholder=_seo_man_ph, height=200, key="seo_man")
        if st.button(_seo_btn, key="btn_seo_gen"):
            _seo_scrape_txt = ""
            if _seo_url.strip():
                with st.spinner("\U0001F310 Leyendo tu p\u00e1gina..." if not _is_en_pw else "\U0001F310 Reading your page..."):
                    _seo_sc = scrapear_url(_seo_url)
                if _seo_sc.get("error"):
                    st.warning(f"\U0001F310 {_seo_sc['error']}")
                else:
                    _seo_scrape_txt = _scrape_a_texto(_seo_sc)
                    st.success(f"\u2705 P\u00e1gina le\u00edda: {_seo_sc['title'][:60]}")
            if not _seo_man.strip() and not _seo_scrape_txt:
                st.warning("Pega el texto de tu p\u00e1gina o ingresa su URL." if not _is_en_pw else "Paste your page text or enter its URL.")
            elif verificar_creditos(3):
                _seo_raw_text = _seo_man.strip()[:5000]
                _seo_nicho  = st.session_state.get("nicho_guardado", nicho)
                _seo_marca  = st.session_state.get("marca_guardada", "")
                _seo_pais_v = st.session_state.get("pais_guardado", pais)
                _seo_prefix = "Respond ONLY in English.\n\n" if _is_en_pw else ""
                _seo_datos_str = (_seo_scrape_txt + "\n\n" if _seo_scrape_txt else "") + (f"Texto adicional pegado por el usuario:\n{_seo_raw_text}" if _seo_raw_text else "")

                _seo_prompt = (_seo_prefix +
                    f"Realiza una auditor\u00eda SEO completa para esta p\u00e1gina de tipo '{_seo_pag}'.\n"
                    f"Marca: {_seo_marca} | Nicho: {_seo_nicho} | Pa\u00eds: {_seo_pais_v}\n\n"
                    f"DATOS DE LA P\u00c1GINA:\n{_seo_datos_str}\n\n"
                    f"Genera:\n"
                    f"1. \U0001f4ca SCORE SEO ACTUAL: X/100 con justificaci\u00f3n\n\n"
                    f"2. \u274c PROBLEMAS CR\u00cdTICOS (ordenados por impacto):\n"
                    f"   - Cada problema con su nivel de impacto en el ranking\n\n"
                    f"3. \u26a0\ufe0f PROBLEMAS MENORES:\n\n"
                    f"4. \U0001f527 PLAN DE CORRECCI\u00d3N PASO A PASO:\n"
                    f"   Prioridad 1 a N con tiempo estimado cada uno\n\n"
                    f"5. \U0001f4dd META TITLE MEJORADO (m\u00e1x 60 chars):\n\n"
                    f"6. \U0001f4dd META DESCRIPTION MEJORADA (m\u00e1x 155 chars):\n\n"
                    f"7. \U0001f511 KEYWORDS SUGERIDAS (10 palabras clave principales):\n\n"
                    f"8. \U0001f4c8 SCORE ESTIMADO DESPU\u00c9S DE CORRECCIONES: X/100\n")
                with st.spinner("Ejecutando auditor\u00eda SEO..." if not _is_en_pw else "Running SEO audit..."):
                    _seo_res = generar_analitico(_seo_prompt, max_tokens=6000)
                st.markdown(_seo_res)
                _seo_email = (st.session_state.get("user_email") or "").strip().lower()
                if _seo_email:
                    guardar_reporte(_seo_email, "auditoria_seo",
                                    f"SEO Audit - {_seo_marca}", _seo_res)
                consumir(3)

    # ── 5. CALENDARIO CON HORARIOS ────────────────────────────────────────────
    # ── 6. PR DIGITAL ─────────────────────────────────────────────────────────
    elif opcion_power == "PR Digital":
        if _is_en_pw:
            st.subheader("\U0001f4f0 Digital PR Generator")
            _pr_tipo_opts = ["Launch", "Achievement", "Event", "Trend"]
            _pr_tipo_lbl  = "Type of news:"
            _pr_noticia_lbl = "Describe your news in 2-3 lines:"
            _pr_noticia_ph  = "Ex: We just launched our online store with 50 artisan products from Peru."
            _pr_btn = "\U0001f4f0 Generate PR kit (2 credits)"
        else:
            st.subheader("\U0001f4f0 PR Digital")
            _pr_tipo_opts = ["Lanzamiento", "Logro", "Evento", "Tendencia"]
            _pr_tipo_lbl  = "Tipo de noticia:"
            _pr_noticia_lbl = "Describe la noticia en 2-3 l\u00edneas:"
            _pr_noticia_ph  = "Ej: Acabamos de lanzar nuestra tienda online con 50 productos artesanales de Per\u00fa."
            _pr_btn = "\U0001f4f0 Generar kit de PR (2 cr\u00e9ditos)"

        _pr_tipo    = st.selectbox(_pr_tipo_lbl, _pr_tipo_opts, key="pr_tipo")
        _pr_noticia = st.text_area(_pr_noticia_lbl, placeholder=_pr_noticia_ph, height=90, key="pr_noticia")
        if st.button(_pr_btn, key="btn_pr_gen"):
            if not _pr_noticia.strip():
                st.warning("Describe la noticia primero." if not _is_en_pw else "Describe your news first.")
            elif len(_pr_noticia) > 3000:
                st.warning("⚠ Texto demasiado largo, máximo 3000 caracteres")
            elif verificar_creditos(2):
                _pr_noticia = _sanitizar(_pr_noticia)
                _pr_nicho  = st.session_state.get("nicho_guardado", nicho)
                _pr_marca  = st.session_state.get("marca_guardada", "")
                _pr_pais   = st.session_state.get("pais_guardado", pais)
                _pr_prefix = "Respond ONLY in English.\n\n" if _is_en_pw else ""
                _pr_prompt = (_pr_prefix +
                    f"Crea un kit completo de PR digital para:\n"
                    f"Marca: {_pr_marca} | Nicho: {_pr_nicho} | Pa\u00eds: {_pr_pais}\n"
                    f"Tipo: {_pr_tipo}\n"
                    f"Noticia: {_pr_noticia}\n\n"
                    f"Genera:\n"
                    f"1. \U0001f4f0 NOTA DE PRENSA COMPLETA:\n"
                    f"   - Titular gancho (m\u00e1x 80 chars)\n"
                    f"   - Bajada (1 p\u00e1rrafo)\n"
                    f"   - Cuerpo completo (3 p\u00e1rrafos)\n"
                    f"   - Cita del fundador/CEO\n"
                    f"   - Boilerplate de la empresa\n\n"
                    f"2. \U0001f4cb LISTA DE 10 MEDIOS DIGITALES LATAM RELEVANTES:\n"
                    f"   (espec\u00edficos para nicho {_pr_nicho})\n\n"
                    f"3. \U0001f4e7 TEMPLATE DE EMAIL PARA PERIODISTAS:\n\n"
                    f"4. \U0001f3f7\ufe0f HASHTAGS PARA REDES SOCIALES (10-15):\n\n"
                    f"5. \u23f0 TIMING RECOMENDADO:\n"
                    f"   Mejor d\u00eda y hora para distribuir en {_pr_pais}\n")
                with st.spinner("Generando kit de PR..." if not _is_en_pw else "Generating PR kit..."):
                    _pr_res = generar_texto(_pr_prompt, max_out=6000, modelo=MODELO_FUERTE)
                _pr_email = (st.session_state.get("user_email") or "").strip().lower()
                if _pr_email:
                    guardar_reporte(_pr_email, "pr_digital",
                                    f"PR {_pr_tipo} - {_pr_marca}", _pr_res)
                consumir(2)
                st.session_state["_ed_pr_dig"] = _pr_res
                st.session_state["_ed_prompt_pr_dig"] = _pr_prompt
        if st.session_state.get("_ed_pr_dig"):
            st.markdown(st.session_state["_ed_pr_dig"])
            _panel_edicion(st.session_state["_ed_pr_dig"], "pr_dig", max_tokens=6000)

    # ── 7. TRACKER DE KPIs ────────────────────────────────────────────────────
    elif opcion_power == "Tracker de KPIs":
        if _is_en_pw:
            st.subheader("\U0001f4ca KPI Tracker")
            _kpi_semana_lbl   = "Week:"
            _kpi_ventas_lbl   = "Total sales (local currency):"
            _kpi_segui_lbl    = "New followers (all networks):"
            _kpi_alcance_lbl  = "Total post reach:"
            _kpi_clics_lbl    = "Clicks to website or store:"
            _kpi_leads_lbl    = "Leads or contacts received:"
            _kpi_conv_lbl     = "Conversion rate (%):"
            _kpi_btn          = "\U0001f4be Save & Analyze (1 credit)"
        else:
            st.subheader("\U0001f4ca Tracker de KPIs")
            _kpi_semana_lbl   = "Semana:"
            _kpi_ventas_lbl   = "Ventas totales (moneda local):"
            _kpi_segui_lbl    = "Nuevos seguidores (todas las redes):"
            _kpi_alcance_lbl  = "Alcance total de publicaciones:"
            _kpi_clics_lbl    = "Clics en web o tienda:"
            _kpi_leads_lbl    = "Leads o contactos recibidos:"
            _kpi_conv_lbl     = "Tasa de conversi\u00f3n (%):"
            _kpi_btn          = "\U0001f4be Guardar y Analizar (1 cr\u00e9dito)"

        _kpi_email = (st.session_state.get("user_email") or "").strip().lower()
        if not _kpi_email:
            st.warning("Ingresa tu email en el sidebar para usar el tracker." if not _is_en_pw else "Enter your email in the sidebar to use the tracker.")
        else:
            _kpi_semana_display = obtener_semana_actual()
            _kpi_semana_key     = dt.now().strftime("%Y-W%V")
            st.info(f"\U0001f4c5 {_kpi_semana_lbl} {_kpi_semana_display}")

            _kpi_pais   = st.session_state.get("pais_guardado", pais)
            _kpi_moneda = PAISES_MONEDA.get(_kpi_pais, "$")

            _kpi_c1, _kpi_c2 = st.columns(2)
            with _kpi_c1:
                _kpi_ventas  = st.number_input(f"{_kpi_ventas_lbl} ({_kpi_moneda})", min_value=0.0, step=1.0, key="kpi_ventas")
                _kpi_alcance = st.number_input(_kpi_alcance_lbl, min_value=0, step=100, key="kpi_alcance")
                _kpi_leads   = st.number_input(_kpi_leads_lbl, min_value=0, step=1, key="kpi_leads")
            with _kpi_c2:
                _kpi_segui  = st.number_input(_kpi_segui_lbl, min_value=0, step=1, key="kpi_segui")
                _kpi_clics  = st.number_input(_kpi_clics_lbl, min_value=0, step=1, key="kpi_clics")
                _kpi_conv   = st.number_input(_kpi_conv_lbl, min_value=0.0, max_value=100.0, step=0.1, key="kpi_conv")

            if st.button(_kpi_btn, key="btn_kpi_save"):
                if verificar_creditos(1):
                    _saved = db_guardar_kpis(
                        _kpi_email, _kpi_semana_key,
                        _kpi_ventas, _kpi_segui, _kpi_alcance,
                        _kpi_clics, _kpi_leads, _kpi_conv
                    )
                    if _saved:
                        st.success("\u2705 KPIs guardados." if not _is_en_pw else "\u2705 KPIs saved.")

                    _kpi_hist = db_obtener_kpis(_kpi_email)
                    if len(_kpi_hist) >= 2:
                        try:
                            _kpi_df = pd.DataFrame(_kpi_hist[::-1])
                            _kpi_df = _kpi_df[["semana", "ventas", "seguidores", "alcance", "clics", "leads"]].set_index("semana")
                            st.line_chart(_kpi_df)
                        except Exception:
                            pass

                    _kpi_prefix = "Respond ONLY in English.\n\n" if _is_en_pw else ""
                    _kpi_ant = _kpi_hist[1] if len(_kpi_hist) > 1 else {}
                    _kpi_prompt = (_kpi_prefix +
                        f"Analiza estos KPIs semanales del negocio:\n"
                        f"Semana actual: {_kpi_semana_display}\n"
                        f"Ventas: {_kpi_ventas} {_kpi_moneda} (anterior: {_kpi_ant.get('ventas', 'N/A')})\n"
                        f"Seguidores nuevos: {_kpi_segui} (anterior: {_kpi_ant.get('seguidores', 'N/A')})\n"
                        f"Alcance: {_kpi_alcance} (anterior: {_kpi_ant.get('alcance', 'N/A')})\n"
                        f"Clics: {_kpi_clics} (anterior: {_kpi_ant.get('clics', 'N/A')})\n"
                        f"Leads: {_kpi_leads} (anterior: {_kpi_ant.get('leads', 'N/A')})\n"
                        f"Conversi\u00f3n: {_kpi_conv}% (anterior: {_kpi_ant.get('conversion', 'N/A')}%)\n\n"
                        f"Genera:\n"
                        f"1. QU\u00c9 MEJOR\u00d3 vs semana anterior (con % exacto)\n"
                        f"2. QU\u00c9 BAJ\u00d3 y posible causa\n"
                        f"3. 3 ACCIONES CONCRETAS para la pr\u00f3xima semana\n"
                        f"4. PROYECCI\u00d3N DEL MES si sigue a este ritmo\n")
                    with st.spinner("Analizando KPIs..." if not _is_en_pw else "Analyzing KPIs..."):
                        _kpi_res = generar_analitico(_kpi_prompt, max_tokens=6000)
                    st.markdown(_kpi_res)
                    guardar_reporte(_kpi_email, "kpi_tracker",
                                    f"KPIs {_kpi_semana_display}", _kpi_res)
                    consumir(1)

            # Show historical chart without clicking
            _kpi_hist_prev = db_obtener_kpis(_kpi_email)
            if len(_kpi_hist_prev) >= 2:
                if _is_en_pw:
                    st.markdown("#### \U0001f4c8 Historical performance (last 8 weeks)")
                else:
                    st.markdown("#### \U0001f4c8 Historial de las \u00faltimas semanas")
                try:
                    _kpi_df2 = pd.DataFrame(_kpi_hist_prev[::-1])
                    _kpi_df2 = _kpi_df2[["semana", "ventas", "seguidores", "alcance", "clics", "leads"]].set_index("semana")
                    st.line_chart(_kpi_df2)
                except Exception:
                    pass

    # ── 8. OPTIMIZADOR LANDING CRO ────────────────────────────────────────────
    elif opcion_power == "Optimizador Landing CRO":
        if _is_en_pw:
            st.subheader("\U0001f3af Landing Page Optimizer (CRO)")
            _cro_lbl = "Paste your complete landing page or sales page text:"
            _cro_ph  = "Paste all the text from your landing page here..."
            _cro_btn = "\U0001f3af Analyze and optimize (2 credits)"
        else:
            st.subheader("\U0001f3af Optimizador Landing CRO")
            _cro_lbl = "Pega el texto completo de tu landing page o p\u00e1gina de ventas:"
            _cro_ph  = "Pega aqu\u00ed todo el texto de tu landing page..."
            _cro_btn = "\U0001f3af Analizar y optimizar (2 cr\u00e9ditos)"

        # ── CAMBIO 5: analizar la URL real de la landing ───────────────────────
        _cro_url = st.text_input("🌐 URL de tu landing (recomendado, análisis real):" if not _is_en_pw
                                  else "🌐 Your landing URL (recommended, real analysis):",
                                  placeholder="Ej: mitienda.com/oferta" if not _is_en_pw else "Ex: mystore.com/offer",
                                  key="cro_url_scrape")
        _cro_texto = st.text_area(_cro_lbl, placeholder=_cro_ph, height=200, key="cro_texto")
        if st.button(_cro_btn, key="btn_cro_gen"):
            _cro_scrape_txt = ""
            if _cro_url.strip():
                with st.spinner("🌐 Leyendo tu landing..." if not _is_en_pw else "🌐 Reading your landing..."):
                    _cro_sc = scrapear_url(_cro_url)
                if _cro_sc.get("error"):
                    st.warning(f"🌐 {_cro_sc['error']}")
                else:
                    _cro_scrape_txt = _scrape_a_texto(_cro_sc)
                    st.success(f"✅ Landing leída: {_cro_sc['title'][:60]}")
                    if not _cro_texto.strip():
                        _cro_texto = _cro_sc["texto"][:3000]
            if not _cro_texto.strip():
                st.warning("Pega el texto de tu landing page o ingresa su URL." if not _is_en_pw else "Paste your landing page text or enter its URL.")
            elif len(_cro_texto) > 3000 and not _cro_scrape_txt:
                st.warning("⚠ Texto demasiado largo, máximo 3000 caracteres")
            elif verificar_creditos(2):
                _cro_texto = _sanitizar(_cro_texto)
                _cro_nicho  = st.session_state.get("nicho_guardado", nicho)
                _cro_marca  = st.session_state.get("marca_guardada", "")
                _cro_prod   = st.session_state.get("producto_servicio", "")
                _cro_prefix = "Respond ONLY in English. Adapt to US/global market.\n\n" if _is_en_pw else ""
                _cro_prompt = (_cro_prefix +
                    f"Analiza esta landing page y optimiz\u00e1la para m\u00e1xima conversi\u00f3n:\n"
                    f"Marca: {_cro_marca} | Nicho: {_cro_nicho} | Producto: {_cro_prod}\n\n"
                    f"TEXTO ACTUAL:\n{_cro_texto[:3000]}\n\n"
                    f"Genera:\n"
                    f"1. \U0001f4ca SCORE DE CONVERSI\u00d3N ACTUAL: X/100\n\n"
                    f"2. \u274c PROBLEMAS CR\u00cdTICOS DETECTADOS:\n"
                    f"   \u2714 \u00bfEl t\u00edtulo dice claramente qu\u00e9 ofreces?\n"
                    f"   \u2714 \u00bfEl CTA es visible y espec\u00edfico?\n"
                    f"   \u2714 \u00bfHay prueba social (testimonios/n\u00fameros)?\n"
                    f"   \u2714 \u00bfLas objeciones est\u00e1n resueltas?\n"
                    f"   \u2714 \u00bfLa propuesta de valor es \u00fanica?\n\n"
                    f"3. \u2728 VERSI\u00d3N MEJORADA COMPLETA:\n"
                    f"   - Nuevo titular principal\n"
                    f"   - Nuevo subt\u00edtulo\n"
                    f"   - 3 bullets de beneficios optimizados\n"
                    f"   - CTA mejorado con urgencia\n"
                    f"   - Secci\u00f3n de testimonios sugerida\n"
                    f"   - 3 preguntas FAQ para resolver objeciones\n\n"
                    f"4. \U0001f4c8 ESTIMADO DE MEJORA:\n"
                    f"   \"Con estos cambios podr\u00edas pasar del X% al Y% de conversi\u00f3n\"\n"
                    f"   (usa benchmarks reales del nicho {_cro_nicho})\n")
                with st.spinner("Optimizando landing page..." if not _is_en_pw else "Optimizing landing page..."):
                    _cro_res = generar_analitico(_cro_prompt, max_tokens=6000)
                st.markdown(_cro_res)
                _cro_email = (st.session_state.get("user_email") or "").strip().lower()
                if _cro_email:
                    guardar_reporte(_cro_email, "landing_cro",
                                    f"CRO Audit - {_cro_marca}", _cro_res)
                consumir(2)


# --- SECCIÓN: AUTOPILOTO (Centro de Mando completo, FASE 5) ---
if _sec_activa == "autopiloto":
    _is_en_ap = st.session_state.get("lang") == "en"
    _email_ap = (st.session_state.get("user_email") or "").strip().lower()
    _plan_ap = st.session_state.get("plan", "Free")
    _mes_ap = dt.now().strftime("%Y-%m")

    st.subheader("⚡ Autopiloto" if not _is_en_ap else "⚡ Autopilot")
    st.caption("Tu equipo de agentes coordinado: tú das el objetivo, el pulpo organiza y ejecuta · 8 créditos por corrida"
               if not _is_en_ap else
               "Your coordinated agent team: you set the goal, the octopus organizes and executes · 8 credits per run")

    if not _email_ap:
        st.warning("⚠ Ingresa tu email en el sidebar para acceder a esta sección."
                   if not _is_en_ap else "⚠ Enter your email in the sidebar to access this section.")
    elif _plan_ap not in ("Pro", "Agency", "Admin"):
        _mostrar_upgrade("🔒 " + ("El Autopiloto está disponible desde el plan Pro ($39/mes). Deja que tu equipo completo trabaje por ti:"
                                  if not _is_en_ap else
                                  "Autopilot is available from the Pro plan ($39/mo). Let your whole team work for you:"))
    else:
        _usos_ap = db_get_autopiloto_usos(_email_ap, _mes_ap)
        st.caption(f"Corridas este mes: {_usos_ap}" if not _is_en_ap else f"Runs this month: {_usos_ap}")

        _cm_fase_ap = st.session_state.get("cm_fase")

        if _cm_fase_ap not in ("confirmar", "ejecutar", "done"):
            _ap_obj = st.text_area(
                "¿Qué necesitas que tu equipo logre?" if not _is_en_ap else "What do you need your team to achieve?",
                value=st.session_state.get("objetivo_actual", ""),
                placeholder=("Ej: Quiero aumentar ventas 30% este mes, tengo un nuevo producto lanzando la próxima semana."
                             if not _is_en_ap else
                             "Ex: I want to increase sales 30% this month, launching a new product next week."),
                height=90, key="ap_obj_cm",
            )
            if st.button("🧠 " + ("Planificar mi equipo (gratis)" if not _is_en_ap else "Plan my team (free)"),
                         key="btn_ap_planificar"):
                if not _ap_obj.strip():
                    st.warning("Escribe primero qué quieres lograr." if not _is_en_ap else "First write what you want to achieve.")
                else:
                    st.session_state["objetivo_actual"] = _ap_obj.strip()
                    with st.spinner("🐙 El pulpo está analizando tu objetivo..." if not _is_en_ap
                                    else "🐙 The octopus is analyzing your goal..."):
                        st.session_state["cm_plan"] = seleccionar_agentes_para_objetivo(_ap_obj.strip())
                    st.session_state["cm_fase"] = "confirmar"
                    st.rerun()

        if _cm_fase_ap == "confirmar" and st.session_state.get("cm_plan"):
            _cm_render_confirmacion(_is_en_ap, _plan_ap)
        elif _cm_fase_ap == "ejecutar":
            _cm_render_ejecucion(_is_en_ap)
        elif _cm_fase_ap == "done":
            _cm_render_done(_is_en_ap)

# ══════════════════════════════════════════════════════════════════════════════

def crm_get_contactos(user_email):
    if not supabase or not user_email:
        return []
    try:
        r = supabase.table("crm_contactos").select("*") \
            .eq("user_email", user_email) \
            .order("ultima_interaccion", desc=True) \
            .execute()
        return r.data or []
    except Exception:
        return []

def crm_add_contacto(user_email, nombre, email_c, telefono, empresa, pais_c, fuente, valor, notas):
    if not supabase:
        return False
    try:
        from datetime import datetime as _dt3
        supabase.table("crm_contactos").insert({
            "user_email": user_email,
            "nombre": nombre,
            "email_contacto": email_c,
            "telefono": telefono,
            "empresa": empresa,
            "pais": pais_c,
            "fuente": fuente,
            "valor_estimado": float(valor) if valor else None,
            "notas": notas,
            "estado": "nuevo",
            "ultima_interaccion": _dt3.now().isoformat(),
        }).execute()
        return True
    except Exception as _e:
        st.error(f"Error guardando contacto: {_e}")
        return False

def crm_update_estado(contacto_id, nuevo_estado):
    if not supabase:
        return
    try:
        supabase.table("crm_contactos").update({"estado": nuevo_estado}) \
            .eq("id", contacto_id).execute()
    except Exception:
        pass

def crm_get_interacciones(contacto_id):
    if not supabase:
        return []
    try:
        r = supabase.table("crm_interacciones").select("*") \
            .eq("contacto_id", contacto_id) \
            .order("fecha", desc=True) \
            .execute()
        return r.data or []
    except Exception:
        return []

def crm_add_interaccion(contacto_id, tipo, descripcion, resultado):
    if not supabase:
        return False
    try:
        from datetime import datetime as _dt3
        _now = _dt3.now().isoformat()
        supabase.table("crm_interacciones").insert({
            "contacto_id": contacto_id,
            "tipo": tipo,
            "descripcion": descripcion,
            "resultado": resultado,
            "fecha": _now,
        }).execute()
        supabase.table("crm_contactos").update({"ultima_interaccion": _now}) \
            .eq("id", contacto_id).execute()
        return True
    except Exception as _e:
        st.error(f"Error guardando interacción: {_e}")
        return False

def crm_get_tareas(user_email):
    if not supabase or not user_email:
        return []
    try:
        r = supabase.table("crm_tareas").select("*") \
            .eq("user_email", user_email) \
            .eq("completada", False) \
            .order("fecha_limite", desc=False) \
            .execute()
        return r.data or []
    except Exception:
        return []

def crm_add_tarea(user_email, contacto_id, descripcion, fecha_limite):
    if not supabase:
        return False
    try:
        supabase.table("crm_tareas").insert({
            "user_email": user_email,
            "contacto_id": contacto_id,
            "descripcion": descripcion,
            "fecha_limite": str(fecha_limite) if fecha_limite else None,
            "completada": False,
        }).execute()
        return True
    except Exception as _e:
        st.error(f"Error guardando tarea: {_e}")
        return False

def crm_completar_tarea(tarea_id):
    if not supabase:
        return
    try:
        supabase.table("crm_tareas").update({"completada": True}) \
            .eq("id", tarea_id).execute()
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN: CRM (agente Comercial)
# ══════════════════════════════════════════════════════════════════════════════
if _sec_activa == "crm":
    if not st.session_state.get("user_email", "").strip():
        st.warning("⚠ Ingresa tu email en el sidebar para acceder a esta sección." if st.session_state.get("lang") != "en" else "⚠ Enter your email in the sidebar to access this section.")
        st.info("👈 Panel izquierdo → Tu Cuenta → Email" if st.session_state.get("lang") != "en" else "👈 Left panel → Your Account → Email")
    from datetime import datetime as _dt_crm, date as _date_crm

    _email_crm = (st.session_state.get("user_email") or "").strip().lower()
    _is_en_crm = st.session_state.get("lang") == "en"

    st.subheader("👥 CRM — Gestión de Contactos" if not _is_en_crm else "👥 CRM — Contact Management")

    if not _email_crm:
        st.warning("Ingresa tu email en el sidebar para usar el CRM." if not _is_en_crm else "Enter your email in the sidebar to use the CRM.")
    else:
        # ── Load contacts ──────────────────────────────────────────────────────
        _contactos_crm = crm_get_contactos(_email_crm)

        _ESTADOS = {
            "nuevo":          "🔵 Nuevo",
            "contactado":     "🟡 Contactado",
            "interesado":     "🟠 Interesado",
            "compro":         "🟢 Compró",
            "no_interesado":  "🔴 No interesado",
        }
        _ESTADOS_EN = {
            "nuevo":          "🔵 New",
            "contactado":     "🟡 Contacted",
            "interesado":     "🟠 Interested",
            "compro":         "🟢 Bought",
            "no_interesado":  "🔴 Not interested",
        }
        _estado_labels = _ESTADOS_EN if _is_en_crm else _ESTADOS

        # helper: days since date string
        def _dias_desde(fecha_str):
            if not fecha_str:
                return "?"
            try:
                _d = _dt_crm.fromisoformat(str(fecha_str)[:19])
                return (_dt_crm.now() - _d).days
            except Exception:
                return "?"

        # ── SECCIÓN 1 — Pipeline Kanban ────────────────────────────────────────
        st.markdown("### 📊 Pipeline")
        _kanban_cols = ["nuevo", "contactado", "interesado", "compro"]
        _kanban_labels = {
            "nuevo":       "🔵 Nuevo",
            "contactado":  "🟡 Contactado",
            "interesado":  "🟠 Interesado",
            "compro":      "🟢 Compró",
        } if not _is_en_crm else {
            "nuevo":       "🔵 New",
            "contactado":  "🟡 Contacted",
            "interesado":  "🟠 Interested",
            "compro":      "🟢 Bought",
        }

        _col_k1, _col_k2, _col_k3, _col_k4 = st.columns(4)
        _kanban_map = {k: c for k, c in zip(_kanban_cols, [_col_k1, _col_k2, _col_k3, _col_k4])}

        for _estado_k, _col_k in _kanban_map.items():
            with _col_k:
                st.markdown(f"**{_kanban_labels[_estado_k]}**")
                _grupo = [c for c in _contactos_crm if c.get("estado") == _estado_k]
                if not _grupo:
                    st.caption("Sin contactos aquí" if not _is_en_crm else "No contacts here")
                else:
                    for _ct in _grupo:
                        _dias = _dias_desde(_ct.get("ultima_interaccion"))
                        _val = _ct.get("valor_estimado")
                        _val_str = f"${_val:,.0f}" if _val else ""
                        with st.container(border=True):
                            st.markdown(f"**{_ct.get('nombre', '?')}**")
                            if _ct.get("empresa"):
                                st.caption(_ct["empresa"])
                            if _val_str:
                                st.caption(_val_str)
                            st.caption(f"🕐 {_dias}d" if not _is_en_crm else f"🕐 {_dias}d ago")
                            if st.button("Ver detalle" if not _is_en_crm else "View detail",
                                         key=f"ver_{_ct['id']}"):
                                st.session_state["crm_contacto_id"] = _ct["id"]
                                st.rerun()

        st.markdown("---")

        # ── SECCIÓN 2 — Agregar contacto ──────────────────────────────────────
        with st.expander("➕ Agregar contacto nuevo" if not _is_en_crm else "➕ Add new contact"):
            with st.form("form_add_contacto"):
                _fc1, _fc2 = st.columns(2)
                with _fc1:
                    _f_nombre  = st.text_input("Nombre *" if not _is_en_crm else "Name *",
                                               value=st.session_state.get("crm_f_nombre", ""))
                    _f_email   = st.text_input("Email del contacto" if not _is_en_crm else "Contact email",
                                               value=st.session_state.get("crm_f_email", ""))
                    _f_tel     = st.text_input("Teléfono" if not _is_en_crm else "Phone",
                                               value=st.session_state.get("crm_f_tel", ""))
                    _f_empresa = st.text_input("Empresa" if not _is_en_crm else "Company",
                                               value=st.session_state.get("crm_f_empresa", ""))
                with _fc2:
                    _f_pais    = st.text_input("País" if not _is_en_crm else "Country",
                                               value=st.session_state.get("crm_f_pais", ""))
                    _fuentes   = ["Instagram", "Facebook", "Referido", "Web", "Ads", "WhatsApp", "Otro"]
                    _f_fuente  = st.selectbox("Fuente" if not _is_en_crm else "Source", _fuentes)
                    _f_valor   = st.number_input("Valor estimado ($)" if not _is_en_crm else "Estimated value ($)",
                                                 min_value=0.0, value=0.0, step=10.0)
                _f_notas = st.text_area("Notas" if not _is_en_crm else "Notes",
                                        value=st.session_state.get("crm_f_notas", ""), height=80)
                _submit_c = st.form_submit_button("💾 Guardar contacto" if not _is_en_crm else "💾 Save contact")

                if _submit_c:
                    if not _f_nombre.strip():
                        st.warning("El nombre es obligatorio." if not _is_en_crm else "Name is required.")
                    else:
                        st.session_state["crm_f_nombre"]  = _f_nombre
                        st.session_state["crm_f_email"]   = _f_email
                        st.session_state["crm_f_tel"]     = _f_tel
                        st.session_state["crm_f_empresa"] = _f_empresa
                        st.session_state["crm_f_pais"]    = _f_pais
                        st.session_state["crm_f_notas"]   = _f_notas
                        if crm_add_contacto(_email_crm, _f_nombre.strip(), _f_email.strip(),
                                            _f_tel.strip(), _f_empresa.strip(), _f_pais.strip(),
                                            _f_fuente, _f_valor if _f_valor > 0 else None,
                                            _f_notas.strip()):
                            st.success("✅ Contacto guardado" if not _is_en_crm else "✅ Contact saved")
                            for _k in ["crm_f_nombre","crm_f_email","crm_f_tel","crm_f_empresa","crm_f_pais","crm_f_notas"]:
                                st.session_state.pop(_k, None)
                            st.rerun()

        # ── SECCIÓN 3 + 4 — Detalle del contacto ──────────────────────────────
        _cid = st.session_state.get("crm_contacto_id")
        if _cid:
            _ct_det = next((c for c in _contactos_crm if c.get("id") == _cid), None)
            if _ct_det is None:
                # reload in case it was just added
                _ct_det = next((c for c in crm_get_contactos(_email_crm) if c.get("id") == _cid), None)

            if _ct_det:
                st.markdown("---")
                st.markdown(f"### 📋 {_ct_det.get('nombre','')}")

                _dc1, _dc2 = st.columns([2, 1])
                with _dc1:
                    if _ct_det.get("empresa"):
                        st.markdown(f"**Empresa:** {_ct_det['empresa']}")
                    if _ct_det.get("email_contacto"):
                        st.markdown(f"**Email:** {_ct_det['email_contacto']}")
                    if _ct_det.get("telefono"):
                        st.markdown(f"**Teléfono:** {_ct_det['telefono']}")
                    if _ct_det.get("pais"):
                        st.markdown(f"**País:** {_ct_det['pais']}")
                    if _ct_det.get("fuente"):
                        st.markdown(f"**Fuente:** {_ct_det['fuente']}")
                    if _ct_det.get("valor_estimado"):
                        st.markdown(f"**Valor estimado:** ${_ct_det['valor_estimado']:,.0f}")
                    if _ct_det.get("notas"):
                        st.markdown(f"**Notas:** {_ct_det['notas']}")

                with _dc2:
                    _estado_actual = _ct_det.get("estado", "nuevo")
                    _estado_opts   = list(_ESTADOS.keys())
                    _estado_disp   = [_estado_labels.get(k, k) for k in _estado_opts]
                    _estado_idx    = _estado_opts.index(_estado_actual) if _estado_actual in _estado_opts else 0
                    _nuevo_estado_disp = st.selectbox(
                        "Estado en pipeline" if not _is_en_crm else "Pipeline stage",
                        _estado_disp,
                        index=_estado_idx,
                        key="crm_sel_estado"
                    )
                    _nuevo_estado = _estado_opts[_estado_disp.index(_nuevo_estado_disp)]
                    if _nuevo_estado != _estado_actual:
                        crm_update_estado(_cid, _nuevo_estado)
                        st.success("✅ Estado actualizado" if not _is_en_crm else "✅ Stage updated")
                        st.rerun()

                    if st.button("❌ Cerrar detalle" if not _is_en_crm else "❌ Close detail",
                                 key="crm_close"):
                        st.session_state.pop("crm_contacto_id", None)
                        st.rerun()

                # ── Historial de interacciones ─────────────────────────────────
                st.markdown("#### 💬 Historial de interacciones" if not _is_en_crm else "#### 💬 Interaction history")
                _interacciones = crm_get_interacciones(_cid)
                if not _interacciones:
                    st.caption("Sin interacciones registradas." if not _is_en_crm else "No interactions recorded.")
                else:
                    for _inter in _interacciones:
                        _fecha_i = str(_inter.get("fecha", ""))[:16]
                        _tipo_i  = _inter.get("tipo", "")
                        _desc_i  = _inter.get("descripcion", "")
                        _res_i   = _inter.get("resultado", "")
                        with st.container(border=True):
                            st.caption(f"{_fecha_i} — {_tipo_i}")
                            if _desc_i:
                                st.markdown(_desc_i)
                            if _res_i:
                                st.markdown(f"**Resultado:** {_res_i}")

                # Formulario agregar interacción
                with st.expander("➕ Agregar interacción" if not _is_en_crm else "➕ Add interaction"):
                    with st.form("form_add_interaccion"):
                        _tipos_i = ["Llamada", "Email", "WhatsApp", "Reunión", "Otro"]
                        _fi_tipo = st.selectbox("Tipo" if not _is_en_crm else "Type", _tipos_i)
                        _fi_desc = st.text_area("¿Qué pasó?" if not _is_en_crm else "What happened?",
                                                key="crm_fi_desc")
                        _fi_res  = st.text_input("¿Cuál fue el resultado?" if not _is_en_crm else "What was the result?",
                                                 key="crm_fi_res")
                        _sub_i   = st.form_submit_button("Guardar interacción" if not _is_en_crm else "Save interaction")
                        if _sub_i:
                            if crm_add_interaccion(_cid, _fi_tipo, _fi_desc.strip(), _fi_res.strip()):
                                st.success("✅ Interacción guardada" if not _is_en_crm else "✅ Interaction saved")
                                st.rerun()

                # ── SECCIÓN 4 — IA para el contacto ───────────────────────────
                st.markdown("---")
                st.markdown("#### 🤖 IA para este lead" if not _is_en_crm else "#### 🤖 AI for this lead")
                _dias_ct = _dias_desde(_ct_det.get("ultima_interaccion"))
                _ia_btn_lbl = "💬 ¿Qué le escribo? (1 crédito)" if not _is_en_crm else "💬 What should I write? (1 credit)"

                if st.button(_ia_btn_lbl, key="crm_ia_btn"):
                    if verificar_creditos(1):
                        _marca_crm  = st.session_state.get("marca_guardada", "")
                        _pais_crm   = st.session_state.get("pais_guardado", "")
                        _nicho_crm  = st.session_state.get("nicho_guardado", "")
                        _oferta_crm = st.session_state.get("producto_servicio", "")
                        _cliente_crm = st.session_state.get("cliente_ideal_guardado", "")
                        _ctx_neg = (
                            f"Marca: {_marca_crm}\n"
                            f"País: {_pais_crm}\n"
                            f"Nicho: {_nicho_crm}\n"
                            f"Oferta: {_oferta_crm}\n"
                            f"Cliente ideal: {_cliente_crm[:300]}"
                        )
                        _prompt_ia = (
                            f"Eres experto en ventas consultivas para LATAM.\n"
                            f"CONTEXTO DEL VENDEDOR:\n{_ctx_neg}\n\n"
                            f"DATOS DEL LEAD:\n"
                            f"Nombre: {_ct_det.get('nombre','')}\n"
                            f"Empresa: {_ct_det.get('empresa','')}\n"
                            f"Estado en pipeline: {_estado_labels.get(_ct_det.get('estado','nuevo'), '')}\n"
                            f"Días sin contacto: {_dias_ct}\n"
                            f"Fuente: {_ct_det.get('fuente','')}\n"
                            f"Notas: {_ct_det.get('notas','')}\n\n"
                            f"Genera el mensaje perfecto para este lead.\n"
                            f"Incluye:\n"
                            f"## CANAL RECOMENDADO\n"
                            f"[WhatsApp/Email/Llamada y por qué]\n\n"
                            f"## MENSAJE LISTO PARA ENVIAR\n"
                            f"[mensaje completo listo para copiar y pegar]\n\n"
                            f"## CTA ESPECÍFICO\n"
                            f"[qué acción quieres que tome]\n\n"
                            f"## PRÓXIMO PASO SUGERIDO\n"
                            f"[qué hacer si responde / si no responde]"
                        )
                        _ia_res = generar_texto(_prompt_ia, max_out=4000, modelo=MODELO_FUERTE)
                        st.session_state["crm_ia_result"] = _ia_res
                        consumir(1)

                if st.session_state.get("crm_ia_result"):
                    st.markdown(st.session_state["crm_ia_result"])

        # ── SECCIÓN 5 — Tareas pendientes ─────────────────────────────────────
        st.markdown("---")
        with st.expander("📋 Tareas pendientes" if not _is_en_crm else "📋 Pending tasks"):
            _tareas = crm_get_tareas(_email_crm)
            _hoy = _date_crm.today()

            if not _tareas:
                st.caption("Sin tareas pendientes." if not _is_en_crm else "No pending tasks.")
            else:
                for _t in _tareas:
                    _t_id    = _t.get("id")
                    _t_desc  = _t.get("descripcion", "")
                    _t_fecha = _t.get("fecha_limite")
                    _t_cid   = _t.get("contacto_id")
                    _t_nombre_c = next((c.get("nombre","") for c in _contactos_crm if c.get("id") == _t_cid), "")

                    _vencida = False
                    if _t_fecha:
                        try:
                            _vencida = _date_crm.fromisoformat(str(_t_fecha)[:10]) < _hoy
                        except Exception:
                            pass

                    _t_col1, _t_col2 = st.columns([1, 8])
                    with _t_col1:
                        _done = st.checkbox("", key=f"tarea_{_t_id}", value=False)
                        if _done:
                            crm_completar_tarea(_t_id)
                            st.rerun()
                    with _t_col2:
                        _color = "🔴" if _vencida else "🟡"
                        _fecha_str = f" — Vence: {_t_fecha}" if _t_fecha else ""
                        _contacto_str = f" ({_t_nombre_c})" if _t_nombre_c else ""
                        st.markdown(
                            f"{_color} **{_t_desc}**{_contacto_str}{_fecha_str}",
                        )

            st.markdown("---")
            st.markdown("**Agregar tarea**" if not _is_en_crm else "**Add task**")
            with st.form("form_add_tarea"):
                _contacto_opts = [(c["id"], c.get("nombre","")) for c in _contactos_crm]
                _contacto_names = ["(Ninguno)" if not _is_en_crm else "(None)"] + [n for _, n in _contacto_opts]
                _sel_c = st.selectbox("Contacto relacionado" if not _is_en_crm else "Related contact",
                                      _contacto_names)
                _sel_cid = None
                if _sel_c not in ("(Ninguno)", "(None)"):
                    _sel_cid = next((i for i, n in _contacto_opts if n == _sel_c), None)
                _ft_desc  = st.text_area("Descripción" if not _is_en_crm else "Description",
                                         key="crm_ft_desc")
                _ft_fecha = st.date_input("Fecha límite (opcional)" if not _is_en_crm else "Due date (optional)",
                                          value=None)
                _sub_t = st.form_submit_button("Agregar tarea" if not _is_en_crm else "Add task")
                if _sub_t:
                    if not _ft_desc.strip():
                        st.warning("Escribe una descripción." if not _is_en_crm else "Write a description.")
                    else:
                        if crm_add_tarea(_email_crm, _sel_cid, _ft_desc.strip(), _ft_fecha):
                            st.success("✅ Tarea agregada" if not _is_en_crm else "✅ Task added")
                            st.rerun()

# --- FOOTER ---
# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN: DASHBOARD ADMIN PRIVADO (CAMBIO 4)
# ══════════════════════════════════════════════════════════════════════════════
if _sec_activa == "admin_dashboard":
    if not _es_admin_ui:
        st.error("⛔ Acceso restringido.")
    elif not supabase:
        st.warning("Supabase no está conectado.")
    else:
        st.subheader("🛠 Dashboard Admin — Tentakl.ai")
        _hoy_dash = dt.now().strftime("%Y-%m-%d")
        _mes_dash = dt.now().strftime("%Y-%m")

        # ── Usuarios por plan + ingresos estimados ─────────────────────────────
        try:
            _u_rows = supabase.table("usuarios").select("email,plan,creditos_usados,imagenes_usadas,created_at").execute().data or []
        except Exception:
            _u_rows = []
        if _u_rows:
            _df_u = pd.DataFrame(_u_rows)
            _c_d1, _c_d2, _c_d3, _c_d4 = st.columns(4)
            _c_d1.metric("👥 Total usuarios", len(_df_u))
            _por_plan = _df_u["plan"].fillna("Free").value_counts()
            _ingresos = sum(int(_por_plan.get(_p, 0)) * _precio for _p, _precio in PRECIOS_PLANES.items())
            _c_d2.metric("💵 Ingresos estimados/mes", f"${_ingresos}")
            _nuevos_sem = 0
            if "created_at" in _df_u.columns:
                try:
                    _fechas_cr = pd.to_datetime(_df_u["created_at"], errors="coerce", utc=True)
                    _hace7 = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=7)
                    _nuevos_sem = int((_fechas_cr >= _hace7).sum())
                except Exception:
                    _nuevos_sem = 0
            _c_d3.metric("🆕 Nuevos esta semana", _nuevos_sem)
            _free_agotados = _df_u[(_df_u["plan"].fillna("Free") == "Free")
                                   & (_df_u["creditos_usados"].fillna(0).astype(int) >= 50)]
            _c_d4.metric("🎯 Free agotados (remarketing)", len(_free_agotados))

            st.markdown("**Usuarios por plan**")
            st.bar_chart(_por_plan)

            with st.expander("🎯 Lista remarketing: Free que agotaron créditos y no convirtieron"):
                if len(_free_agotados):
                    st.dataframe(_free_agotados[["email", "creditos_usados"]], use_container_width=True)
                else:
                    st.caption("Nadie por ahora.")
        else:
            st.info("Sin datos de usuarios todavía.")

        st.divider()

        # ── Consumo de créditos (uso_creditos) ─────────────────────────────────
        try:
            _uc_rows = supabase.table("uso_creditos").select("tipo_accion,creditos,agente,subfuncion,fecha,user_email").order("fecha", desc=True).limit(2000).execute().data or []
        except Exception:
            _uc_rows = []
        if _uc_rows:
            _df_uc = pd.DataFrame(_uc_rows)
            _df_uc["fecha_dt"] = pd.to_datetime(_df_uc["fecha"], errors="coerce", utc=True)
            _ahora_uc = pd.Timestamp.now(tz="UTC")
            _cr_hoy = int(_df_uc[_df_uc["fecha_dt"] >= _ahora_uc.normalize()]["creditos"].sum())
            _cr_sem = int(_df_uc[_df_uc["fecha_dt"] >= _ahora_uc - pd.Timedelta(days=7)]["creditos"].sum())
            _cr_mes = int(_df_uc[_df_uc["fecha_dt"] >= _ahora_uc - pd.Timedelta(days=30)]["creditos"].sum())
            _c_u1, _c_u2, _c_u3, _c_u4 = st.columns(4)
            _c_u1.metric("⚡ Créditos hoy", _cr_hoy)
            _c_u2.metric("📅 Esta semana", _cr_sem)
            _c_u3.metric("🗓 Este mes", _cr_mes)
            _img_mes = int((_df_uc[(_df_uc["tipo_accion"].isin(["imagen", "edicion_imagen"]))
                                   & (_df_uc["fecha_dt"] >= _ahora_uc - pd.Timedelta(days=30))]).shape[0])
            _c_u4.metric("🎨 Imágenes este mes", _img_mes)

            st.markdown("**Top 10 funciones más usadas**")
            _top_fn = _df_uc["subfuncion"].replace("", pd.NA).dropna().value_counts().head(10)
            if len(_top_fn):
                st.bar_chart(_top_fn)
            else:
                _top_fn2 = _df_uc["tipo_accion"].value_counts().head(10)
                st.bar_chart(_top_fn2)
        else:
            st.info("Aún no hay registros en uso_creditos.")

        # ── Usuarios por país (perfil_negocio) ─────────────────────────────────
        try:
            _pn_rows = supabase.table("perfil_negocio").select("pais").execute().data or []
        except Exception:
            _pn_rows = []
        if _pn_rows:
            st.markdown("**Usuarios por país**")
            _df_pn = pd.DataFrame(_pn_rows)
            st.bar_chart(_df_pn["pais"].fillna("Sin país").value_counts().head(15))

        st.divider()

        # ── Controles del admin ────────────────────────────────────────────────
        st.markdown("### 🎛 Controles")
        _emails_admin_list = sorted([str(u.get("email", "")) for u in _u_rows if u.get("email")])
        if _emails_admin_list:
            _c_ctrl1, _c_ctrl2 = st.columns(2)
            with _c_ctrl1:
                _usr_sel = st.selectbox("Usuario:", _emails_admin_list, key="admdash_usr")
                _plan_nuevo_sel = st.selectbox("Cambiar plan a:", ["Free", "Starter", "Pro", "Agency", "Admin"], key="admdash_plan")
                if st.button("💾 Aplicar plan", key="admdash_btn_plan"):
                    try:
                        supabase.table("usuarios").update({"plan": _plan_nuevo_sel}).eq("email", _usr_sel).execute()
                        st.success(f"✅ {_usr_sel} → {_plan_nuevo_sel}")
                    except Exception as _e_adm:
                        st.error(f"No se pudo cambiar el plan: {_e_adm}")
            with _c_ctrl2:
                _extra_n = st.number_input("Dar créditos extra:", min_value=1, max_value=1000, value=15, key="admdash_extra")
                if st.button("🎁 Dar créditos", key="admdash_btn_extra"):
                    try:
                        _u_act = supabase.table("usuarios").select("creditos_extra").eq("email", _usr_sel).limit(1).execute().data or []
                        _extra_act = int((_u_act[0].get("creditos_extra") if _u_act else 0) or 0)
                        supabase.table("usuarios").update({"creditos_extra": _extra_act + int(_extra_n)}).eq("email", _usr_sel).execute()
                        st.success(f"✅ +{int(_extra_n)} créditos para {_usr_sel}")
                    except Exception as _e_adm2:
                        st.error(f"No se pudo dar créditos: {_e_adm2}")

        # ── Reportes generados ─────────────────────────────────────────────────
        with st.expander("📂 Todos los reportes generados"):
            _f_email_rep = st.text_input("Filtrar por email (opcional):", key="admdash_f_email")
            _f_tipo_rep = st.text_input("Filtrar por tipo (opcional):", key="admdash_f_tipo")
            try:
                _q_rep = supabase.table("reportes").select("user_email,tipo_reporte,titulo,created_at").order("created_at", desc=True).limit(200)
                if _f_email_rep.strip():
                    _q_rep = _q_rep.eq("user_email", _f_email_rep.strip().lower())
                if _f_tipo_rep.strip():
                    _q_rep = _q_rep.eq("tipo_reporte", _f_tipo_rep.strip())
                _rep_rows = _q_rep.execute().data or []
                if _rep_rows:
                    st.dataframe(pd.DataFrame(_rep_rows), use_container_width=True)
                else:
                    st.caption("Sin reportes con esos filtros.")
            except Exception:
                st.caption("No se pudieron leer los reportes.")

        # ── Activar/desactivar funciones por plan (config_funciones) ───────────
        with st.expander("🔧 Funciones por plan (config_funciones)"):
            _todas_subf = sorted({s[0] for _agx in AGENTES.values() for s in _agx["subfunciones"]})
            _cf_funcion = st.selectbox("Función:", _todas_subf, key="admdash_cf_fn")
            _cf_plan = st.selectbox("Plan:", ["Free", "Starter", "Pro", "Agency"], key="admdash_cf_plan")
            _cf_activa = st.checkbox("Activa", value=True, key="admdash_cf_act")
            if st.button("💾 Guardar configuración", key="admdash_cf_btn"):
                try:
                    supabase.table("config_funciones").upsert({
                        "funcion": _cf_funcion, "plan": _cf_plan, "activa": _cf_activa,
                    }, on_conflict="funcion,plan").execute()
                    st.success("✅ Configuración guardada")
                except Exception as _e_cf:
                    st.error(f"No se pudo guardar: {_e_cf}")
            try:
                _cf_rows = supabase.table("config_funciones").select("*").execute().data or []
                if _cf_rows:
                    st.dataframe(pd.DataFrame(_cf_rows), use_container_width=True)
            except Exception:
                pass

st.markdown("---")
# ✅ FIX: alcance leído desde session_state para el footer (nunca da NameError)
st.caption(f"© 2026 TENTAKL.AI | V5.1 Full Integrated | {st.session_state.get('alcance', 'NACIONAL')}")




