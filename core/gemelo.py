"""Gemelo Digital de Tentakl — MOTOR MATEMÁTICO (Python puro, SIN IA).

Separación estricta de capas: AQUÍ se calcula el número; la IA (en la UI) solo
explica en palabras lo que este motor produce. Nada de este archivo llama a
Gemini ni a Streamlit; todo es determinista y testeable.

Modelo:
  • Curva de respuesta por canal (saturación / rendimientos decrecientes):
        ventas_canal(g) = max_ventas * (1 - e^(-g / b))
    donde `g` es el gasto, `max_ventas` el techo del canal y `b` la escala de
    gasto (a mayor b, más lento satura).
  • Elasticidad de precio:
        factor = (precio / precio_ref)^(-elasticidad)
    subir el precio baja la demanda según la elasticidad del sector.
  • Monte Carlo: N simulaciones variando los parámetros ±15% para entregar un
    RANGO (p10, p50, p90), nunca un número exacto solo.
  • Distribución óptima: reparte un presupuesto maximizando ventas, asignando
    cada sol/dólar al canal con mayor retorno marginal (greedy sobre la
    derivada de la curva de saturación).

Supuesto honesto de atribución: como las ventas históricas son totales (no por
canal), repartimos cada semana las ventas entre canales en proporción a su
gasto. Es una aproximación (no causalidad real) y así se le comunica al usuario.
"""
from __future__ import annotations

import math

import numpy as np

CANALES = ["Meta", "Google", "TikTok"]

# ── Benchmarks por sector para ARRANQUE EN FRÍO (sin datos propios) ──────────
# roas_tope: ventas-tope aproximadas por cada unidad de "escala b" de gasto.
# elasticidad: sensibilidad de la demanda al precio (1.0 = neutral).
BENCHMARKS_SECTOR = {
    "retail_moda":       {"elasticidad": 1.4, "roas_canal": {"Meta": 2.2, "Google": 1.8, "TikTok": 2.0}},
    "food_beverage":     {"elasticidad": 1.1, "roas_canal": {"Meta": 2.6, "Google": 1.9, "TikTok": 2.4}},
    "servicios":         {"elasticidad": 0.8, "roas_canal": {"Meta": 1.6, "Google": 2.4, "TikTok": 1.3}},
    "ecommerce_general": {"elasticidad": 1.2, "roas_canal": {"Meta": 2.4, "Google": 2.2, "TikTok": 2.1}},
}
SECTOR_DEFAULT = "ecommerce_general"


# ══════════════════════════════════════════════════════════════════════════
# VALIDACIÓN DE DATOS
# ══════════════════════════════════════════════════════════════════════════
def validar_semanas(semanas):
    """Valida la lista de semanas ingresadas. Devuelve (ok, errores).

    Cada semana es un dict: {"gasto": {canal: float}, "ventas": float,
    "precio": float, "costo": float}. Rechaza negativos e inconsistencias.
    """
    errores = []
    if not isinstance(semanas, list):
        return False, ["Los datos de semanas no tienen el formato esperado."]
    for i, s in enumerate(semanas, 1):
        g = s.get("gasto", {}) or {}
        for c in CANALES:
            if float(g.get(c, 0) or 0) < 0:
                errores.append(f"Semana {i}: el gasto en {c} no puede ser negativo.")
        if float(s.get("ventas", 0) or 0) < 0:
            errores.append(f"Semana {i}: las ventas no pueden ser negativas.")
        _precio = float(s.get("precio", 0) or 0)
        _costo = float(s.get("costo", 0) or 0)
        if _precio < 0 or _costo < 0:
            errores.append(f"Semana {i}: precio y costo no pueden ser negativos.")
        if _precio > 0 and _costo > _precio:
            errores.append(f"Semana {i}: el costo unitario ({_costo}) es mayor que el precio ({_precio}).")
    return (len(errores) == 0), errores


def datos_suficientes(semanas, minimo=4):
    """True si hay al menos `minimo` semanas con algún gasto o venta."""
    utiles = [s for s in (semanas or [])
              if float(s.get("ventas", 0) or 0) > 0
              or sum(float((s.get("gasto", {}) or {}).get(c, 0) or 0) for c in CANALES) > 0]
    return len(utiles) >= minimo


# ══════════════════════════════════════════════════════════════════════════
# CURVA DE RESPUESTA
# ══════════════════════════════════════════════════════════════════════════
def ventas_canal(gasto, max_ventas, b):
    """Curva de saturación de un canal: ventas = max_ventas*(1 - e^(-gasto/b))."""
    gasto = max(float(gasto), 0.0)
    b = max(float(b), 1e-6)
    return float(max_ventas) * (1.0 - math.exp(-gasto / b))


def _retorno_marginal(gasto, max_ventas, b):
    """Derivada de la curva: cuántas ventas extra da el próximo sol en el canal."""
    b = max(float(b), 1e-6)
    return (float(max_ventas) / b) * math.exp(-float(gasto) / b)


def elasticidad_factor(precio, precio_ref, elasticidad):
    """factor = (precio/precio_ref)^(-elasticidad). 1.0 si precio == precio_ref."""
    precio = float(precio)
    precio_ref = float(precio_ref)
    if precio <= 0 or precio_ref <= 0:
        return 1.0
    return (precio / precio_ref) ** (-float(elasticidad))


# ══════════════════════════════════════════════════════════════════════════
# CALIBRACIÓN CON DATOS REALES
# ══════════════════════════════════════════════════════════════════════════
def _atribuir_ventas(semanas):
    """Reparte las ventas de cada semana entre canales en proporción al gasto.
    Devuelve dict canal -> lista de pares (gasto, ventas_atribuidas)."""
    series = {c: [] for c in CANALES}
    for s in semanas:
        g = s.get("gasto", {}) or {}
        gastos = {c: float(g.get(c, 0) or 0) for c in CANALES}
        total_g = sum(gastos.values())
        ventas = float(s.get("ventas", 0) or 0)
        if total_g <= 0:
            continue
        for c in CANALES:
            share = gastos[c] / total_g
            series[c].append((gastos[c], ventas * share))
    return series


def _calibrar_canal(pares):
    """Ajusta (max_ventas, b) de un canal por búsqueda en grilla (sin scipy).
    `pares` = [(gasto, ventas_atribuidas), ...]. Devuelve (max_ventas, b)."""
    gastos = np.array([p[0] for p in pares], dtype=float)
    ventas = np.array([p[1] for p in pares], dtype=float)
    g_pos = gastos[gastos > 0]
    if len(g_pos) == 0 or ventas.max() <= 0:
        # Sin señal: canal neutro
        return float(max(ventas.max(), 1.0)), float(max(gastos.mean(), 1.0))
    v_max_obs = float(ventas.max())
    g_med = float(np.mean(g_pos))
    # Grilla razonable alrededor de lo observado
    max_grid = np.linspace(v_max_obs * 1.05, v_max_obs * 3.0, 24)
    b_grid = np.linspace(g_med * 0.2, g_med * 4.0, 24)
    mejor = (v_max_obs * 1.5, g_med)
    mejor_sse = float("inf")
    for mx in max_grid:
        for b in b_grid:
            pred = mx * (1.0 - np.exp(-gastos / max(b, 1e-6)))
            sse = float(np.sum((pred - ventas) ** 2))
            if sse < mejor_sse:
                mejor_sse = sse
                mejor = (float(mx), float(b))
    return mejor


def calibrar(semanas, sector=SECTOR_DEFAULT):
    """Calibra los parámetros del gemelo con datos reales.

    Devuelve dict: {"canales": {canal: {"max": .., "b": ..}}, "elasticidad": ..,
    "precio_ref": .., "fuente": "datos"}.
    """
    series = _atribuir_ventas(semanas)
    canales = {}
    for c in CANALES:
        if series[c]:
            mx, b = _calibrar_canal(series[c])
        else:
            mx, b = 1.0, 1.0
        canales[c] = {"max": mx, "b": b}
    precios = [float(s.get("precio", 0) or 0) for s in semanas if float(s.get("precio", 0) or 0) > 0]
    precio_ref = float(np.mean(precios)) if precios else 0.0
    elasticidad = BENCHMARKS_SECTOR.get(sector, BENCHMARKS_SECTOR[SECTOR_DEFAULT])["elasticidad"]
    return {"canales": canales, "elasticidad": elasticidad,
            "precio_ref": precio_ref, "fuente": "datos"}


def params_benchmark(sector, precio_ref, gasto_tipico_por_canal):
    """Parámetros de arranque en frío a partir de benchmarks del sector.

    gasto_tipico_por_canal: dict canal -> gasto semanal estimado (para fijar la
    escala b). roas del sector define el techo de ventas de cada canal.
    """
    bench = BENCHMARKS_SECTOR.get(sector, BENCHMARKS_SECTOR[SECTOR_DEFAULT])
    canales = {}
    for c in CANALES:
        g = float((gasto_tipico_por_canal or {}).get(c, 0) or 0)
        b = max(g, 1.0)  # satura cerca del gasto típico
        roas = bench["roas_canal"][c]
        # Techo ≈ ventas que daría ~2*b de gasto a ese ROAS (unidades de venta)
        max_ventas = (roas * 2.0 * b) / max(float(precio_ref), 1.0) if precio_ref else roas * 2.0
        canales[c] = {"max": float(max_ventas), "b": float(b)}
    return {"canales": canales, "elasticidad": bench["elasticidad"],
            "precio_ref": float(precio_ref or 0), "fuente": "benchmark"}


# ══════════════════════════════════════════════════════════════════════════
# PREDICCIÓN + MONTE CARLO
# ══════════════════════════════════════════════════════════════════════════
def predecir_ventas(params, plan_gasto, precio):
    """Punto base (sin incertidumbre): ventas totales esperadas para un plan."""
    factor = elasticidad_factor(precio, params.get("precio_ref") or precio, params["elasticidad"])
    total = 0.0
    for c in CANALES:
        cp = params["canales"][c]
        total += ventas_canal(plan_gasto.get(c, 0), cp["max"], cp["b"])
    return max(total * factor, 0.0)


def monte_carlo(params, plan_gasto, precio, costo=0.0, n=500, variacion=0.15, seed=None):
    """N simulaciones variando los parámetros ±`variacion`. Devuelve rangos.

    Salida: {"ventas": {p10,p50,p90}, "ingresos": {...}, "utilidad": {...},
    "n": n}. ingresos = ventas*precio; utilidad = ventas*(precio-costo) - gasto.
    """
    rng = np.random.default_rng(seed)
    gasto_total = sum(float(plan_gasto.get(c, 0) or 0) for c in CANALES)
    precio_ref = params.get("precio_ref") or precio
    ventas_sims = np.zeros(n)
    for c in CANALES:
        cp = params["canales"][c]
        g = float(plan_gasto.get(c, 0) or 0)
        # Varía max y b de forma independiente por simulación
        max_s = cp["max"] * (1.0 + rng.uniform(-variacion, variacion, n))
        b_s = cp["b"] * (1.0 + rng.uniform(-variacion, variacion, n))
        b_s = np.maximum(b_s, 1e-6)
        ventas_sims += max_s * (1.0 - np.exp(-g / b_s))
    # Elasticidad también con algo de ruido
    elas_s = params["elasticidad"] * (1.0 + rng.uniform(-variacion, variacion, n))
    if precio > 0 and precio_ref > 0:
        factor_s = (precio / precio_ref) ** (-elas_s)
    else:
        factor_s = np.ones(n)
    ventas_sims = np.maximum(ventas_sims * factor_s, 0.0)
    ingresos_sims = ventas_sims * float(precio)
    utilidad_sims = ventas_sims * (float(precio) - float(costo)) - gasto_total

    def _pcts(arr):
        return {"p10": float(np.percentile(arr, 10)),
                "p50": float(np.percentile(arr, 50)),
                "p90": float(np.percentile(arr, 90))}

    return {"ventas": _pcts(ventas_sims), "ingresos": _pcts(ingresos_sims),
            "utilidad": _pcts(utilidad_sims), "n": int(n),
            "gasto_total": gasto_total}


# ══════════════════════════════════════════════════════════════════════════
# DISTRIBUCIÓN ÓPTIMA DEL PRESUPUESTO
# ══════════════════════════════════════════════════════════════════════════
def distribuir_optimo(params, presupuesto_total, precio, pasos=200):
    """Reparte `presupuesto_total` maximizando ventas (greedy marginal).

    En cada paso asigna un trozo del presupuesto al canal cuyo PRÓXIMO sol
    genere más ventas (derivada de la curva). Devuelve {"asignacion": {canal:
    gasto}, "ventas_estimadas": .., "ingresos_estimados": ..}.
    """
    presupuesto_total = max(float(presupuesto_total), 0.0)
    if presupuesto_total <= 0:
        return {"asignacion": {c: 0.0 for c in CANALES}, "ventas_estimadas": 0.0,
                "ingresos_estimados": 0.0}
    paso = presupuesto_total / max(int(pasos), 1)
    asignacion = {c: 0.0 for c in CANALES}
    for _ in range(int(pasos)):
        # Canal con mayor retorno marginal en su nivel de gasto actual
        mejor_c = max(
            CANALES,
            key=lambda c: _retorno_marginal(asignacion[c], params["canales"][c]["max"],
                                            params["canales"][c]["b"]),
        )
        asignacion[mejor_c] += paso
    ventas = predecir_ventas(params, asignacion, precio)
    return {"asignacion": {c: round(asignacion[c], 2) for c in CANALES},
            "ventas_estimadas": ventas,
            "ingresos_estimados": ventas * float(precio)}


def precision(prediccion_p10, prediccion_p90, venta_real):
    """% de acierto de una predicción pasada: 100 si la real cayó en el rango
    [p10, p90]; si no, decae según qué tan lejos quedó del borde más cercano."""
    try:
        real = float(venta_real)
        p10, p90 = float(prediccion_p10), float(prediccion_p90)
        if p10 <= real <= p90:
            return 100.0
        borde = p10 if real < p10 else p90
        if borde <= 0:
            return 0.0
        err = abs(real - borde) / borde
        return float(max(0.0, 100.0 * (1.0 - err)))
    except Exception:
        return 0.0


# ══════════════════════════════════════════════════════════════════════════
# ÁRBITRO + VEREDICTO (bug #1 de Decisia: el veredicto NUNCA contradice el ROI)
# El veredicto se DERIVA de los números, así que es imposible que diga "NO" con
# un ROI de 525%. Una sola función produce veredicto + números juntos; la IA
# solo lo explica, jamás decide el veredicto.
# ══════════════════════════════════════════════════════════════════════════
def veredicto(mc_resultado):
    """Decide ✅/⚠️/❌ a partir de la utilidad simulada (p10/p50).

    Lógica (el "árbitro"):
      ✅ HAZLO      → hasta en el peor caso (p10) ganas o empatas.
      ⚠️ CON CUIDADO → el caso probable (p50) gana, pero el peor caso pierde.
      ❌ NO          → ni el caso probable (p50) es rentable.
    Devuelve dict con icono, nivel, titulo, roas y la razón numérica.
    """
    util = mc_resultado.get("utilidad", {})
    ing = mc_resultado.get("ingresos", {})
    gasto = float(mc_resultado.get("gasto_total", 0) or 0)
    u_p10 = float(util.get("p10", 0))
    u_p50 = float(util.get("p50", 0))
    roas = (float(ing.get("p50", 0)) / gasto) if gasto > 0 else None

    if u_p50 <= 0:
        nivel, icono, titulo = "no", "❌", "No conviene"
        razon = f"Ni en el caso probable es rentable (utilidad p50 ≈ {u_p50:.0f})."
    elif u_p10 >= 0:
        nivel, icono, titulo = "hazlo", "✅", "Conviene"
        razon = f"Hasta en el peor caso ganas (utilidad p10 ≈ {u_p10:.0f}, probable ≈ {u_p50:.0f})."
    else:
        nivel, icono, titulo = "cuidado", "⚠️", "Con cuidado"
        razon = (f"El caso probable gana (≈ {u_p50:.0f}) pero el pesimista pierde "
                 f"(≈ {u_p10:.0f}). Riesgo real.")
    return {"icono": icono, "nivel": nivel, "titulo": titulo, "razon": razon,
            "roas": (round(roas, 2) if roas is not None else None)}


def escenarios(mc_resultado):
    """Empaqueta los 3 escenarios para la UI: pesimista(p10)/base(p50)/optimista(p90)."""
    def _s(p):
        return {"ventas": mc_resultado["ventas"][p], "ingresos": mc_resultado["ingresos"][p],
                "utilidad": mc_resultado["utilidad"][p]}
    return {"pesimista": _s("p10"), "base": _s("p50"), "optimista": _s("p90")}


def proyeccion(mc_resultado, semanas_por_mes=4.3, meses=(6, 12), crecimiento_mensual=0.0):
    """Proyecta ingresos y utilidad a 6 y 12 meses a partir del ritmo semanal base.

    Honesto: es una extrapolación lineal del caso probable (p50) "si mantienes
    este ritmo", con un crecimiento mensual opcional. No es una promesa.
    """
    ing_sem = float(mc_resultado["ingresos"]["p50"])
    util_sem = float(mc_resultado["utilidad"]["p50"])
    g = max(float(crecimiento_mensual), 0.0)
    out = {}
    for m in meses:
        # Suma de m meses con crecimiento compuesto mensual (factor sobre el mensual)
        factor = sum((1.0 + g) ** k for k in range(int(m)))
        ing_mes = ing_sem * semanas_por_mes
        util_mes = util_sem * semanas_por_mes
        out[f"{m}m"] = {"ingresos": round(ing_mes * factor, 2),
                        "utilidad": round(util_mes * factor, 2)}
    return out


# ══════════════════════════════════════════════════════════════════════════
# SIMULADOR DE DECISIONES — 4 tipos, mismo formato de salida
# Todos devuelven: ventas/ingresos/utilidad (p10/p50/p90) + veredicto +
# escenarios + proyeccion + tipo + fuente. Presupuesto y precio usan las curvas
# calibradas (sólidos); producto y zona son por SUPUESTOS explícitos (se marca
# fuente="supuestos" y se usa más incertidumbre, para no caer en fantasía).
# ══════════════════════════════════════════════════════════════════════════
TIPOS_DECISION = ("presupuesto", "precio", "producto", "zona")


def _empacar(mc, tipo, extra=None):
    """Toma un resultado Monte Carlo y le agrega veredicto/escenarios/proyección."""
    out = {
        "tipo": tipo,
        "ventas": mc["ventas"], "ingresos": mc["ingresos"], "utilidad": mc["utilidad"],
        "gasto_total": mc.get("gasto_total", 0.0),
        "veredicto": veredicto(mc), "escenarios": escenarios(mc), "proyeccion": proyeccion(mc),
    }
    if extra:
        out.update(extra)
    return out


def _mc_alrededor(ventas_media, precio, costo, gasto_total, incertidumbre=0.35, n=500, seed=None):
    """Monte Carlo alrededor de una venta media estimada (para decisiones sin
    curva histórica: producto nuevo, zona). Mayor incertidumbre a propósito."""
    rng = np.random.default_rng(seed)
    ventas = np.maximum(float(ventas_media) * (1.0 + rng.uniform(-incertidumbre, incertidumbre, n)), 0.0)
    ingresos = ventas * float(precio)
    utilidad = ventas * (float(precio) - float(costo)) - float(gasto_total)

    def _p(a):
        return {"p10": float(np.percentile(a, 10)), "p50": float(np.percentile(a, 50)),
                "p90": float(np.percentile(a, 90))}

    return {"ventas": _p(ventas), "ingresos": _p(ingresos), "utilidad": _p(utilidad),
            "n": int(n), "gasto_total": float(gasto_total)}


def sim_presupuesto(params, presupuesto, precio, costo=0.0, n=500, seed=None):
    """¿Cuánto invertir en ads y cómo repartir? Usa curvas calibradas."""
    dist = distribuir_optimo(params, presupuesto, precio)
    mc = monte_carlo(params, dist["asignacion"], precio, costo=costo, n=n, seed=seed)
    return _empacar(mc, "presupuesto",
                    {"asignacion": dist["asignacion"], "fuente": params.get("fuente", "datos")})


def sim_precio(params, precio_actual, precio_nuevo, plan_gasto, costo=0.0, n=500, seed=None):
    """¿Subo o bajo el precio? Compara utilidad al precio actual vs el nuevo."""
    mc_act = monte_carlo(params, plan_gasto, precio_actual, costo=costo, n=n, seed=seed)
    mc_new = monte_carlo(params, plan_gasto, precio_nuevo, costo=costo, n=n, seed=seed)
    comp = {
        "utilidad_actual": mc_act["utilidad"]["p50"], "utilidad_nueva": mc_new["utilidad"]["p50"],
        "ventas_actual": mc_act["ventas"]["p50"], "ventas_nueva": mc_new["ventas"]["p50"],
        "mejora": mc_new["utilidad"]["p50"] - mc_act["utilidad"]["p50"],
    }
    return _empacar(mc_new, "precio",
                    {"fuente": params.get("fuente", "datos"), "comparacion": comp,
                     "precio_actual": precio_actual, "precio_nuevo": precio_nuevo})


def sim_producto_nuevo(precio, costo, gasto_marketing, demanda_esperada,
                       incertidumbre=0.35, n=500, seed=None):
    """¿Lanzo un producto nuevo? Sin historial → por supuestos (demanda esperada
    semanal) con alta incertidumbre. fuente='supuestos'."""
    mc = _mc_alrededor(demanda_esperada, precio, costo, gasto_marketing, incertidumbre, n, seed)
    return _empacar(mc, "producto", {"fuente": "supuestos", "incertidumbre": incertidumbre})


def sim_zona(precio, costo, inversion, clientes_potenciales, penetracion_pct,
             incertidumbre=0.35, n=500, seed=None):
    """¿Abro en otra zona/distrito? Por supuestos: clientes potenciales ×
    penetración esperada. fuente='supuestos'."""
    ventas_media = float(clientes_potenciales) * max(float(penetracion_pct), 0.0) / 100.0
    mc = _mc_alrededor(ventas_media, precio, costo, inversion, incertidumbre, n, seed)
    return _empacar(mc, "zona", {"fuente": "supuestos", "incertidumbre": incertidumbre,
                                 "clientes_potenciales": clientes_potenciales,
                                 "penetracion_pct": penetracion_pct})


# Colores del mapa de efectividad por zona (🟢/🟡/🔴 según el veredicto)
_COLOR_NIVEL = {"hazlo": ("🟢", "#16A34A"), "cuidado": ("🟡", "#D97706"), "no": ("🔴", "#DC2626")}


def mapa_zonas(zonas, precio, costo, incertidumbre=0.35, n=400, seed=None):
    """Compara varias zonas y las pinta 🟢/🟡/🔴 por efectividad (fase 2 del doc).

    zonas: [{"nombre","clientes","penetracion","inversion"}].
    Devuelve {"zonas": [...orden por utilidad...], "mejor": nombre, "tipo":"zonas_mapa"}.
    Produce también los datos listos (JSON) para un mapa geográfico futuro.
    """
    filas = []
    for z in (zonas or []):
        nombre = str(z.get("nombre", "") or "").strip()
        clientes = float(z.get("clientes", 0) or 0)
        pen = float(z.get("penetracion", 0) or 0)
        inv = float(z.get("inversion", 0) or 0)
        if not nombre or clientes <= 0:
            continue
        r = sim_zona(precio, costo, inv, clientes, pen, incertidumbre=incertidumbre, n=n, seed=seed)
        nivel = r["veredicto"]["nivel"]
        icono, color = _COLOR_NIVEL.get(nivel, ("⚪", "#9890ad"))
        util = r["utilidad"]["p50"]
        roi = (util / inv) if inv > 0 else None
        filas.append({
            "nombre": nombre, "nivel": nivel, "icono": icono, "color": color,
            "ventas_p50": round(r["ventas"]["p50"], 1),
            "utilidad_p50": round(util, 1),
            "roi": (round(roi, 2) if roi is not None else None),
            "clientes": clientes, "penetracion": pen, "inversion": inv,
        })
    filas.sort(key=lambda f: f["utilidad_p50"], reverse=True)
    return {"tipo": "zonas_mapa", "zonas": filas,
            "mejor": (filas[0]["nombre"] if filas else "")}
