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

_SECTORES_LBL = {
    "retail_moda": "Retail / Moda",
    "food_beverage": "Comida y bebida",
    "servicios": "Servicios",
    "ecommerce_general": "E-commerce general",
}


def _noop(*_a, **_k):
    return None


def render(*, supabase=None, generar_texto=None, user_email="", marca="",
           sector_nicho="", moneda="S/", lang="es", log=None, historial_activo=True):
    """Dibuja el Gemelo Digital. Dependencias inyectadas (ver docstring)."""
    log = log or _noop
    _en = (lang == "en")

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
        })
    return semanas


def _tab_datos(supabase, user_email, moneda, T, log):
    import pandas as pd

    st.write(T(f"Ingresa tus últimas semanas (gasto en {moneda}). Con 4+ semanas el Gemelo se calibra con TUS datos.",
               f"Enter your recent weeks (spend in {moneda}). With 4+ weeks the Twin calibrates on YOUR data."))

    # Carga previa (sesión o Supabase)
    _key = "gemelo_df"
    if _key not in st.session_state:
        _filas = _cargar_datos(supabase, user_email, log)
        if not _filas:
            _filas = [{"Semana": f"S{i}", "Gasto Meta": 0.0, "Gasto Google": 0.0,
                       "Gasto TikTok": 0.0, "Ventas": 0.0, "Precio": 0.0, "Costo": 0.0}
                      for i in range(1, 5)]
        st.session_state[_key] = pd.DataFrame(_filas)

    df = st.data_editor(st.session_state[_key], num_rows="dynamic", use_container_width=True,
                        key="gemelo_editor")

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

    if _tipo in ("presupuesto", "precio"):
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
    if _tipo == "presupuesto":
        _tope = max(int(_gasto_hist * 3), 1000)
        datos["presupuesto"] = st.slider(T(f"Presupuesto semanal ({moneda})", f"Weekly budget ({moneda})"),
                                         0, _tope, min(int(_gasto_hist) or 300, _tope),
                                         step=max(_tope // 100, 10), key="g_presup")
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
    if tipo in ("presupuesto", "precio") and precio <= 0:
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
    def _params():
        if hay_datos:
            p = G.calibrar(semanas, sector)
            if not p.get("precio_ref"):
                p["precio_ref"] = precio or datos.get("precio_actual", 0)
            return p
        _base = datos.get("presupuesto") or datos.get("gasto") or 300
        return G.params_benchmark(sector, precio or datos.get("precio_actual", 20),
                                  {c: _base / 3.0 for c in G.CANALES})

    if tipo == "presupuesto":
        res = G.sim_presupuesto(_params(), datos["presupuesto"], precio, costo=costo)
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

    st.markdown(f"### {T('Predicción de esta semana', 'This week prediction')}")
    _c1, _c2, _c3 = st.columns(3)
    _c1.metric(T("Pesimista", "Pessimistic"), f"{v['p10']:.0f}")
    _c2.metric(T("Más probable", "Most likely"), f"{v['p50']:.0f}", T("ventas", "sales"))
    _c3.metric(T("Optimista", "Optimistic"), f"{v['p90']:.0f}")
    st.markdown(f"**{T('Rango de ventas', 'Sales range')}: {v['p10']:.0f} – {v['p90']:.0f}** · "
                f"{T('Ingresos', 'Revenue')} ≈ {moneda}{r['ingresos']['p50']:.0f} · "
                f"{T('Utilidad', 'Profit')} ≈ {moneda}{r['utilidad']['p50']:.0f}")
    if r.get("fuente") == "benchmark":
        st.caption("⚠ " + T("Basado en benchmarks del sector (sin tus datos aún).",
                             "Based on sector benchmarks (no data from you yet)."))
    elif r.get("fuente") == "supuestos":
        st.caption("⚠ " + T("Estimación por supuestos (sin historial) — rango amplio a propósito.",
                             "Assumption-based estimate (no history) — range is wide on purpose."))
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
        st.markdown(f"#### 🏷 {T('Precio actual vs nuevo', 'Current vs new price')}")
        _pa, _pb = st.columns(2)
        _pa.metric(f"{moneda}{r.get('precio_actual', 0):.0f} " + T("(actual)", "(current)"),
                   f"{_comp['ventas_actual']:.0f} " + T("ventas", "sales"),
                   f"{moneda}{_comp['utilidad_actual']:.0f} " + T("utilidad", "profit"))
        _pb.metric(f"{moneda}{r.get('precio_nuevo', 0):.0f} " + T("(nuevo)", "(new)"),
                   f"{_comp['ventas_nueva']:.0f} " + T("ventas", "sales"),
                   f"{moneda}{_comp['utilidad_nueva']:.0f}",
                   delta=f"{_comp['mejora']:+.0f} " + T("utilidad", "profit"))

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

    # Tarjeta compartible
    st.divider()
    png, err = GC.generar_tarjeta(marca, v["p10"], v["p90"], r.get("semana", ""),
                                  moneda=moneda, ingresos_p50=r["ingresos"]["p50"])
    if png:
        st.download_button("📤 " + T("Descargar tarjeta para compartir", "Download shareable card"),
                           data=png, file_name="gemelo_tentakl.png", mime="image/png",
                           key="gemelo_card_dl", use_container_width=True)
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
    "precio": "si subir o bajar el precio",
    "producto": "si lanzar un producto nuevo",
    "zona": "si abrir en otra zona/distrito",
}


def _explicar_ia(generar_texto, r, marca, moneda, T):
    """La IA SOLO explica los números que ya calculó el motor (nunca inventa)."""
    v, ing, ut = r["ventas"], r["ingresos"], r["utilidad"]
    ver = r.get("veredicto", {})
    tipo = r.get("tipo", "presupuesto")
    _extra = ""
    if r.get("asignacion"):
        _extra = "- Reparto recomendado: " + ", ".join(f"{c}: {moneda}{g:.0f}" for c, g in r["asignacion"].items()) + "\n"
    elif r.get("comparacion"):
        _c = r["comparacion"]
        _extra = (f"- Precio actual {moneda}{r.get('precio_actual', 0):.0f} da utilidad {moneda}{_c['utilidad_actual']:.0f}; "
                  f"precio nuevo {moneda}{r.get('precio_nuevo', 0):.0f} da {moneda}{_c['utilidad_nueva']:.0f} "
                  f"(cambio {_c['mejora']:+.0f}).\n")
    prompt = (
        "Eres un analista de negocio. Explica en español simple, en MÁXIMO 150 palabras, "
        "este resultado de una simulación. NO inventes números ni nombres: usa SOLO estos.\n"
        f"- Marca: {marca}\n"
        f"- Decisión analizada: {_DECISION_TXT.get(tipo, tipo)}\n"
        f"- Veredicto del motor: {ver.get('icono', '')} {ver.get('titulo', '')} ({ver.get('razon', '')})\n"
        f"- Ventas estimadas: entre {v['p10']:.0f} y {v['p90']:.0f} (más probable {v['p50']:.0f})\n"
        f"- Ingresos (probable): {moneda}{ing['p50']:.0f} · Utilidad (probable): {moneda}{ut['p50']:.0f}\n"
        f"{_extra}\n"
        "Formato EXACTO (sin encabezados markdown):\n"
        "1) Una frase que explique el veredicto y el rango en lenguaje de dueño de negocio.\n"
        "2) Una frase con el porqué (qué mueve el resultado).\n"
        "3) UNA acción concreta para esta semana.\n"
        "Directo y honesto; si el veredicto es ⚠️ o ❌, dilo claro, no lo adornes."
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
                          "Costo": float(row.get("costo", 0) or 0)})
        return filas
    except Exception:
        log("gemelo_cargar_datos")
        return []


def _guardar_datos(supabase, email, df, log):
    if not supabase:
        return
    try:
        supabase.table("gemelo_datos").delete().eq("user_id", email).execute()
        payload = []
        for _, row in df.iterrows():
            payload.append({"user_id": email, "fecha": str(row.get("Semana", "")),
                            "gasto_meta": float(row.get("Gasto Meta", 0) or 0),
                            "gasto_google": float(row.get("Gasto Google", 0) or 0),
                            "gasto_tiktok": float(row.get("Gasto TikTok", 0) or 0),
                            "ventas": float(row.get("Ventas", 0) or 0),
                            "precio": float(row.get("Precio", 0) or 0),
                            "costo": float(row.get("Costo", 0) or 0)})
        if payload:
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
