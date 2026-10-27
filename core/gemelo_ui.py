"""Gemelo Digital — INTERFAZ Streamlit (4 tabs).

La UI NO calcula: toda la matemática vive en core.gemelo (capa separada). Aquí
solo se recogen datos, se llama al motor, se grafica y la IA (inyectada) explica.

Para evitar imports circulares con el monolito app.py, las dependencias
externas (cliente Supabase, función generar_texto, logger) se INYECTAN por
parámetro en render(). Si falta alguna, la feature degrada con elegancia.
"""
from __future__ import annotations

import json
from datetime import datetime

import streamlit as st

from core import gemelo as G
from core import gemelo_card as GC
from core import gemelo_personas as GP
from integrations import stores as _stores

_SECTORES_LBL = {
    "retail_moda": "Retail / Moda",
    "food_beverage": "Comida y bebida",
    "servicios": "Servicios",
    "ecommerce_general": "E-commerce general",
    "otro": "Otro (escríbelo)",
}


def _meses_recientes(n=3):
    """Etiquetas de los últimos n meses COMPLETOS (calendario real), p. ej.
    si hoy es octubre 2026 → ['Jul 2026', 'Ago 2026', 'Sep 2026']."""
    _mes_es = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
               "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    hoy = datetime.now()
    y, m = hoy.year, hoy.month
    out = []
    for k in range(n):
        mm, yy = m - 1 - k, y
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append(f"{_mes_es[mm - 1]} {yy}")
    out.reverse()
    return out


def _noop(*_a, **_k):
    return None


def _num(x, d=0.0):
    """Convierte a float de forma segura (None/str/'' -> d). Evita que un valor
    raro en un resultado reviente el formateo (:.0f) de la pantalla."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def render(*, supabase=None, generar_texto=None, user_email="", marca="",
           sector_nicho="", moneda="S/", lang="es", log=None, historial_activo=True,
           store_config_fn=None, ref_link=""):
    """Dibuja el Gemelo Digital. Dependencias inyectadas (ver docstring)."""
    log = log or _noop
    _en = (lang == "en")
    # Link de referido del usuario (para unirlo a la tarjeta compartible)
    st.session_state["_gemelo_ref_link"] = ref_link or ""

    def T(es, en):
        return en if _en else es

    st.markdown(
        f"""<h3 style="border-left:6px solid #7C3AED;padding-left:10px;">
        🔮 {T('Gemelo Digital — simula tus ventas', 'Digital Twin — simulate your sales')}</h3>""",
        unsafe_allow_html=True,
    )
    st.caption(T("El número lo calcula un motor matemático (Monte Carlo); la IA solo te lo explica.",
                 "A math engine (Monte Carlo) computes the number; the AI just explains it."))

    if not (user_email or "").strip():
        st.warning(T("Ingresa tu email en el panel izquierdo para usar el Gemelo.",
                     "Enter your email in the left panel to use the Twin."))
        return

    # Por defecto: modo SIMPLE (una pantalla, en meses, para cualquiera).
    # El modo avanzado (4 pestañas, más tipos de decisión) queda a un toggle.
    _avanzado = st.toggle(
        T("⚙️ Modo avanzado (más decisiones, historial, equipo)",
          "⚙️ Advanced mode (more decisions, history, team)"),
        value=st.session_state.get("gemelo_avanzado", False), key="gemelo_avanzado")
    if not _avanzado:
        _render_simple(supabase, generar_texto, user_email, marca, sector_nicho, moneda, T, log,
                       store_config_fn=store_config_fn)
        return

    tabs = st.tabs([T("📥 Mis datos", "📥 My data"), T("🎛 Simular", "🎛 Simulate"),
                    T("📊 Resultado", "📊 Result"), T("📈 Historial", "📈 History")])

    # ── TAB 1 — MIS DATOS ───────────────────────────────────────────────────
    with tabs[0]:
        _tab_datos(supabase, user_email, moneda, T, log)

    # ── TAB 2 — SIMULAR ─────────────────────────────────────────────────────
    with tabs[1]:
        _tab_simular(supabase, generar_texto, user_email, marca, sector_nicho, moneda, T, log)

    # ── TAB 3 — RESULTADO ───────────────────────────────────────────────────
    with tabs[2]:
        _tab_resultado(marca, moneda, T, generar_texto)

    # ── TAB 4 — HISTORIAL (completo: Pro+) ──────────────────────────────────
    with tabs[3]:
        if historial_activo:
            _tab_historial(supabase, user_email, moneda, T, log)
        else:
            st.info("🔒 " + T("El historial y la precisión acumulada del Gemelo están en el plan Pro. "
                              "Con tu plan actual puedes simular todas las veces que quieras; "
                              "guardar el historial para medir la precisión semana a semana es Pro.",
                              "The Twin's history and cumulative accuracy are in the Pro plan. "
                              "On your current plan you can simulate as much as you want; "
                              "saving the history to track weekly accuracy is Pro."))
            st.caption("👉 tentakl.ai/planes")


# ══════════════════════════════════════════════════════════════════════════
# MODO SIMPLE — una sola pantalla, en MESES, apta para negocios sin datos
# ══════════════════════════════════════════════════════════════════════════
_PREGUNTAS_SIMPLE = {
    "presupuesto": ("💰 ¿Cuánto venderé el próximo mes?",
                    "💰 How much will I sell next month?"),
    "campana":     ("🔥 ¿Cuánto venderé en una campaña? (Cyber, Black, Navidad)",
                    "🔥 How much will I sell on a campaign? (Cyber, Black, Xmas)"),
    "precio":      ("🏷 ¿Me conviene subir el precio?",
                    "🏷 Should I raise my price?"),
    "zona":        ("📍 ¿Cómo me irá en una zona o distrito nuevo?",
                    "📍 How would I do in a new area or district?"),
}


def _render_simple(supabase, generar_texto, user_email, marca, sector_nicho, moneda, T, log,
                   store_config_fn=None):
    """El Gemelo en UNA pantalla: 3 preguntas, calcula y muestra el resultado
    ahí mismo. En MESES (no semanas) y con camino para negocios sin datos."""
    import pandas as pd

    st.caption(T("Responde 3 cosas y te doy un rango realista de ventas (no un número inventado).",
                 "Answer 3 things and I'll give you a realistic sales range (not a made-up number)."))

    # Confianza: precisión acumulada del Gemelo (predicho vs. real)
    try:
        _panel_precision(supabase, user_email, moneda, T, log)
    except Exception:
        log("panel_precision")

    # ── 1. ¿Qué quieres saber? ───────────────────────────────────────────────
    st.markdown("##### 1. " + T("¿Qué quieres saber?", "What do you want to know?"))
    _pregunta = st.radio("pregunta", list(_PREGUNTAS_SIMPLE),
                         format_func=lambda k: _PREGUNTAS_SIMPLE[k][1 if _en_lang() else 0],
                         key="gs_pregunta", label_visibility="collapsed")

    # Al cambiar de pregunta, el resultado viejo ya no aplica → se limpia.
    if st.session_state.get("gs_last_pregunta") != _pregunta:
        st.session_state["gs_last_pregunta"] = _pregunta
        st.session_state.pop("gemelo_resultado", None)
        st.session_state.pop("gemelo_personas", None)

    # Zona/distrito: flujo propio (es un estimado, no necesita historial mensual).
    if _pregunta == "zona":
        _render_simple_zona(supabase, generar_texto, user_email, marca, moneda, T, log)
        return

    # ── 2. ¿Ya vendes o recién empiezas? ─────────────────────────────────────
    st.markdown("##### 2. " + T("¿Ya vendes o recién empiezas?", "Do you already sell or just starting?"))
    _situacion = st.radio(
        "situacion", ["tengo", "nuevo"],
        format_func=lambda k: {"tengo": T("Ya tengo ventas", "I already have sales"),
                               "nuevo": T("Recién empiezo (no tengo datos)", "Just starting (no data)")}[k],
        horizontal=True, key="gs_situacion", label_visibility="collapsed")

    _sector_sel = st.selectbox(T("Tu rubro:", "Your sector:"), list(_SECTORES_LBL.keys()),
                               format_func=lambda k: _SECTORES_LBL[k], key="gs_sector")
    if _sector_sel == "otro":
        _otro = st.text_input(T("¿Cuál es tu rubro?", "What's your sector?"),
                              placeholder=T("Ej: mascotas, ferretería, cosmética...", "Ex: pets, hardware, cosmetics..."),
                              key="gs_sector_otro")
        st.caption("ℹ️ " + T("Para tu rubro usaré referencias generales de e-commerce (funciona igual). "
                             "El Gemelo se afina con TUS datos reales, no con el rubro.",
                             "I'll use general e-commerce benchmarks for your sector (works the same). "
                             "The Twin sharpens with YOUR real data, not the sector."))
        _sector = G.SECTOR_DEFAULT
    else:
        _sector = _sector_sel

    semanas = []  # son MESES (el motor es agnóstico al periodo)
    _df = None
    if _situacion == "tengo":
        st.caption("📅 " + T("Pon tus últimos 2 a 4 MESES. Solo 2 datos por mes: lo que invertiste en ads y lo que vendiste.",
                             "Enter your last 2-4 MONTHS: ad spend and sales per month."))
        _key = "gs_meses_df"
        if _key not in st.session_state:
            _saved = _cargar_datos(supabase, user_email, log)
            if _saved:
                st.session_state[_key] = pd.DataFrame([
                    {"Mes": (r.get("Semana") or f"Mes {i + 1}"),
                     "Inversión en ads": (float(r.get("Gasto Meta", 0) or 0) + float(r.get("Gasto Google", 0) or 0)
                                          + float(r.get("Gasto TikTok", 0) or 0)),
                     "Ventas": float(r.get("Ventas", 0) or 0)} for i, r in enumerate(_saved)])
            else:
                st.session_state[_key] = pd.DataFrame(
                    [{"Mes": _m, "Inversión en ads": 0.0, "Ventas": 0.0}
                     for _m in _meses_recientes(3)])
        _df = st.data_editor(st.session_state[_key], num_rows="dynamic",
                             use_container_width=True, key="gs_editor")
        st.caption("➕ " + T("¿Quieres agregar más meses? Escribe en la fila vacía del final de la tabla "
                             "(se agregan solas). Mientras más meses, más preciso.",
                             "Want more months? Type in the empty row at the bottom of the table "
                             "(rows add themselves). More months = more precise."))
        if st.session_state.pop("gs_autofill_ok", False):
            st.success("✅ " + T("Ventas traídas de tu tienda. Revisa los meses y agrega tu inversión en ads.",
                                 "Sales pulled from your store. Review the months and add your ad spend."))
        # Autollenar las VENTAS desde la tienda conectada (hoy: WooCommerce)
        if store_config_fn:
            st.caption("💡 " + T("Puedo traer tus VENTAS reales desde tu tienda. La inversión en ads la pones tú "
                                 "(pronto también será automática).",
                                 "I can pull your real SALES from your store. Ad spend you enter yourself "
                                 "(soon automatic too)."))
            if st.button("📥 " + T("Traer mis ventas de mi tienda", "Pull my sales from my store"),
                         key="gs_autofill", use_container_width=True):
                _cfg = None
                try:
                    _cfg = store_config_fn(user_email)
                except Exception:
                    log("gs_store_cfg")
                if not _cfg:
                    st.warning(T("No encuentro tu tienda conectada. Conéctala en 📋 Gestión → Integraciones.",
                                 "No connected store found. Connect it in Management → Integrations."))
                elif _cfg.get("plataforma") != "WooCommerce":
                    st.info(T(f"Por ahora el autollenado funciona con WooCommerce (tu tienda es {_cfg.get('plataforma', '—')}).",
                              f"Auto-fill currently supports WooCommerce (your store is {_cfg.get('plataforma', '—')})."))
                else:
                    with st.spinner(T("Leyendo tus ventas de WooCommerce...", "Reading your WooCommerce sales...")):
                        _filas, _err = _stores.fetch_woocommerce_sales_by_month(
                            _cfg.get("url", ""), _cfg.get("consumer_key", ""),
                            _cfg.get("consumer_secret", ""), meses=6)
                    if _err:
                        st.error(T("No pude traer las ventas: ", "Couldn't fetch sales: ") + _err)
                    elif not any(f["ventas"] > 0 for f in (_filas or [])):
                        st.warning(T("Tu tienda respondió, pero no veo ventas en los últimos meses. Llénalas a mano.",
                                     "Store responded but no sales in recent months. Fill them manually."))
                    else:
                        st.session_state[_key] = pd.DataFrame(
                            [{"Mes": f["mes"], "Inversión en ads": 0.0, "Ventas": f["ventas"]} for f in _filas])
                        st.session_state.pop("gs_editor", None)  # re-inicializa el editor con lo traído
                        st.session_state["gs_autofill_ok"] = True
                        st.rerun()
        _c1, _c2 = st.columns(2)
        _precio_def = _c1.number_input(
            T(f"Precio promedio de lo que vendes ({moneda})", f"Avg selling price ({moneda})"),
            min_value=0.0, value=0.0, step=1.0, key="gs_precio",
            help=T("Déjalo en 1 si registras el MONTO total de ventas (no unidades).",
                   "Leave at 1 if you track total REVENUE, not units."))
        _costo_def = _c2.number_input(T(f"Costo por unidad ({moneda})", f"Cost per unit ({moneda})"),
                                      min_value=0.0, value=0.0, step=1.0, key="gs_costo")
        for _, row in _df.iterrows():
            g = float(row.get("Inversión en ads", 0) or 0)
            semanas.append({"gasto": {c: g / 3.0 for c in G.CANALES},
                            "ventas": float(row.get("Ventas", 0) or 0),
                            "precio": _precio_def, "costo": _costo_def})
    else:
        st.info("🔎 " + T("Como recién empiezas, te daré un estimado del sector (rango amplio y honesto). "
                          "En cuanto tengas 2-3 meses de ventas reales, el Gemelo se vuelve mucho más preciso.",
                          "Since you're just starting, I'll give a sector estimate (wide, honest range). "
                          "With 2-3 months of real sales it gets far more precise."))
        _c1, _c2 = st.columns(2)
        _precio_def = _c1.number_input(T(f"Precio de lo que vendes ({moneda})", f"Price ({moneda})"),
                                       min_value=0.0, value=30.0, step=1.0, key="gs_precio_nuevo")
        _costo_def = _c2.number_input(T(f"Costo por unidad ({moneda})", f"Cost per unit ({moneda})"),
                                      min_value=0.0, value=12.0, step=1.0, key="gs_costo_nuevo")

    hay_datos = G.datos_suficientes(semanas, minimo=2)
    _vv = [s["ventas"] for s in semanas if s["ventas"] > 0]
    _ventas_base = round(min(_vv) * 0.5, 0) if (hay_datos and _vv) else 0.0
    _gasto_hist = max((sum(s["gasto"].values()) for s in semanas), default=0.0) if semanas else 0.0

    # ── 3. El dato de la pregunta elegida ────────────────────────────────────
    st.markdown("##### 3. " + T("Un último dato", "One last thing"))
    _intensidad, _precio_nuevo, _precio_act = 1.0, 0.0, 0.0
    if _pregunta in ("presupuesto", "campana"):
        _lbl = (T(f"¿Cuánto piensas invertir en ads el próximo mes? ({moneda})", f"Ad budget next month ({moneda})")
                if _pregunta == "presupuesto"
                else T(f"Presupuesto TOTAL de la campaña ({moneda})", f"TOTAL campaign budget ({moneda})"))
        _default_inv = float(round(_gasto_hist)) or (1000.0 if _pregunta == "campana" else 300.0)
        _inv = st.number_input(_lbl, min_value=0.0, value=_default_inv, step=50.0, key="gs_inv")
        if _pregunta == "campana":
            _intensidad = st.slider(T("¿Qué tan fuerte esperas la campaña?", "How strong do you expect it?"),
                                    0.5, 1.5, 1.0, step=0.1, key="gs_int",
                                    help=T("1.0 = campaña típica · 1.3 = más fuerte", "1.0 = typical · 1.3 = stronger"))
    else:  # precio
        _c1, _c2 = st.columns(2)
        _precio_act = _c1.number_input(T(f"Precio actual ({moneda})", f"Current price ({moneda})"),
                                       min_value=0.0, value=float(_precio_def or 20.0), step=1.0, key="gs_pact")
        _precio_nuevo = _c2.number_input(T(f"Precio nuevo ({moneda})", f"New price ({moneda})"),
                                         min_value=0.0, value=float((_precio_def or 20.0) * 1.1), step=1.0, key="gs_pnew")
        _inv = float(_gasto_hist or 300)

    if st.button("🔮 " + T("Calcular", "Calculate"), key="gs_calcular",
                 use_container_width=True, type="primary"):
        _precio = _precio_nuevo if _pregunta == "precio" else (_precio_def or 1.0)

        def _params():
            if hay_datos:
                p = G.calibrar(semanas, _sector, ventas_base=_ventas_base)
                if not p.get("precio_ref"):
                    p["precio_ref"] = _precio
                return p
            _g = _inv or 300
            return G.params_benchmark(_sector, _precio_def or 20,
                                      {c: _g / 3.0 for c in G.CANALES}, ventas_base=0.0)

        if _pregunta == "presupuesto":
            res = G.sim_presupuesto(_params(), _inv, _precio, costo=_costo_def)
        elif _pregunta == "campana":
            res = G.sim_campana(_params(), _inv, _precio, costo=_costo_def, intensidad=_intensidad)
        else:
            _plan = {c: _inv / 3.0 for c in G.CANALES}
            res = G.sim_precio(_params(), _precio_act, _precio_nuevo, _plan, costo=_costo_def)

        # Datos en MESES → la proyección interna (semanal) no aplica: la ocultamos.
        res.pop("proyeccion", None)
        res.update({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "semana": datetime.now().strftime("%b %Y"), "moneda": moneda,
                    "sector": _sector, "precio": _precio, "costo": _costo_def, "periodo": "mes"})
        res["explicacion"] = _explicar_ia(generar_texto, res, marca, moneda, T) if generar_texto else ""
        st.session_state["gemelo_resultado"] = res
        st.session_state.pop("gemelo_personas", None)
        # Guarda los meses (convertidos al formato del motor) para no perderlos.
        if _situacion == "tengo" and _df is not None and semanas:
            try:
                _dfsave = pd.DataFrame([
                    {"Semana": str(r.get("Mes", f"Mes {i + 1}")),
                     "Gasto Meta": float(r.get("Inversión en ads", 0) or 0) / 3.0,
                     "Gasto Google": float(r.get("Inversión en ads", 0) or 0) / 3.0,
                     "Gasto TikTok": float(r.get("Inversión en ads", 0) or 0) / 3.0,
                     "Ventas": float(r.get("Ventas", 0) or 0),
                     "Precio": _precio_def, "Costo": _costo_def, "Campaña": False}
                    for i, r in _df.iterrows()])
                _guardar_datos(supabase, user_email, _dfsave, log)
            except Exception:
                log("gs_guardar_datos")
        _guardar_simulacion(supabase, user_email, res, log)

    # ── Resultado AQUÍ MISMO (misma pantalla, sin saltar pestañas) ───────────
    if st.session_state.get("gemelo_resultado"):
        st.divider()
        try:
            _tab_resultado(marca, moneda, T, generar_texto)
        except Exception as _e:
            log("gemelo_render")
            st.error(T("No pude mostrar el resultado. Comparte este detalle con tu equipo: ",
                       "Couldn't show the result. Share this detail: ") + f"`{type(_e).__name__}: {_e}`")


def _render_simple_zona(supabase, generar_texto, user_email, marca, moneda, T, log):
    """Pregunta de zona/distrito en modo simple. Estimado por supuestos
    (mercado × penetración); honesto: no usa datos reales de la calle."""
    st.markdown("##### 2. " + T("Datos de la zona", "Area details"))
    st.info("📍 " + T("Es un estimado por supuestos: tamaño del mercado × % que esperas captar. "
                      "Hoy NO usa datos reales de tráfico de la calle (eso sería un módulo aparte). "
                      "Igual te sirve para decidir si una zona conviene y comparar entre varias.",
                      "An assumption-based estimate: market size × % you expect to capture. "
                      "It does NOT use real street-traffic data yet. Still useful to judge and compare areas."))
    _distrito = st.text_input(T("¿Qué zona o distrito?", "Which area/district?"), key="gsz_distrito")
    _c1, _c2 = st.columns(2)
    _precio = _c1.number_input(T(f"Precio de lo que vendes ({moneda})", f"Price ({moneda})"),
                               min_value=0.0, value=25.0, step=1.0, key="gsz_precio")
    _costo = _c2.number_input(T(f"Costo por unidad ({moneda})", f"Cost per unit ({moneda})"),
                              min_value=0.0, value=10.0, step=1.0, key="gsz_costo")
    _clientes = st.number_input(
        T("¿Cuántos clientes potenciales hay en la zona? (estimado)", "Potential customers in the area? (estimate)"),
        min_value=0.0, value=8000.0, step=500.0, key="gsz_cli",
        help=T("Si no sabes el número exacto, pon un estimado del tamaño del mercado de esa zona.",
               "If you don't know the exact number, estimate the market size of that area."))
    _pen = st.slider(
        T("De cada 100 clientes posibles, ¿cuántos crees que te comprarán? (%)",
          "Of every 100 possible customers, how many do you think will buy? (%)"),
        0.0, 20.0, 3.0, step=0.5, key="gsz_pen",
        help=T("Es tu % de captación. Ejemplo: 3 = de cada 100 personas de la zona, 3 te compran. "
               "Para un negocio nuevo lo normal es entre 1% y 5%.",
               "Your capture rate. Example: 3 = of every 100 people, 3 buy from you. New business: usually 1%-5%."))
    _inv = st.number_input(T(f"Inversión mensual para operar ahí ({moneda})", f"Monthly investment to operate there ({moneda})"),
                           min_value=0.0, value=1500.0, step=100.0, key="gsz_inv")

    if st.button("🔮 " + T("Calcular", "Calculate"), key="gsz_calcular",
                 use_container_width=True, type="primary"):
        if _precio <= 0:
            st.error(T("Pon un precio mayor que 0.", "Enter a price greater than 0."))
        else:
            res = G.sim_zona(_precio, _costo, _inv, _clientes, _pen)
            res.pop("proyeccion", None)
            res.update({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "semana": datetime.now().strftime("%b %Y"), "moneda": moneda,
                        "distrito": _distrito, "precio": _precio, "costo": _costo, "periodo": "mes"})
            res["explicacion"] = _explicar_ia(generar_texto, res, marca, moneda, T) if generar_texto else ""
            st.session_state["gemelo_resultado"] = res
            st.session_state.pop("gemelo_personas", None)
            _guardar_simulacion(supabase, user_email, res, log)

    if st.session_state.get("gemelo_resultado"):
        st.divider()
        try:
            _tab_resultado(marca, moneda, T, generar_texto)
        except Exception as _e:
            log("gemelo_render")
            st.error(T("No pude mostrar el resultado. Comparte este detalle con tu equipo: ",
                       "Couldn't show the result. Share this detail: ") + f"`{type(_e).__name__}: {_e}`")


def _registrar_venta_real(supabase, email, sim_id, venta, log):
    """Guarda la venta real de una predicción pasada, para medir la precisión."""
    if not supabase or sim_id is None:
        return False
    try:
        supabase.table("gemelo_simulaciones").update(
            {"ventas_reales_posterior": float(venta)}).eq("id", sim_id).eq("user_id", email).execute()
        return True
    except Exception:
        log("registrar_venta_real")
        return False


def _panel_precision(supabase, user_email, moneda, T, log):
    """Precisión acumulada del Gemelo (predicho vs. real) + registro de ventas
    reales de predicciones de mes/campaña pasadas. Es la feature de confianza:
    "el mes pasado predije X, vendiste Y, acerté Z%"."""
    filas = _cargar_simulaciones(supabase, user_email, log)
    if not filas:
        return
    _precisiones, _pendientes = [], []
    for f in filas:
        try:
            _par = f.get("parametros_json")
            _par = json.loads(_par) if isinstance(_par, str) else (_par or {})
            if _par.get("tipo", "") not in ("presupuesto", "campana"):
                continue  # solo una predicción de ventas de un periodo es verificable
            _res = f.get("resultado_json")
            _res = json.loads(_res) if isinstance(_res, str) else (_res or {})
            _v = _res.get("ventas", {})
            _real = f.get("ventas_reales_posterior")
            if _real is not None:
                _precisiones.append(G.precision(_v.get("p10", 0), _v.get("p90", 0), _real))
            else:
                _pendientes.append((f.get("id"), f.get("fecha_sim", ""),
                                    float(_v.get("p10", 0) or 0), float(_v.get("p90", 0) or 0)))
        except Exception:
            log("panel_precision_fila")

    if _precisiones:
        _avg = sum(_precisiones) / len(_precisiones)
        st.success("📈 " + T(
            f"**Precisión del Gemelo: {_avg:.0f}%** — de {len(_precisiones)} predicción(es) que ya comparaste con tus ventas reales.",
            f"**Twin accuracy: {_avg:.0f}%** — from {len(_precisiones)} prediction(s) you compared with real sales."))
    elif _pendientes:
        st.info("📈 " + T("Registra tus ventas reales (abajo) para empezar a medir qué tan preciso es tu Gemelo.",
                          "Log your real sales (below) to start measuring your Twin's accuracy."))

    if _pendientes:
        with st.expander("✅ " + T(f"Registrar mis ventas reales ({len(_pendientes)} pendiente(s))",
                                   f"Log my real sales ({len(_pendientes)} pending)")):
            st.caption(T("Cuando termine el periodo, pon cuánto vendiste de verdad. Así el Gemelo mide su precisión.",
                         "When the period ends, enter what you really sold. That's how the Twin measures its accuracy."))
            for _id, _fecha, _p10, _p90 in _pendientes[:8]:
                _ca, _cb, _cc = st.columns([3, 2, 1])
                _ca.markdown(T(f"**{_fecha}** · predije {_p10:.0f}–{_p90:.0f}",
                               f"**{_fecha}** · predicted {_p10:.0f}–{_p90:.0f}"))
                _vr = _cb.number_input(T("Venta real", "Real sales"), min_value=0.0, value=0.0,
                                       step=10.0, key=f"vr_{_id}", label_visibility="collapsed")
                if _cc.button(T("Guardar", "Save"), key=f"vrbtn_{_id}"):
                    if _vr > 0 and _registrar_venta_real(supabase, user_email, _id, _vr, log):
                        st.rerun()
                    else:
                        st.warning(T("Pon una venta real mayor que 0.", "Enter real sales > 0."))


# ──────────────────────────────────────────────────────────────────────────
def _semanas_desde_editor(df):
    """Convierte el DataFrame del editor en la lista de semanas del motor."""
    semanas = []
    for _, row in df.iterrows():
        semanas.append({
            "gasto": {"Meta": float(row.get("Gasto Meta", 0) or 0),
                      "Google": float(row.get("Gasto Google", 0) or 0),
                      "TikTok": float(row.get("Gasto TikTok", 0) or 0)},
            "ventas": float(row.get("Ventas", 0) or 0),
            "precio": float(row.get("Precio", 0) or 0),
            "costo": float(row.get("Costo", 0) or 0),
            # Marca de campaña (Cyber, Black, Navidad...): aparta los picos para
            # que el Gemelo aprenda cuánto suben vs. un mes normal.
            "campana": bool(row.get("Campaña", False)),
        })
    return semanas


def _tab_datos(supabase, user_email, moneda, T, log):
    import pandas as pd

    st.write(T(f"Ingresa tus últimas semanas (gasto en {moneda}). Con 4+ semanas el Gemelo se calibra con TUS datos.",
               f"Enter your recent weeks (spend in {moneda}). With 4+ weeks the Twin calibrates on YOUR data."))
    st.caption("🔥 " + T("Marca la casilla **Campaña** en las semanas de Cyber, Black, Navidad, Día de la Madre, etc. "
                         "Así el Gemelo aprende cuánto suben tus ventas en campaña y puede proyectar las próximas.",
                         "Tick the **Campaign** box on Cyber, Black, Xmas, Mother's Day weeks, etc. "
                         "The Twin then learns your campaign uplift and can project upcoming ones."))

    # Carga previa (sesión o Supabase)
    _key = "gemelo_df"
    if _key not in st.session_state:
        _filas = _cargar_datos(supabase, user_email, log)
        if not _filas:
            _filas = [{"Semana": f"S{i}", "Gasto Meta": 0.0, "Gasto Google": 0.0,
                       "Gasto TikTok": 0.0, "Ventas": 0.0, "Precio": 0.0, "Costo": 0.0,
                       "Campaña": False}
                      for i in range(1, 5)]
        st.session_state[_key] = pd.DataFrame(_filas)
    # Compatibilidad: datos viejos sin la columna Campaña
    if "Campaña" not in st.session_state[_key].columns:
        st.session_state[_key]["Campaña"] = False

    df = st.data_editor(st.session_state[_key], num_rows="dynamic", use_container_width=True,
                        key="gemelo_editor",
                        column_config={"Campaña": st.column_config.CheckboxColumn(
                            T("Campaña", "Campaign"),
                            help=T("Semana de campaña fuerte (Cyber, Black, Navidad...)",
                                   "Strong campaign week (Cyber, Black, Xmas...)"))})

    _c1, _c2 = st.columns(2)
    with _c1:
        if st.button("💾 " + T("Guardar mis datos", "Save my data"), key="gemelo_guardar", use_container_width=True):
            semanas = _semanas_desde_editor(df)
            ok, errs = G.validar_semanas(semanas)
            if not ok:
                st.error(T("Revisa estos datos:", "Check these values:") + "\n\n- " + "\n- ".join(errs[:8]))
            else:
                st.session_state[_key] = df
                st.session_state["gemelo_semanas"] = semanas
                _guardar_datos(supabase, user_email, df, log)
                _n = len(semanas)
                if G.datos_suficientes(semanas):
                    st.success(T(f"✅ Guardado. {_n} semanas — el Gemelo usará TUS datos reales.",
                                 f"✅ Saved. {_n} weeks — the Twin will use YOUR real data."))
                else:
                    st.info(T(f"Guardado ({_n} semanas). Con 4+ semanas útiles pasamos de benchmark a tus datos reales.",
                              f"Saved ({_n} weeks). With 4+ useful weeks we switch from benchmark to your real data."))
    with _c2:
        if st.button("🔄 " + T("Recargar guardados", "Reload saved"), key="gemelo_recargar", use_container_width=True):
            st.session_state.pop(_key, None)
            st.rerun()


_DECISIONES = {
    "presupuesto": ("💰 ¿Cuánto invertir en ads y cómo repartir?", "💰 How much to spend on ads & how to split?"),
    "campana":     ("🔥 ¿Cuánto venderé en campaña (Cyber, Black, Navidad)?", "🔥 How much will I sell on a campaign (Cyber, Black, Xmas)?"),
    "precio":      ("🏷 ¿Subo o bajo el precio?", "🏷 Should I raise or lower the price?"),
    "producto":    ("🚀 ¿Lanzo un producto nuevo?", "🚀 Should I launch a new product?"),
    "zona":        ("📍 ¿Abro en otra zona?", "📍 Should I open in another area?"),
    "zonas_mapa":  ("🗺 Comparar zonas (mapa de efectividad)", "🗺 Compare areas (effectiveness map)"),
}


def _tab_simular(supabase, generar_texto, user_email, marca, sector_nicho, moneda, T, log):
    semanas = st.session_state.get("gemelo_semanas") or []
    hay_datos = G.datos_suficientes(semanas)

    _sector = st.selectbox(T("Tu sector:", "Your sector:"), list(_SECTORES_LBL.keys()),
                           format_func=lambda k: _SECTORES_LBL[k], key="gemelo_sector")

    # Ubicación (distrito obligatorio para zona — bug #3 de Decisia: nada de "Lima" genérico)
    _cu1, _cu2 = st.columns(2)
    with _cu1:
        ciudad = st.text_input(T("Ciudad", "City"), key="gemelo_ciudad",
                               value=st.session_state.get("ciudad_guardada", ""))
    with _cu2:
        distrito = st.text_input(T("Distrito / zona", "District / area"), key="gemelo_distrito")

    # Qué decisión quiere simular
    _tipo = st.selectbox(T("¿Qué decisión quieres simular?", "Which decision do you want to simulate?"),
                         list(_DECISIONES.keys()),
                         format_func=lambda k: _DECISIONES[k][1 if _en_lang() else 0],
                         key="gemelo_tipo_decision")

    if _tipo in ("presupuesto", "precio", "campana"):
        if hay_datos:
            st.success(T("✅ Gemelo calibrado con tus datos reales.", "✅ Twin calibrated on your real data."))
        else:
            st.warning(T("⚠ Sin 4+ semanas de datos usaré benchmarks del sector (menos preciso).",
                         "⚠ Without 4+ weeks of data I'll use sector benchmarks (less precise)."))

    # Precio y costo sugeridos desde los datos
    _precio_def = _costo_def = 0.0
    if semanas:
        _ps = [s["precio"] for s in semanas if s["precio"] > 0]
        _cs = [s["costo"] for s in semanas if s["costo"] > 0]
        _precio_def = round(sum(_ps) / len(_ps), 2) if _ps else 0.0
        _costo_def = round(sum(_cs) / len(_cs), 2) if _cs else 0.0
    _gasto_hist = max((sum(s["gasto"].values()) for s in semanas), default=0.0) if semanas else 0.0

    # ── Inputs según el tipo de decisión ────────────────────────────────────
    datos = {"precio": _precio_def, "costo": _costo_def}

    # Piso de ventas base: lo que vendes aunque NO hagas ads (negocio establecido).
    # Para negocio nuevo, dejar en 0 → los ads mueven todo.
    if _tipo in ("presupuesto", "precio", "campana"):
        _base_def = 0.0
        if semanas:
            _vv = [s["ventas"] for s in semanas if s["ventas"] > 0]
            _base_def = round(min(_vv) * 0.5, 0) if _vv else 0.0
        datos["ventas_base"] = st.number_input(
            T(f"¿Cuánto vendes por semana SIN hacer publicidad? (piso base, en {moneda} o unidades)",
              f"How much do you sell per week WITHOUT ads? (baseline)"),
            min_value=0.0, value=float(_base_def), step=10.0, key="g_ventas_base",
            help=T("Negocio nuevo: déjalo en 0. Negocio con marca/tráfico propio: pon lo que vendes igual.",
                   "New business: leave 0. Established brand/traffic: put what you sell anyway."))

    if _tipo == "presupuesto":
        _tope = max(int(_gasto_hist * 3), 1000)
        datos["presupuesto"] = st.slider(T(f"Presupuesto semanal ({moneda})", f"Weekly budget ({moneda})"),
                                         0, _tope, min(int(_gasto_hist) or 300, _tope),
                                         step=max(_tope // 100, 10), key="g_presup")
    elif _tipo == "campana":
        # Muestra el multiplicador que el Gemelo ya conoce (datos propios o benchmark)
        _mult_info = ""
        if semanas:
            _pprev = (G.calibrar(semanas, _sector, ventas_base=float(datos.get("ventas_base", 0) or 0))
                      if hay_datos else G.params_benchmark(_sector, _precio_def or 20, {c: 100 for c in G.CANALES}))
            _camp = _pprev.get("campana", {})
            if _camp.get("fuente") == "datos":
                st.success(T(f"📈 Según TUS campañas marcadas, vendes ~**{_camp['multiplicador']:.1f}x** más que un mes normal "
                             f"({_camp.get('n', 0)} campaña(s) en tus datos).",
                             f"📈 Per YOUR tagged campaigns, you sell ~**{_camp['multiplicador']:.1f}x** a normal month "
                             f"({_camp.get('n', 0)} campaign(s) in your data)."))
            else:
                st.info(T(f"🔎 Aún no marcaste campañas en tus datos → uso un estimado del sector (~**{_camp.get('multiplicador', 1.8):.1f}x**). "
                          "Marca tus semanas de Cyber/Black en 📥 Mis datos para que aprenda TU número.",
                          f"🔎 No campaigns tagged yet → using a sector estimate (~**{_camp.get('multiplicador', 1.8):.1f}x**). "
                          "Tag your Cyber/Black weeks in 📥 My data so it learns YOUR number."))
        _tope = max(int(_gasto_hist * 5), 2000)
        datos["presupuesto"] = st.slider(
            T(f"Presupuesto TOTAL de la campaña ({moneda})", f"TOTAL campaign budget ({moneda})"),
            0, _tope, min(int(_gasto_hist * 2) or 1000, _tope),
            step=max(_tope // 100, 50), key="g_camp_presup",
            help=T("Suma todo lo que invertirás en la campaña (ej. Cyber Wow + Black Week).",
                   "Sum everything you'll invest in the campaign."))
        datos["intensidad"] = st.slider(
            T("¿Qué tan fuerte esperas esta campaña?", "How strong do you expect this campaign?"),
            0.5, 1.5, 1.0, step=0.1, key="g_camp_int",
            help=T("1.0 = como tus campañas típicas · 1.3 = esperas que pegue más fuerte · 0.7 = más floja.",
                   "1.0 = like your typical campaigns · 1.3 = expect stronger · 0.7 = weaker."))
    elif _tipo == "precio":
        _c1, _c2 = st.columns(2)
        datos["precio_actual"] = _c1.number_input(T(f"Precio actual ({moneda})", f"Current price ({moneda})"),
                                                   0.0, value=float(_precio_def or 20.0), step=1.0, key="g_pact")
        datos["precio_nuevo"] = _c2.number_input(T(f"Precio nuevo ({moneda})", f"New price ({moneda})"),
                                                 0.0, value=float((_precio_def or 20.0) * 1.1), step=1.0, key="g_pnew")
        datos["gasto"] = float(_gasto_hist or 300)
    elif _tipo == "producto":
        st.info(T("Producto nuevo = sin historial → estimación por supuestos (marca el rango).",
                  "New product = no history → assumption-based estimate (shows the range)."))
        _c1, _c2 = st.columns(2)
        datos["precio"] = _c1.number_input(T(f"Precio del producto ({moneda})", f"Product price ({moneda})"),
                                           0.0, value=float(_precio_def or 30.0), step=1.0, key="g_prod_precio")
        datos["costo"] = _c2.number_input(T(f"Costo del producto ({moneda})", f"Product cost ({moneda})"),
                                          0.0, value=float(_costo_def or 12.0), step=1.0, key="g_prod_costo")
        datos["demanda"] = st.number_input(T("¿Cuántas unidades esperas vender por semana?",
                                             "How many units do you expect to sell per week?"),
                                           0.0, value=30.0, step=5.0, key="g_prod_dem")
        datos["gasto_mkt"] = st.number_input(T(f"Inversión en marketing semanal ({moneda})",
                                               f"Weekly marketing spend ({moneda})"),
                                             0.0, value=float(_gasto_hist or 300), step=50.0, key="g_prod_mkt")
    elif _tipo == "zona":
        st.info(T("Zona nueva = estimación por supuestos (tamaño del mercado × penetración esperada).",
                  "New area = assumption-based estimate (market size × expected penetration)."))
        _c1, _c2 = st.columns(2)
        datos["precio"] = _c1.number_input(T(f"Precio ({moneda})", f"Price ({moneda})"),
                                           0.0, value=float(_precio_def or 25.0), step=1.0, key="g_zona_precio")
        datos["costo"] = _c2.number_input(T(f"Costo ({moneda})", f"Cost ({moneda})"),
                                          0.0, value=float(_costo_def or 10.0), step=1.0, key="g_zona_costo")
        datos["clientes"] = st.number_input(T("Clientes potenciales en la zona", "Potential customers in the area"),
                                            0.0, value=8000.0, step=500.0, key="g_zona_cli")
        datos["penetracion"] = st.slider(T("% que esperas captar", "% you expect to reach"),
                                         0.0, 20.0, 3.0, step=0.5, key="g_zona_pen")
        datos["inversion"] = st.number_input(T(f"Inversión para abrir ({moneda}/sem)", f"Opening investment ({moneda}/wk)"),
                                             0.0, value=float(_gasto_hist or 500), step=100.0, key="g_zona_inv")
    elif _tipo == "zonas_mapa":
        import pandas as pd
        st.info(T("Compara varias zonas/distritos. Te las pinto 🟢🟡🔴 por rentabilidad esperada.",
                  "Compare several areas/districts. I'll color them 🟢🟡🔴 by expected profit."))
        _c1, _c2 = st.columns(2)
        datos["precio"] = _c1.number_input(T(f"Precio ({moneda})", f"Price ({moneda})"),
                                           0.0, value=float(_precio_def or 25.0), step=1.0, key="g_map_precio")
        datos["costo"] = _c2.number_input(T(f"Costo ({moneda})", f"Cost ({moneda})"),
                                          0.0, value=float(_costo_def or 10.0), step=1.0, key="g_map_costo")
        _zkey = "gemelo_zonas_df"
        if _zkey not in st.session_state:
            st.session_state[_zkey] = pd.DataFrame([
                {"Zona": "Zona A", "Clientes potenciales": 9000.0, "Penetración %": 4.0, "Inversión": 1500.0},
                {"Zona": "Zona B", "Clientes potenciales": 15000.0, "Penetración %": 1.5, "Inversión": 1200.0},
                {"Zona": "Zona C", "Clientes potenciales": 7000.0, "Penetración %": 5.0, "Inversión": 1800.0},
            ])
        datos["zonas_df"] = st.data_editor(st.session_state[_zkey], num_rows="dynamic",
                                           use_container_width=True, key="gemelo_zonas_editor")

    if st.button("🔮 " + T("Simular", "Simulate"), key="gemelo_simular_btn", use_container_width=True):
        _ejecutar_simulacion(_tipo, datos, semanas, hay_datos, _sector, moneda, ciudad, distrito,
                             marca, supabase, generar_texto, user_email, T, log)


def _en_lang():
    return st.session_state.get("lang") == "en"


def _ejecutar_simulacion(tipo, datos, semanas, hay_datos, sector, moneda, ciudad, distrito,
                         marca, supabase, generar_texto, user_email, T, log):
    """Enruta al tipo de decisión, arma el resultado estándar y lo guarda."""
    precio = float(datos.get("precio", 0) or 0)
    costo = float(datos.get("costo", 0) or 0)
    if tipo in ("presupuesto", "precio", "campana") and precio <= 0:
        st.error(T("Ingresa un precio mayor que 0.", "Enter a price greater than 0."))
        return

    # Mapa de efectividad por zona: formato propio (no pasa por _empacar)
    if tipo == "zonas_mapa":
        _zonas = []
        _df = datos.get("zonas_df")
        if _df is not None:
            for _, _row in _df.iterrows():
                _zonas.append({"nombre": _row.get("Zona", ""),
                               "clientes": _row.get("Clientes potenciales", 0),
                               "penetracion": _row.get("Penetración %", 0),
                               "inversion": _row.get("Inversión", 0)})
        _mapa = G.mapa_zonas(_zonas, precio, costo)
        if not _mapa["zonas"]:
            st.error(T("Agrega al menos una zona con clientes potenciales > 0.",
                       "Add at least one area with potential customers > 0."))
            return
        _mapa.update({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                      "semana": datetime.now().strftime("%W (%Y)"),
                      "moneda": moneda, "sector": sector, "ciudad": ciudad})
        st.session_state["gemelo_resultado"] = _mapa
        st.session_state.pop("gemelo_personas", None)
        st.success(T("Listo. Mira la pestaña 📊 Resultado.", "Done. See the 📊 Result tab."))
        return

    # Parámetros (curvas) solo para presupuesto y precio
    _ventas_base = float(datos.get("ventas_base", 0) or 0)

    def _params():
        if hay_datos:
            p = G.calibrar(semanas, sector, ventas_base=_ventas_base)
            if not p.get("precio_ref"):
                p["precio_ref"] = precio or datos.get("precio_actual", 0)
            return p
        _g = datos.get("presupuesto") or datos.get("gasto") or 300
        return G.params_benchmark(sector, precio or datos.get("precio_actual", 20),
                                  {c: _g / 3.0 for c in G.CANALES}, ventas_base=_ventas_base)

    if tipo == "presupuesto":
        res = G.sim_presupuesto(_params(), datos["presupuesto"], precio, costo=costo)
    elif tipo == "campana":
        res = G.sim_campana(_params(), datos["presupuesto"], precio, costo=costo,
                            intensidad=float(datos.get("intensidad", 1.0) or 1.0))
    elif tipo == "precio":
        plan = {c: datos["gasto"] / 3.0 for c in G.CANALES}
        res = G.sim_precio(_params(), datos["precio_actual"], datos["precio_nuevo"], plan, costo=costo)
    elif tipo == "producto":
        res = G.sim_producto_nuevo(precio, costo, datos["gasto_mkt"], datos["demanda"])
    else:  # zona
        res = G.sim_zona(precio, costo, datos["inversion"], datos["clientes"], datos["penetracion"])

    res.update({
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "semana": datetime.now().strftime("%W (%Y)"),
        "moneda": moneda, "ciudad": ciudad, "distrito": distrito, "sector": sector,
        "precio": precio or datos.get("precio_nuevo", 0), "costo": costo,
    })
    res["explicacion"] = _explicar_ia(generar_texto, res, marca, moneda, T) if generar_texto else ""
    st.session_state["gemelo_resultado"] = res
    st.session_state.pop("gemelo_personas", None)  # opiniones viejas no aplican a esta sim
    _guardar_simulacion(supabase, user_email, res, log)
    st.success(T("Listo. Mira la pestaña 📊 Resultado.", "Done. See the 📊 Result tab."))


def _render_mapa_zonas(r, moneda, T):
    """Mapa de efectividad por zona: ranking 🟢🟡🔴 + gráfico de utilidad."""
    zs = r.get("zonas", [])
    st.markdown("### 🗺 " + T("Mapa de efectividad por zona", "Area effectiveness map"))
    if r.get("mejor"):
        st.success(T(f"🏆 Mejor zona para empezar: **{r['mejor']}**",
                     f"🏆 Best area to start: **{r['mejor']}**"))
    st.caption("⚠ " + T("Estimación por supuestos (clientes × penetración) — rango amplio a propósito.",
                        "Assumption-based estimate (customers × penetration) — wide range on purpose."))

    for z in zs:
        with st.container(border=True):
            _c1, _c2, _c3 = st.columns([3, 2, 2])
            _c1.markdown(f"### {z['icono']} {z['nombre']}")
            _c2.metric(T("Utilidad est.", "Est. profit"), f"{moneda}{z['utilidad_p50']:,.0f}")
            _c3.metric("ROI", "—" if z.get("roi") is None else f"{z['roi']}x")
            st.caption(f"{T('Ventas', 'Sales')} ≈ {z['ventas_p50']:.0f} · "
                       f"{T('Clientes', 'Customers')} {z['clientes']:.0f} · "
                       f"{T('Penetración', 'Penetration')} {z['penetracion']}% · "
                       f"{T('Inversión', 'Investment')} {moneda}{z['inversion']:.0f}")

    try:
        import plotly.graph_objects as go
        fig = go.Figure(go.Bar(
            x=[z["nombre"] for z in zs], y=[z["utilidad_p50"] for z in zs],
            marker_color=[z["color"] for z in zs],
            text=[f"{moneda}{z['utilidad_p50']:,.0f}" for z in zs], textposition="outside",
        ))
        fig.update_layout(height=320, yaxis_title=T("Utilidad estimada", "Estimated profit"),
                          showlegend=False, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        pass
    st.caption(T("🟢 conviene · 🟡 con cuidado · 🔴 pierde", "🟢 go · 🟡 careful · 🔴 loses"))


def _tab_resultado(marca, moneda, T, generar_texto=None):
    r = st.session_state.get("gemelo_resultado")
    if not r:
        st.info(T("Aún no has simulado. Ve a la pestaña 🎛 Simular.", "No simulation yet. Go to the 🎛 Simulate tab."))
        return

    # ── Mapa de efectividad por zona (formato propio) ───────────────────────
    if r.get("tipo") == "zonas_mapa":
        _render_mapa_zonas(r, moneda, T)
        return

    v = r["ventas"]

    # ── Veredicto del árbitro (se deriva de los números → nunca contradice) ──
    _ver = r.get("veredicto")
    if _ver:
        _colores = {"hazlo": "#16A34A", "cuidado": "#D97706", "no": "#DC2626"}
        _col = _colores.get(_ver["nivel"], "#7C3AED")
        _roas_txt = (f" · ROAS {_ver['roas']}x" if _ver.get("roas") else "")
        st.markdown(
            f"""<div style="border:2px solid {_col};border-radius:14px;padding:14px 16px;margin-bottom:14px;">
            <div style="font-size:1.35rem;font-weight:800;color:{_col};">{_ver['icono']} {_ver['titulo']}{_roas_txt}</div>
            <div style="color:inherit;opacity:.85;margin-top:2px;">{_ver['razon']}</div></div>""",
            unsafe_allow_html=True,
        )

    _es_camp = r.get("tipo") == "campana"
    if _es_camp:
        _titulo_pred = T("Predicción de la campaña", "Campaign prediction")
    elif r.get("periodo") == "mes":
        _titulo_pred = T("Predicción del próximo mes", "Next month prediction")
    else:
        _titulo_pred = T("Predicción de esta semana", "This week prediction")
    st.markdown("### " + _titulo_pred)
    _p10, _p50, _p90 = _num(v.get("p10")), _num(v.get("p50")), _num(v.get("p90"))
    _ing = _num((r.get("ingresos") or {}).get("p50"))
    _uti = _num((r.get("utilidad") or {}).get("p50"))
    _c1, _c2, _c3 = st.columns(3)
    _c1.metric(T("Pesimista", "Pessimistic"), f"{_p10:.0f}")
    _c2.metric(T("Más probable", "Most likely"), f"{_p50:.0f}", T("ventas", "sales"))
    _c3.metric(T("Optimista", "Optimistic"), f"{_p90:.0f}")
    st.markdown(f"**{T('Rango de ventas', 'Sales range')}: {_p10:.0f} – {_p90:.0f}** · "
                f"{T('Ingresos', 'Revenue')} ≈ {moneda}{_ing:.0f} · "
                f"{T('Utilidad', 'Profit')} ≈ {moneda}{_uti:.0f}")
    if r.get("fuente") == "benchmark":
        st.caption("⚠ " + T("Basado en benchmarks del sector (sin tus datos aún).",
                             "Based on sector benchmarks (no data from you yet)."))
    elif r.get("fuente") == "supuestos":
        st.caption("⚠ " + T("Estimación por supuestos (sin historial) — rango amplio a propósito.",
                             "Assumption-based estimate (no history) — range is wide on purpose."))
    if _es_camp:
        _mf = r.get("mult_fuente", "benchmark")
        _origen = T("tus propias campañas", "your own campaigns") if _mf == "datos" \
            else T("un estimado del sector", "a sector estimate")
        st.caption(f"🔥 " + T(
            f"Modo campaña: multiplica un mes normal por **{r.get('multiplicador', '?')}x** "
            f"(de {_origen}). El rango es ancho porque las campañas son más impredecibles.",
            f"Campaign mode: multiplies a normal month by **{r.get('multiplicador', '?')}x** "
            f"(from {_origen}). The range is wide because campaigns are less predictable."))
        if _mf == "benchmark":
            st.caption("👉 " + T("Marca tus campañas pasadas en 📥 Mis datos para afinar TU multiplicador real.",
                                 "Tag your past campaigns in 📥 My data to sharpen YOUR real multiplier."))
    if r.get("distrito"):
        st.caption("📍 " + f"{r.get('ciudad', '')} · {r['distrito']}".strip(" ·"))

    # Gráfico de escenarios
    try:
        import plotly.graph_objects as go
        fig = go.Figure(go.Bar(
            x=[T("Pesimista", "Pessimistic"), T("Base", "Base"), T("Optimista", "Optimistic")],
            y=[v["p10"], v["p50"], v["p90"]],
            marker_color=["#F97316", "#7C3AED", "#16A34A"],
            text=[f"{v['p10']:.0f}", f"{v['p50']:.0f}", f"{v['p90']:.0f}"], textposition="outside",
        ))
        fig.update_layout(height=320, yaxis_title=T("Ventas", "Sales"), showlegend=False,
                          margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        st.bar_chart({"ventas": [v["p10"], v["p50"], v["p90"]]})

    # Reparto recomendado (solo decisión de presupuesto)
    if r.get("asignacion"):
        st.markdown(f"#### 🎯 {T('Reparto recomendado del presupuesto', 'Recommended budget split')}")
        _cols = st.columns(len(r["asignacion"]))
        for _col, (canal, g) in zip(_cols, r["asignacion"].items()):
            _col.metric(canal, f"{moneda}{g:.0f}")

    # Comparación de precio (solo decisión de precio)
    _comp = r.get("comparacion")
    if _comp:
        def _n(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0.0
        st.markdown(f"#### 🏷 {T('Precio actual vs nuevo', 'Current vs new price')}")
        _pa, _pb = st.columns(2)
        _pa.metric(f"{moneda}{_n(r.get('precio_actual')):.0f} " + T("(actual)", "(current)"),
                   f"{_n(_comp.get('ventas_actual')):.0f} " + T("ventas", "sales"),
                   f"{moneda}{_n(_comp.get('utilidad_actual')):.0f} " + T("utilidad", "profit"))
        _pb.metric(f"{moneda}{_n(r.get('precio_nuevo')):.0f} " + T("(nuevo)", "(new)"),
                   f"{_n(_comp.get('ventas_nueva')):.0f} " + T("ventas", "sales"),
                   f"{moneda}{_n(_comp.get('utilidad_nueva')):.0f}",
                   delta=f"{_n(_comp.get('mejora')):+.0f} " + T("utilidad", "profit"))

    # Proyección 6/12 meses (si mantiene el ritmo)
    _proy = r.get("proyeccion")
    if _proy:
        st.markdown(f"#### 📆 {T('Proyección si mantienes el ritmo', 'Projection if you keep this pace')}")
        _pc1, _pc2 = st.columns(2)
        _pc1.metric(T("Ingresos 6 meses", "Revenue 6 months"), f"{moneda}{_proy['6m']['ingresos']:,.0f}")
        _pc2.metric(T("Ingresos 12 meses", "Revenue 12 months"), f"{moneda}{_proy['12m']['ingresos']:,.0f}")
        st.caption(T("Estimación lineal del caso probable — no es una promesa.",
                     "Linear estimate of the likely case — not a promise."))

    # Explicación IA
    if r.get("explicacion"):
        st.markdown("#### 🧠 " + T("Qué significa", "What it means"))
        st.markdown(r["explicacion"])

    # 👥 Opinión del equipo (agentes-persona, a pedido para no gastar en cada sim)
    if generar_texto:
        st.divider()
        st.markdown("#### 👥 " + T("Qué opina tu equipo", "What your team thinks"))
        _ops = st.session_state.get("gemelo_personas")
        if st.button("🗣 " + T("Pedir opinión (comprador · competidor · mercado)",
                               "Ask the team (buyer · competitor · market)"),
                     key="gemelo_personas_btn", use_container_width=True):
            with st.spinner(T("Consultando a tu equipo...", "Asking your team...")):
                _ops = GP.opiniones_equipo(generar_texto, r, marca, r.get("sector", ""),
                                           moneda, r.get("ciudad", ""), r.get("distrito", ""))
                st.session_state["gemelo_personas"] = _ops
        if _ops:
            _personas_meta = [("comprador", "🛒", T("Comprador", "Buyer")),
                              ("competidor", "⚔️", T("Competidor", "Competitor")),
                              ("mercado", "📊", T("Mercado", "Market"))]
            for _k, _emoji, _lbl in _personas_meta:
                _op = (_ops or {}).get(_k, "")
                if _op:
                    with st.container(border=True):
                        st.markdown(f"**{_emoji} {_lbl}**")
                        st.write(_op)

    # 📲 Tarjeta compartible (gancho viral) — prominente y honesta según veredicto
    st.divider()
    st.markdown("#### 📲 " + T("Comparte tu predicción", "Share your forecast"))
    _en_card = _en_lang()
    png, err = GC.generar_tarjeta(marca, _p10, _p90, r.get("semana", ""),
                                  moneda=moneda, ingresos_p50=_ing,
                                  veredicto=_ver, periodo=r.get("periodo", "semana"), en=_en_card)
    if png:
        _cimg, _cbtn = st.columns([1, 1])
        with _cimg:
            st.image(png, use_container_width=True)
        with _cbtn:
            st.markdown(T("Descárgala y compártela en WhatsApp, Instagram o tus estados. "
                          "Cada vez que la compartes, más gente descubre Tentakl. 🐙",
                          "Download it and share on WhatsApp, Instagram or your stories. "
                          "Every share helps more people discover Tentakl. 🐙"))
            st.download_button("📲 " + T("Descargar para compartir", "Download to share"),
                               data=png, file_name="gemelo_tentakl.png", mime="image/png",
                               key="gemelo_card_dl", use_container_width=True)
            # 🔗 Mensaje listo para pegar CON tu link de referido (invita y gana)
            _ref_link = st.session_state.get("_gemelo_ref_link", "")
            if _ref_link:
                _msg = T("🔮 Mira lo que mi Gemelo Digital predijo para mi negocio. Pruébalo gratis: ",
                         "🔮 Look at what my Digital Twin predicted for my business. Try it free: ") + _ref_link
                st.caption("💬 " + T("Copia este mensaje y pégalo junto con la imagen "
                                     "(si alguien entra por tu link y crea su cuenta, ambos ganan créditos):",
                                     "Copy this message and paste it with the image "
                                     "(if someone joins with your link and signs up, you both get credits):"))
                st.code(_msg, language=None)
    else:
        st.caption(T("No se pudo generar la tarjeta: ", "Could not generate the card: ") + str(err))


def _tab_historial(supabase, user_email, moneda, T, log):
    filas = _cargar_simulaciones(supabase, user_email, log)
    if not filas:
        st.info(T("Aún no hay simulaciones guardadas.", "No saved simulations yet."))
        return
    import pandas as pd

    _rows = []
    _precisiones = []
    for f in filas:
        try:
            res = f.get("resultado_json")
            res = json.loads(res) if isinstance(res, str) else (res or {})
            v = res.get("ventas", {})
            real = f.get("ventas_reales_posterior")
            prec = None
            if real is not None:
                prec = G.precision(v.get("p10", 0), v.get("p90", 0), real)
                _precisiones.append(prec)
            _rows.append({
                T("Fecha", "Date"): f.get("fecha_sim", ""),
                T("Rango predicho", "Predicted range"): f"{v.get('p10', 0):.0f}–{v.get('p90', 0):.0f}",
                T("Venta real", "Actual sales"): "—" if real is None else f"{float(real):.0f}",
                T("Precisión", "Accuracy"): "—" if prec is None else f"{prec:.0f}%",
            })
        except Exception:
            log("historial_fila")
    st.dataframe(_rows, use_container_width=True, hide_index=True)
    if _precisiones:
        st.metric(T("Precisión acumulada", "Cumulative accuracy"),
                  f"{sum(_precisiones) / len(_precisiones):.0f}%")
    else:
        st.caption(T("Registra tus ventas reales para medir la precisión del Gemelo.",
                     "Log your actual sales to measure the Twin's accuracy."))


# ──────────────────────────────────────────────────────────────────────────
# IA (explicación) — recibe números del motor y los traduce a palabras
# ──────────────────────────────────────────────────────────────────────────
_DECISION_TXT = {
    "presupuesto": "cuánto invertir en ads y cómo repartirlo",
    "campana": "cuánto venderás en un periodo de campaña (Cyber, Black, Navidad)",
    "precio": "si subir o bajar el precio",
    "producto": "si lanzar un producto nuevo",
    "zona": "si abrir en otra zona/distrito",
}


def _explicar_ia(generar_texto, r, marca, moneda, T):
    """La IA SOLO explica los números que ya calculó el motor (nunca inventa)."""
    def _n(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return 0.0

    v, ing, ut = r["ventas"], r["ingresos"], r["utilidad"]
    ver = r.get("veredicto", {})
    tipo = r.get("tipo", "presupuesto")
    _extra = ""
    if r.get("asignacion"):
        _extra = "- Reparto recomendado: " + ", ".join(f"{c}: {moneda}{_n(g):.0f}" for c, g in r["asignacion"].items()) + "\n"
    elif r.get("comparacion"):
        _c = r["comparacion"]
        _extra = (f"- Precio actual {moneda}{_n(r.get('precio_actual')):.0f} da utilidad {moneda}{_n(_c.get('utilidad_actual')):.0f}; "
                  f"precio nuevo {moneda}{_n(r.get('precio_nuevo')):.0f} da {moneda}{_n(_c.get('utilidad_nueva')):.0f} "
                  f"(cambio {_n(_c.get('mejora')):+.0f}).\n")
    _zona = (r.get("distrito") or r.get("ciudad") or "").strip()
    if _zona:
        _extra += (f"- Zona/distrito indicado por el usuario: {_zona}. (No tenemos datos reales de esa "
                   "zona; es un estimado por supuestos. NO inventes datos de esa zona, solo nómbrala.)\n")
    # La IA DEBE saber en qué fecha estamos (si no, sugiere campañas que ya pasaron).
    _mes_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
               "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    _hoy = datetime.now()
    _fecha_txt = f"{_hoy.day} de {_mes_es[_hoy.month - 1]} de {_hoy.year}"
    prompt = (
        "Eres un analista de negocio. Explica en español simple, en MÁXIMO 150 palabras, "
        "este resultado de una simulación. NO inventes números ni nombres: usa SOLO estos.\n"
        f"- HOY es {_fecha_txt} (estamos en {_mes_es[_hoy.month - 1]}). Esta es la fecha ACTUAL.\n"
        f"- Marca: {marca}\n"
        f"- Decisión analizada: {_DECISION_TXT.get(tipo, tipo)}\n"
        f"- Veredicto del motor: {ver.get('icono', '')} {ver.get('titulo', '')} ({ver.get('razon', '')})\n"
        f"- Ventas estimadas: entre {v['p10']:.0f} y {v['p90']:.0f} (más probable {v['p50']:.0f})\n"
        f"- Ingresos (probable): {moneda}{ing['p50']:.0f} · Utilidad (probable): {moneda}{ut['p50']:.0f}\n"
        f"{_extra}\n"
        "Formato EXACTO (sin encabezados markdown):\n"
        "1) Una frase que explique el veredicto y el rango en lenguaje de dueño de negocio.\n"
        "2) Una frase con el porqué (qué mueve el resultado).\n"
        "3) UNA acción concreta para los próximos días.\n"
        "REGLA DE FECHA: solo menciona campañas o temporadas que vienen DESPUÉS de hoy "
        "(ej. las próximas según el calendario). NUNCA sugieras aprovechar una fecha o campaña "
        "que YA PASÓ este año. Directo y honesto; si el veredicto es ⚠️ o ❌, dilo claro."
    )
    try:
        out = generar_texto(prompt, max_out=1200, temperatura=0.3)
        return out or ""
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────
# PERSISTENCIA (Supabase) — degrada con elegancia si no hay tablas/cliente
# ──────────────────────────────────────────────────────────────────────────
def _cargar_datos(supabase, email, log):
    if not supabase:
        return []
    try:
        r = supabase.table("gemelo_datos").select("*").eq("user_id", email) \
            .order("fecha").execute()
        filas = []
        for row in (r.data or []):
            filas.append({"Semana": row.get("fecha", ""),
                          "Gasto Meta": float(row.get("gasto_meta", 0) or 0),
                          "Gasto Google": float(row.get("gasto_google", 0) or 0),
                          "Gasto TikTok": float(row.get("gasto_tiktok", 0) or 0),
                          "Ventas": float(row.get("ventas", 0) or 0),
                          "Precio": float(row.get("precio", 0) or 0),
                          "Costo": float(row.get("costo", 0) or 0),
                          "Campaña": bool(row.get("campana", False))})
        return filas
    except Exception:
        log("gemelo_cargar_datos")
        return []


def _guardar_datos(supabase, email, df, log):
    if not supabase:
        return
    try:
        payload = []
        for _, row in df.iterrows():
            payload.append({"user_id": email, "fecha": str(row.get("Semana", "")),
                            "gasto_meta": float(row.get("Gasto Meta", 0) or 0),
                            "gasto_google": float(row.get("Gasto Google", 0) or 0),
                            "gasto_tiktok": float(row.get("Gasto TikTok", 0) or 0),
                            "ventas": float(row.get("Ventas", 0) or 0),
                            "precio": float(row.get("Precio", 0) or 0),
                            "costo": float(row.get("Costo", 0) or 0),
                            "campana": bool(row.get("Campaña", False))})
        supabase.table("gemelo_datos").delete().eq("user_id", email).execute()
        if payload:
            try:
                supabase.table("gemelo_datos").insert(payload).execute()
            except Exception:
                # BD sin la columna 'campana' (tabla vieja): reintenta sin ella
                log("gemelo_guardar_datos_sin_campana")
                for p in payload:
                    p.pop("campana", None)
                supabase.table("gemelo_datos").insert(payload).execute()
    except Exception:
        log("gemelo_guardar_datos")


def _guardar_simulacion(supabase, email, resultado, log):
    if not supabase:
        return
    try:
        supabase.table("gemelo_simulaciones").insert({
            "user_id": email,
            "fecha_sim": resultado.get("fecha", ""),
            "parametros_json": json.dumps({"tipo": resultado.get("tipo", ""),
                                           "precio": resultado.get("precio", 0),
                                           "costo": resultado.get("costo", 0),
                                           "fuente": resultado.get("fuente", ""),
                                           "distrito": resultado.get("distrito", "")}),
            "resultado_json": json.dumps({"ventas": resultado.get("ventas", {}),
                                          "ingresos": resultado.get("ingresos", {}),
                                          "utilidad": resultado.get("utilidad", {}),
                                          "veredicto": resultado.get("veredicto", {}),
                                          "asignacion": resultado.get("asignacion", {})}),
        }).execute()
    except Exception:
        log("gemelo_guardar_sim")


def _cargar_simulaciones(supabase, email, log):
    if not supabase:
        return []
    try:
        r = supabase.table("gemelo_simulaciones").select("*").eq("user_id", email) \
            .order("fecha_sim", desc=True).limit(30).execute()
        return r.data or []
    except Exception:
        log("gemelo_cargar_sim")
        return []
