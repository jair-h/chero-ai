"""Capa de agentes de Tentakl: definición de los 9 agentes y routing por reglas.

Datos puros + una función de selección por reglas (sin Streamlit ni llamadas
al modelo), extraídos de `app.py` para adelgazar el monolito. La selección con
IA (`seleccionar_agentes_para_objetivo`) sigue en app.py porque depende del
motor de texto y de session_state; aquí vive solo su respaldo determinista.
"""
from __future__ import annotations

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

# Tareas genéricas por agente (respaldo de routing) y mensajes de progreso
TAREAS_GENERICAS = {
    "estrategia": "Analiza el negocio, el mercado y define la estrategia para el objetivo",
    "contenido": "Crea el concepto, los mensajes y las piezas de contenido",
    "imagenes": "Define la dirección de arte y los briefs visuales de la campaña",
    "publicidad": "Diseña la campaña de ads con segmentación y presupuesto",
    "ventas": "Crea la oferta, los CTA y las respuestas a objeciones",
    "competencia": "Analiza a la competencia y define la diferenciación",
    "gestion": "Define el plan de seguimiento de clientes y consistencia de marca",
    "metricas": "Define los KPIs e indicadores de seguimiento del objetivo",
}

MENSAJES_AGENTE = {
    "estrategia": ("Analizando tu negocio, mercado y objetivo...", "Analyzing your business, market and goal..."),
    "contenido": ("Creando concepto, mensajes y calendario...", "Creating concept, messages and calendar..."),
    "imagenes": ("Generando propuestas visuales...", "Generating visual proposals..."),
    "publicidad": ("Preparando campaña, segmentación y variaciones...", "Preparing campaign, targeting and variations..."),
    "ventas": ("Creando oferta, CTA y respuestas a objeciones...", "Creating offer, CTAs and objection handling..."),
    "competencia": ("Analizando a tu competencia y sus gaps...", "Analyzing your competitors and their gaps..."),
    "gestion": ("Organizando seguimiento y gestión...", "Organizing follow-up and management..."),
    "metricas": ("Preparando indicadores y plan de seguimiento...", "Preparing KPIs and tracking plan..."),
}


def ocultar_generador_imagenes(agentes: dict) -> dict:
    """Quita la generación de imágenes del agente Imágenes (deja la Auditoría
    Visual, que solo analiza, no genera). Muta y devuelve el dict."""
    agentes["imagenes"]["subfunciones"] = [
        _sf for _sf in agentes["imagenes"]["subfunciones"]
        if _sf[3] != "Generador de Imagenes"
    ]
    agentes["imagenes"]["desc"] = (
        "Auditoría visual de tus videos y fotos",
        "Visual audit of your videos and photos",
    )
    return agentes


def seleccion_agentes_por_reglas(objetivo: str) -> dict:
    """Respaldo determinista si la selección con IA falla o devuelve JSON inválido.

    Devuelve {"objetivo_interpretado": str, "agentes": [(id, tarea), ...]}.
    """
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
            "agentes": [(_i, TAREAS_GENERICAS[_i]) for _i in _ids]}
