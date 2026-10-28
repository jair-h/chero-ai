"""Tests de humo del código nuevo (sin red real, sin credenciales, sin Streamlit).

Corre con:  python tests/test_tentakl.py
Mockea `requests` dentro de los módulos para validar el camino crítico:
GA4 (OAuth + parsing), conectores de tienda y la capa de agentes.
"""
import os
import sys
import time

# Permite importar los paquetes del repo al correr desde /tests o raíz
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integrations import analytics as A
from integrations import stores as S
from integrations import meta_ads as MA
from core import agents as AG
from core import context as CX
from core import gemelo as GM
from core import gemelo_card as GMC
from core import gemelo_personas as GMP

_fallos = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ FALLO: {msg}")
        _fallos.append(msg)


# ── Fakes de red ───────────────────────────────────────────────────────────
class FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class FakeRequests:
    """Enruta get/post según la URL con respuestas configurables."""
    def __init__(self, router):
        self._router = router

    def get(self, url, **kw):
        return self._router("GET", url, kw)

    def post(self, url, **kw):
        return self._router("POST", url, kw)


SECRETS = {
    "GOOGLE_OAUTH_CLIENT_ID": "cid.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
    "GOOGLE_OAUTH_REDIRECT_URI": "https://tentakl.streamlit.app/",
}


# ── 1) OAuth helpers ─────────────────────────────────────────────────────
def test_oauth_helpers():
    print("\n[1] OAuth helpers")
    check(A.oauth_configurado(SECRETS) is True, "oauth_configurado True con credenciales")
    check(A.oauth_configurado({}) is False, "oauth_configurado False sin credenciales")

    url = A.build_auth_url(SECRETS, state="tentaklga|jair@x.com")
    check("client_id=cid" in url, "auth URL lleva client_id")
    check("analytics.readonly" in url, "auth URL lleva scope analytics.readonly")
    check("access_type=offline" in url, "auth URL pide offline (refresh token)")
    check("state=tentaklga" in url, "auth URL lleva el state")

    # serializar/parsear
    bundle = {"access_token": "AT", "refresh_token": "RT", "expiry": time.time() + 1000}
    s = A.serializar_bundle(bundle)
    check(A.parsear_token_guardado(s)["access_token"] == "AT", "bundle round-trip JSON")
    check(A.parsear_token_guardado("AIzaSyLegacy").get("api_key_legacy") == "AIzaSyLegacy",
          "API key vieja se detecta como legacy")
    check(A.parsear_token_guardado("") == {}, "token vacío -> dict vacío")

    # Login con Google (entrar con Google) — misma app OAuth, scope básico
    _login_url = A.build_login_url(SECRETS)
    check("scope=openid" in _login_url and "email" in _login_url, "login URL pide openid/email")
    check("state=tentakllogin" in _login_url, "login URL lleva state de login")

    def _router_ui(method, url, kw):
        if "userinfo" in url:
            return FakeResp(200, {"email": "Jair@Gmail.com ", "email_verified": True})
        return FakeResp(404, {}, "no")
    A.requests = FakeRequests(_router_ui)
    _em, _e = A.fetch_userinfo("TOK")
    check(_e is None and _em == "jair@gmail.com", "fetch_userinfo devuelve email normalizado")


def test_token_refresh():
    print("\n[2] access_token_valido (refresh)")
    # Token vigente: devuelve el mismo sin tocar la red
    vig = {"access_token": "GOOD", "refresh_token": "RT", "expiry": time.time() + 5000}
    tok, b2, err = A.access_token_valido(SECRETS, vig)
    check(err is None and tok == "GOOD", "token vigente se reutiliza")

    # Token expirado con refresh: renueva vía POST mockeado
    def router(method, url, kw):
        if "oauth2.googleapis.com/token" in url:
            return FakeResp(200, {"access_token": "NEW", "expires_in": 3600})
        return FakeResp(404, {}, "no")
    A.requests = FakeRequests(router)
    exp = {"access_token": "OLD", "refresh_token": "RT", "expiry": time.time() - 10}
    tok, b2, err = A.access_token_valido(SECRETS, exp)
    check(err is None and tok == "NEW", "token expirado se renueva con refresh_token")
    check(b2["refresh_token"] == "RT", "refresh_token se conserva tras renovar")

    # Expirado sin refresh: error claro
    tok, b2, err = A.access_token_valido(SECRETS, {"access_token": "X", "refresh_token": "", "expiry": 0})
    check(tok is None and err, "expirado sin refresh -> error")


def test_ga4_report():
    print("\n[3] fetch_ga4_report (parsing)")
    # Rechaza el measurement ID G-XXXX
    data, err = A.fetch_ga4_report("G-ABC123", "TOK")
    check(data is None and "NUMÉRICO" in (err or ""), "rechaza G-XXXX y pide ID numérico")

    reports = {"reports": [
        {"rows": [{"metricValues": [
            {"value": "1000"}, {"value": "800"}, {"value": "300"}, {"value": "2500"},
            {"value": "0.45"}, {"value": "95"}, {"value": "2.5"}, {"value": "0.62"},
            {"value": "15000.50"}, {"value": "120"}]}]},
        {"rows": [
            {"dimensionValues": [{"value": "Organic Search"}], "metricValues": [{"value": "500"}]},
            {"dimensionValues": [{"value": "Direct"}], "metricValues": [{"value": "300"}]}]},
        {"rows": [{"dimensionValues": [{"value": "/"}], "metricValues": [{"value": "1200"}]}]},
        {"rows": [{"dimensionValues": [{"value": "mobile"}], "metricValues": [{"value": "700"}]}]},
        {"rows": [{"dimensionValues": [{"value": "Peru"}], "metricValues": [{"value": "600"}]}]},
        {"rows": [{"dimensionValues": [{"value": "20251001"}],
                   "metricValues": [{"value": "50"}, {"value": "40"}]}]},
    ]}

    def router(method, url, kw):
        if "batchRunReports" in url:
            return FakeResp(200, reports)
        return FakeResp(404, {}, "no")
    A.requests = FakeRequests(router)

    data, err = A.fetch_ga4_report("123456789", "TOK", "30daysAgo")
    check(err is None and data is not None, "reporte GA4 OK sin error")
    t = data["totales"]
    check(t["sessions"] == 1000 and t["activeUsers"] == 800 and t["newUsers"] == 300, "totales correctos")
    check(t["bounceRate"] == 45.0, "bounceRate convertido a % (45.0)")
    check(t["engagementRate"] == 62.0, "engagementRate convertido a % (62.0)")
    check(t["pageViews"] == 2500 and t["pagesPerSession"] == 2.5, "vistas y páginas/sesión")
    check(data["canales"]["Organic Search"] == 500, "canales parseados")
    check(data["paginas"][0]["ruta"] == "/" and data["paginas"][0]["vistas"] == 1200, "páginas top")
    check(data["dispositivos"]["mobile"] == 700, "dispositivos")
    check(data["paises"]["Peru"] == 600, "países")
    check(data["serie"][0]["fecha"] == "20251001" and data["serie"][0]["sesiones"] == 50, "serie diaria")
    check(t["ingresos"] == 15000.5 and t["transacciones"] == 120, "ecommerce: ingresos y transacciones")
    check(t["ticketPromedio"] == 125.0, "ticket promedio = ingresos/transacciones")

    # Error de API: no inventa datos
    def router_err(method, url, kw):
        return FakeResp(403, {}, "forbidden")
    A.requests = FakeRequests(router_err)
    data, err = A.fetch_ga4_report("123456789", "TOK")
    check(data is None and "403" in (err or ""), "error de API -> sin datos inventados")


def test_listar_propiedades():
    print("\n[4] listar_propiedades")
    def router(method, url, kw):
        if url.endswith("/accounts"):
            return FakeResp(200, {"accounts": [{"name": "accounts/111"}]})
        if url.endswith("/properties"):
            return FakeResp(200, {"properties": [
                {"name": "properties/123456789", "displayName": "Mi Sitio"}]})
        return FakeResp(404, {}, "no")
    A.requests = FakeRequests(router)
    props, err = A.listar_propiedades("TOK")
    check(err is None, "listar_propiedades sin error")
    check(props and props[0]["id"] == "123456789" and props[0]["nombre"] == "Mi Sitio",
          "propiedad con ID numérico y nombre")


def test_stores():
    print("\n[5] conectores de tienda")
    def router_sh(method, url, kw):
        if "products.json" in url:
            return FakeResp(200, {"products": [
                {"title": "Café Orgánico", "variants": [{"price": "20.00"}]}]})
        return FakeResp(500, {}, "err")
    S.requests = FakeRequests(router_sh)
    lineas, err = S.fetch_shopify_products("mitienda.myshopify.com", "token", "$")
    check(err is None and lineas == ["Café Orgánico - $20.00"], "Shopify parsea título y precio")

    lineas, err = S.fetch_shopify_products("", "token", "$")
    check(lineas == [] and err, "Shopify sin URL -> error claro")

    def router_woo(method, url, kw):
        if "/wp-json/wc/v3/products" in url:
            return FakeResp(200, [{"name": "Cacao", "price": "5"}])
        return FakeResp(500, {}, "err")
    S.requests = FakeRequests(router_woo)
    lineas, err = S.fetch_woocommerce_products("mitienda.com", "ck", "cs", "S/")
    check(err is None and lineas == ["Cacao - S/5"], "WooCommerce parsea nombre y precio")

    # Ventas por mes (autollenado del Gemelo): suma pedidos reales, ignora cancelados
    from datetime import datetime as _dt
    _now = _dt.now()
    _ym_now = _now.strftime("%Y-%m")
    _lm, _ly = (_now.month - 1, _now.year) if _now.month > 1 else (12, _now.year - 1)
    _ym_last = f"{_ly:04d}-{_lm:02d}"

    def router_woo_sales(method, url, kw):
        if "/wp-json/wc/v3/orders" in url:
            if kw.get("params", {}).get("page", 1) != 1:
                return FakeResp(200, [])
            return FakeResp(200, [
                {"status": "completed", "total": "100.00", "date_paid": _ym_now + "-05T10:00:00"},
                {"status": "processing", "total": "50.00", "date_created": _ym_now + "-06T10:00:00"},
                {"status": "cancelled", "total": "999.00", "date_created": _ym_now + "-07T10:00:00"},
                {"status": "completed", "total": "80.00", "date_paid": _ym_last + "-10T10:00:00"},
            ])
        return FakeResp(500, {}, "err")
    S.requests = FakeRequests(router_woo_sales)
    filas, err = S.fetch_woocommerce_sales_by_month("mitienda.com", "ck", "cs", meses=3)
    _d = {f["ym"]: f["ventas"] for f in filas}
    check(err is None and _d.get(_ym_now) == 150.0, "ventas del mes suma completed+processing")
    check(_d.get(_ym_last) == 80.0, "ventas del mes anterior correctas")
    check(len(filas) == 3 and all("mes" in f for f in filas), "devuelve 3 meses con etiqueta legible")
    check(999.0 not in _d.values(), "ignora pedidos cancelados")


def test_agents():
    print("\n[6] capa de agentes")
    check(len(AG.AGENTES) == 8, "8 tentáculos definidos (9no = autopiloto)")
    r = AG.seleccion_agentes_por_reglas("quiero analizar mi roi y kpis")
    check([a[0] for a in r["agentes"]] == ["metricas", "ventas", "estrategia"], "routing métricas")
    r = AG.seleccion_agentes_por_reglas("lanzar un nuevo producto")
    check("publicidad" in [a[0] for a in r["agentes"]], "routing lanzamiento incluye publicidad")
    # ocultar imágenes
    import copy
    ag = copy.deepcopy(AG.AGENTES)
    AG.ocultar_generador_imagenes(ag)
    subs = [s[3] for s in ag["imagenes"]["subfunciones"]]
    check("Generador de Imagenes" not in subs and "Auditoría Visual (Video/Foto)" in subs,
          "ocultar imágenes deja solo Auditoría Visual")


def test_context():
    print("\n[7] capa de contexto/validación")
    pe = CX.get_contexto_pais("Perú 🇵🇪")
    check(pe["moneda"] == "S/" and pe["idioma"] == "es", "Perú -> Soles, español (limpia emoji)")
    us = CX.get_contexto_pais("USA 🇺🇸")
    check(us["idioma"] == "en", "USA -> inglés")
    dflt = CX.get_contexto_pais("Narnia")
    check(dflt["moneda"] == "$" and dflt["moneda_nombre"] == "USD", "país desconocido -> default USD")
    base = CX.construir_contexto_base("Perú", "S/", "Español", "Tono formal")
    check("Perú" in base and "S/" in base and "Tono formal" in base, "contexto_base arma el bloque")
    txt, err = CX.validar_input("   ")
    check(txt is None and err == "Campo vacío", "input vacío -> error")
    txt, err = CX.validar_input("hola <script>alert(1)</script>")
    check(err is None and "<script" not in txt, "validar_input quita <script")
    check(CX._sanitizar("a<b>c") == "abc", "_sanitizar quita <>")


def test_gemelo():
    print("\n[8] Gemelo Digital — motor matemático")
    # Curva de saturación
    check(abs(GM.ventas_canal(0, 100, 50)) < 1e-9, "curva: 0 gasto -> 0 ventas")
    check(GM.ventas_canal(1e9, 100, 50) > 99.9, "curva: gasto alto -> satura al techo")
    # Elasticidad
    check(abs(GM.elasticidad_factor(10, 10, 1.2) - 1.0) < 1e-9, "elasticidad: precio=ref -> 1.0")
    check(GM.elasticidad_factor(12, 10, 1.2) < 1.0, "subir precio baja demanda")
    check(GM.elasticidad_factor(8, 10, 1.2) > 1.0, "bajar precio sube demanda")
    # Validación
    ok, _ = GM.validar_semanas([{"gasto": {"Meta": -5}, "ventas": 10, "precio": 20, "costo": 5}])
    check(not ok, "rechaza gasto negativo")
    ok, _ = GM.validar_semanas([{"gasto": {"Meta": 100}, "ventas": 10, "precio": 20, "costo": 25}])
    check(not ok, "rechaza costo > precio")
    # Datos suficientes
    semanas = [{"gasto": {"Meta": 100, "Google": 50, "TikTok": 30}, "ventas": 40, "precio": 20, "costo": 8}
               for _ in range(5)]
    check(GM.datos_suficientes(semanas) and not GM.datos_suficientes(semanas[:3]), "umbral de 4 semanas")
    # Calibración + Monte Carlo determinista
    params = GM.calibrar(semanas)
    check(params["fuente"] == "datos" and abs(params["precio_ref"] - 20) < 1e-6, "calibra con datos reales")
    mc = GM.monte_carlo(params, {"Meta": 100, "Google": 50, "TikTok": 30}, 20, costo=8, n=500, seed=42)
    check(mc["ventas"]["p10"] <= mc["ventas"]["p50"] <= mc["ventas"]["p90"], "rango p10<=p50<=p90")
    check(30 <= mc["ventas"]["p50"] <= 50, "p50 cerca de las ventas observadas (~40)")
    # Reparto óptimo suma el presupuesto
    dist = GM.distribuir_optimo(params, 300, 20)
    check(abs(sum(dist["asignacion"].values()) - 300) < 1.0, "reparto óptimo suma el presupuesto")
    # Benchmark cold start
    pb = GM.params_benchmark("retail_moda", 20, {"Meta": 100, "Google": 50, "TikTok": 30})
    check(pb["fuente"] == "benchmark" and pb["elasticidad"] == 1.4, "benchmark de sector")
    # Precisión
    check(GM.precision(30, 50, 40) == 100.0, "real dentro del rango -> 100%")
    check(GM.precision(30, 50, 55) < 100.0, "real fuera del rango -> <100%")
    # Tarjeta PNG
    png, err = GMC.generar_tarjeta("Café Chero", 36, 44, "42 (2026)", moneda="S/", ingresos_p50=800)
    check(err is None and png and png[:8] == b"\x89PNG\r\n\x1a\n", "tarjeta genera PNG válido")
    # Árbitro + veredicto (nunca contradice los números)
    mc = GM.monte_carlo(params, {"Meta": 100, "Google": 50, "TikTok": 30}, 20, costo=8, n=400, seed=7)
    ver = GM.veredicto(mc)
    check(ver["icono"] in ("✅", "⚠️", "❌") and ver["roas"] is not None, "veredicto da icono + ROAS")
    check((ver["icono"] == "✅") == (mc["utilidad"]["p10"] >= 0), "✅ sólo si hasta el peor caso gana (coherente)")
    mc_malo = GM.monte_carlo(params, {"Meta": 5000, "Google": 0, "TikTok": 0}, 20, costo=18, n=200, seed=1)
    check(GM.veredicto(mc_malo)["icono"] == "❌", "gasto enorme sin retorno -> ❌")
    esc = GM.escenarios(mc)
    check(set(esc) == {"pesimista", "base", "optimista"}, "escenarios: 3 niveles")
    proy = GM.proyeccion(mc)
    check("6m" in proy and "12m" in proy and proy["12m"]["ingresos"] > proy["6m"]["ingresos"], "proyección 6m/12m")
    # Simulador de decisiones: 4 tipos, mismo formato
    _pp = GM.calibrar(params if False else semanas, "food_beverage")  # usa semanas
    _pp["precio_ref"] = 20
    _plan = {"Meta": 120, "Google": 60, "TikTok": 40}
    _decs = [
        GM.sim_presupuesto(_pp, 300, 20, 8, seed=1),
        GM.sim_precio(_pp, 20, 24, _plan, 8, seed=1),
        GM.sim_producto_nuevo(30, 12, 400, 50, seed=1),
        GM.sim_zona(25, 10, 2000, 8000, 3, seed=1),
    ]
    _campos = ("tipo", "ventas", "ingresos", "utilidad", "veredicto", "escenarios", "proyeccion", "fuente")
    check(all(all(k in d for k in _campos) for d in _decs), "4 decisiones devuelven formato uniforme")
    check(_decs[0]["tipo"] == "presupuesto" and "asignacion" in _decs[0], "presupuesto trae asignación")
    check(_decs[1]["tipo"] == "precio" and "comparacion" in _decs[1], "precio trae comparación actual vs nuevo")
    check(_decs[2]["fuente"] == "supuestos" and _decs[3]["fuente"] == "supuestos", "producto/zona por supuestos")
    # Agentes-persona (comprador/competidor/mercado) — no inventan, citan números
    _cap = []

    def _fake_gt(prompt, max_out=900, modelo=None, temperatura=None):
        _cap.append((modelo, temperatura, prompt))
        return "opinión"
    _ops = GMP.opiniones_equipo(_fake_gt, _decs[1], "Café", "food_beverage", "S/", "Lima", "Miraflores")
    check(set(_ops) == {"comprador", "competidor", "mercado"} and all(_ops.values()), "3 personas responden")
    check(all(m == "gemini-2.5-flash-lite" and t == 0.3 for m, t, _ in _cap), "personas usan flash-lite + temp 0.3")
    check("Veredicto" in _cap[0][2] and "Miraflores" in _cap[0][2], "personas citan números y usan el distrito")
    # Mapa de efectividad por zona
    _mapa = GM.mapa_zonas([
        {"nombre": "Buena", "clientes": 9000, "penetracion": 4, "inversion": 1500},
        {"nombre": "Mala", "clientes": 500, "penetracion": 1, "inversion": 3000},
        {"nombre": "x", "clientes": 0, "penetracion": 5, "inversion": 100},  # se descarta
    ], precio=25, costo=10, seed=3)
    check(len(_mapa["zonas"]) == 2, "mapa descarta zonas sin clientes")
    check(_mapa["zonas"][0]["utilidad_p50"] >= _mapa["zonas"][1]["utilidad_p50"], "mapa ordena por utilidad")
    check(_mapa["mejor"] == "Buena" and _mapa["zonas"][0]["icono"] in ("🟢", "🟡"), "mejor zona identificada")
    check(_mapa["zonas"][1]["icono"] == "🔴", "zona que pierde -> 🔴")
    # Piso de ventas base (negocio establecido vs nuevo)
    _sem_est = [{"gasto": {"Meta": 5.6, "Google": 7, "TikTok": 1.4}, "ventas": 148, "precio": 1, "costo": 0.6},
                {"gasto": {"Meta": 5.6, "Google": 7, "TikTok": 1.4}, "ventas": 181, "precio": 1, "costo": 0.6}]
    _p_base = GM.calibrar(_sem_est, "ecommerce_general", ventas_base=130)
    _p_nobase = GM.calibrar(_sem_est, "ecommerce_general", ventas_base=0)
    check(_p_base["base"] == 130 and _p_nobase["base"] == 0.0, "la base se guarda en params")
    # A 0 de ads: con base vende ~130; sin base vende ~0 (el punto del arreglo)
    check(GM.predecir_ventas(_p_base, {"Meta": 0, "Google": 0, "TikTok": 0}, 1) >= 120, "con base: vende sin ads")
    check(GM.predecir_ventas(_p_nobase, {"Meta": 0, "Google": 0, "TikTok": 0}, 1) < 5, "sin base: 0 ventas sin ads")
    check(GM.calibrar(semanas, "food_beverage")["base"] == 0.0, "base por defecto = 0 (negocio nuevo)")
    # Volatilidad adaptativa: el rango se ensancha según la variación real de ventas
    _sem_volatil = [{"gasto": {"Meta": 6, "Google": 7, "TikTok": 1.4}, "ventas": 148, "precio": 1, "costo": 0.78},
                    {"gasto": {"Meta": 6, "Google": 7, "TikTok": 1.4}, "ventas": 181, "precio": 1, "costo": 0.78}]
    _pv = GM.calibrar(_sem_volatil, "ecommerce_general", ventas_base=120)
    check(0.08 <= _pv["volatilidad"] <= 0.40, "calcula volatilidad real de las ventas")
    _rng = GM.monte_carlo(_pv, {"Meta": 6, "Google": 7, "TikTok": 1.4}, 1, costo=0.78, n=2000, seed=11)["ventas"]
    check(_rng["p10"] <= 148 <= _rng["p90"] and _rng["p10"] <= 181 <= _rng["p90"],
          "el rango honesto contiene ambos meses reales")

    # ── MODO CAMPAÑA (general para todos los usuarios) ──────────────────────
    # Sin campañas marcadas -> multiplicador por benchmark del sector
    _p_sinc = GM.calibrar(_sem_est, "ecommerce_general", ventas_base=120)
    check(_p_sinc["campana"]["fuente"] == "benchmark" and _p_sinc["campana"]["multiplicador"] > 1.0,
          "sin campañas marcadas usa benchmark del sector")
    # Con una campaña real marcada (vende ~2x) -> aprende el multiplicador propio
    _sem_camp = _sem_est + [{"gasto": {"Meta": 6, "Google": 7, "TikTok": 2}, "ventas": 330,
                             "precio": 1, "costo": 0.6, "evento": "Fiestas Patrias"}]
    _p_conc = GM.calibrar(_sem_camp, "ecommerce_general", ventas_base=120)
    check(_p_conc["campana"]["fuente"] == "datos" and _p_conc["campana"]["n"] == 1,
          "aprende el multiplicador de las campañas marcadas del negocio")
    check(1.6 <= _p_conc["campana"]["multiplicador"] <= 2.5, "multiplicador aprendido ~2x (330 vs ~165)")
    # La semana de campaña NO infla las curvas de un mes normal
    _norm = GM.monte_carlo(_p_conc, {"Meta": 5.6, "Google": 7, "TikTok": 1.4}, 1, costo=0.6, n=1500, seed=5)
    check(_norm["ventas"]["p50"] <= 230, "un mes normal sigue siendo normal (no contaminado por la campaña)")
    # sim_campana vende claramente más que un mes normal y mantiene el formato
    _rc = GM.sim_campana(_p_conc, 15.4, 1, costo=0.6, n=1500, seed=5)
    check(all(k in _rc for k in _campos) and _rc["tipo"] == "campana", "sim_campana devuelve formato uniforme")
    check(_rc["ventas"]["p50"] > _norm["ventas"]["p50"] * 1.3, "campaña proyecta bastante más que mes normal")
    check(_rc["mult_fuente"] == "datos" and _rc["multiplicador"] > 1.0, "campaña reporta su multiplicador y fuente")
    # Intensidad 0 -> vuelve a mes normal (multiplicador ~1)
    _rc0 = GM.sim_campana(_p_conc, 15.4, 1, costo=0.6, intensidad=0.0, n=800, seed=5)
    check(abs(_rc0["multiplicador"] - 1.0) < 1e-6, "intensidad 0 = mes normal (multiplicador 1.0)")


def test_meta_ads():
    print("\n[9] Meta Ads (OAuth + gasto por mes)")
    _secrets = {"META_APP_ID": "ID", "META_APP_SECRET": "SEC",
                "META_OAUTH_REDIRECT_URI": "https://app/"}
    check(MA.oauth_configurado(_secrets) and not MA.oauth_configurado({}),
          "detecta si están los secrets de Meta")
    _url = MA.build_auth_url(_secrets, state="x")
    check("dialog/oauth" in _url and "ads_read" in _url and "client_id=ID" in _url,
          "arma la URL de autorización con ads_read")

    from datetime import datetime as _dt
    _now = _dt.now()
    _ym_now = _now.strftime("%Y-%m")
    _lm, _ly = (_now.month - 1, _now.year) if _now.month > 1 else (12, _now.year - 1)
    _ym_last = f"{_ly:04d}-{_lm:02d}"

    def router_meta(method, url, kw):
        if "/insights" in url:
            return FakeResp(200, {"data": [
                {"date_start": _ym_now + "-01", "spend": "300.50",
                 "purchase_roas": [{"action_type": "omni_purchase", "value": "2.5"}]},
                {"date_start": _ym_last + "-01", "spend": "150.00",
                 "purchase_roas": [{"action_type": "omni_purchase", "value": "3.1"}]},
            ]})
        if "/me/adaccounts" in url:
            return FakeResp(200, {"data": [
                {"account_id": "123", "name": "Wasai Ads", "currency": "PEN"}]})
        return FakeResp(500, {}, "err")
    MA.requests = FakeRequests(router_meta)

    _cuentas, _e1 = MA.listar_cuentas_ads("TOK")
    check(_e1 is None and _cuentas and _cuentas[0]["id"] == "123" and _cuentas[0]["moneda"] == "PEN",
          "lista cuentas de ads")
    _filas, _e2 = MA.fetch_ad_spend_by_month("act_123", "TOK", meses=3)
    _d = {f["ym"]: f for f in _filas}
    check(_e2 is None and _d.get(_ym_now, {}).get("gasto") == 300.5, "gasto del mes correcto")
    check(_d.get(_ym_now, {}).get("roas") == 2.5, "ROAS del mes correcto")
    check(_d.get(_ym_last, {}).get("gasto") == 150.0, "gasto del mes anterior")
    check(len(_filas) == 3 and all("mes" in f for f in _filas), "devuelve 3 meses con etiqueta")


if __name__ == "__main__":
    for _t in (test_oauth_helpers, test_token_refresh, test_ga4_report,
               test_listar_propiedades, test_stores, test_agents, test_context,
               test_gemelo, test_meta_ads):
        _t()
    print("\n" + ("=" * 50))
    if _fallos:
        print(f"❌ {len(_fallos)} fallo(s): " + "; ".join(_fallos))
        sys.exit(1)
    print("✅ TODOS LOS TESTS PASARON")
