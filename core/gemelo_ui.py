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

_SECTORES_LBL = {
    "retail_moda": "Retail / Moda",
    "food_beverage": "Comida y bebida",
    "servicios": "Servicios",
    "ecommerce_general": "E-commerce general",
}


def _noop(*_a, **_k):
    return None


def render(*, supabase=None, generar_texto=None, user_email="", marca="",
           sector_nicho="", moneda="S/", lang="es", log=None):
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
        _tab_resultado(marca, moneda, T)

    # ── TAB 4 — HISTORIAL ───────────────────────────────────────────────────
    with tabs[3]:
        _tab_historial(supabase, user_email, moneda, T, log)


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


def _tab_simular(supabase, generar_texto, user_email, marca, sector_nicho, moneda, T, log):
    semanas = st.session_state.get("gemelo_semanas") or []
    hay_datos = G.datos_suficientes(semanas)

    _sector = st.selectbox(T("Tu sector (para el arranque y la elasticidad):", "Your sector (for cold start & elasticity):"),
                           list(_SECTORES_LBL.keys()),
                           format_func=lambda k: _SECTORES_LBL[k], key="gemelo_sector")
    if not hay_datos:
        st.warning(T("⚠ Predicción basada en benchmarks del sector — mejora cuando cargues 4+ semanas de tus datos reales.",
                     "⚠ Prediction based on sector benchmarks — improves once you load 4+ weeks of your real data."))
    else:
        st.success(T("✅ Gemelo calibrado con tus datos reales.", "✅ Twin calibrated on your real data."))

    # Precio y costo sugeridos desde los datos
    _precio_def = 0.0
    _costo_def = 0.0
    if semanas:
        _ps = [s["precio"] for s in semanas if s["precio"] > 0]
        _cs = [s["costo"] for s in semanas if s["costo"] > 0]
        _precio_def = round(sum(_ps) / len(_ps), 2) if _ps else 0.0
        _costo_def = round(sum(_cs) / len(_cs), 2) if _cs else 0.0

    _gasto_hist = 0.0
    if semanas:
        _gasto_hist = max((sum(s["gasto"].values()) for s in semanas), default=0.0)
    _tope = max(int(_gasto_hist * 3), 1000)

    presupuesto = st.slider(T(f"Presupuesto total semanal ({moneda})", f"Total weekly budget ({moneda})"),
                            min_value=0, max_value=_tope, value=min(int(_gasto_hist) or 300, _tope),
                            step=max(_tope // 100, 10), key="gemelo_presupuesto")
    _cp1, _cp2 = st.columns(2)
    with _cp1:
        precio = st.number_input(T(f"Precio unitario ({moneda})", f"Unit price ({moneda})"),
                                 min_value=0.0, value=float(_precio_def), step=1.0, key="gemelo_precio")
    with _cp2:
        costo = st.number_input(T(f"Costo unitario ({moneda})", f"Unit cost ({moneda})"),
                                min_value=0.0, value=float(_costo_def), step=1.0, key="gemelo_costo")

    if st.button("🔮 " + T("Simular", "Simulate"), key="gemelo_simular_btn", use_container_width=True):
        if precio <= 0:
            st.error(T("Ingresa un precio unitario mayor que 0.", "Enter a unit price greater than 0."))
            return
        # Parámetros: datos reales o benchmark
        if hay_datos:
            params = G.calibrar(semanas, _sector)
            if not params.get("precio_ref"):
                params["precio_ref"] = precio
        else:
            _gtip = {c: presupuesto / 3.0 for c in G.CANALES}
            params = G.params_benchmark(_sector, precio, _gtip)

        dist = G.distribuir_optimo(params, presupuesto, precio)
        mc = G.monte_carlo(params, dist["asignacion"], precio, costo=costo, n=500)

        resultado = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "semana": datetime.now().strftime("%W (%Y)"),
            "fuente": params["fuente"],
            "presupuesto": presupuesto, "precio": precio, "costo": costo, "moneda": moneda,
            "asignacion": dist["asignacion"],
            "ventas": mc["ventas"], "ingresos": mc["ingresos"], "utilidad": mc["utilidad"],
        }
        # Explicación con IA (opcional)
        resultado["explicacion"] = _explicar_ia(generar_texto, resultado, marca, moneda, T) if generar_texto else ""
        st.session_state["gemelo_resultado"] = resultado
        _guardar_simulacion(supabase, user_email, resultado, log)
        st.success(T("Listo. Mira la pestaña 📊 Resultado.", "Done. See the 📊 Result tab."))


def _tab_resultado(marca, moneda, T):
    r = st.session_state.get("gemelo_resultado")
    if not r:
        st.info(T("Aún no has simulado. Ve a la pestaña 🎛 Simular.", "No simulation yet. Go to the 🎛 Simulate tab."))
        return
    v = r["ventas"]
    st.markdown(f"### {T('Predicción de esta semana', 'This week prediction')}")
    _c1, _c2, _c3 = st.columns(3)
    _c1.metric(T("Pesimista", "Pessimistic"), f"{v['p10']:.0f}")
    _c2.metric(T("Más probable", "Most likely"), f"{v['p50']:.0f}", T("ventas", "sales"))
    _c3.metric(T("Optimista", "Optimistic"), f"{v['p90']:.0f}")
    st.markdown(f"**{T('Rango de ventas', 'Sales range')}: {v['p10']:.0f} – {v['p90']:.0f}** · "
                f"{T('Ingresos', 'Revenue')} ≈ {moneda}{r['ingresos']['p50']:.0f} · "
                f"{T('Utilidad', 'Profit')} ≈ {moneda}{r['utilidad']['p50']:.0f}")
    if r.get("fuente") == "benchmark":
        st.caption("⚠ " + T("Basado en benchmarks del sector.", "Based on sector benchmarks."))

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

    # Reparto recomendado
    st.markdown(f"#### 🎯 {T('Reparto recomendado del presupuesto', 'Recommended budget split')}")
    _cols = st.columns(len(r["asignacion"]))
    for _col, (canal, g) in zip(_cols, r["asignacion"].items()):
        _col.metric(canal, f"{moneda}{g:.0f}")

    # Explicación IA
    if r.get("explicacion"):
        st.markdown("#### 🧠 " + T("Qué significa", "What it means"))
        st.markdown(r["explicacion"])

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
def _explicar_ia(generar_texto, r, marca, moneda, T):
    v, ing = r["ventas"], r["ingresos"]
    reparto = ", ".join(f"{c}: {moneda}{g:.0f}" for c, g in r["asignacion"].items())
    prompt = (
        "Eres un analista de marketing. Explica en español simple y claro, en MÁXIMO 150 palabras, "
        "este resultado de una simulación (NO inventes números, usa solo estos):\n"
        f"- Marca: {marca}\n"
        f"- Presupuesto semanal: {moneda}{r['presupuesto']}\n"
        f"- Ventas estimadas: entre {v['p10']:.0f} y {v['p90']:.0f} (más probable {v['p50']:.0f})\n"
        f"- Ingresos estimados (más probable): {moneda}{ing['p50']:.0f}\n"
        f"- Reparto recomendado del presupuesto: {reparto}\n\n"
        "Formato EXACTO:\n"
        "1) Una frase que explique el rango en lenguaje de dueño de negocio.\n"
        "2) Una frase sobre el reparto recomendado y por qué.\n"
        "3) UNA acción concreta esta semana (ej: 'mueve X " + moneda + " de un canal a otro').\n"
        "Sin markdown de encabezados, directo y motivador."
    )
    try:
        out = generar_texto(prompt, max_out=1200, temperatura=0.4)
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
            "parametros_json": json.dumps({"presupuesto": resultado["presupuesto"],
                                           "precio": resultado["precio"],
                                           "costo": resultado["costo"],
                                           "fuente": resultado["fuente"]}),
            "resultado_json": json.dumps({"ventas": resultado["ventas"],
                                          "ingresos": resultado["ingresos"],
                                          "asignacion": resultado["asignacion"]}),
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
