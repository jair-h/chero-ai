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
            {"value": "0.45"}, {"value": "95"}, {"value": "2.5"}, {"value": "0.62"}]}]},
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


if __name__ == "__main__":
    for _t in (test_oauth_helpers, test_token_refresh, test_ga4_report,
               test_listar_propiedades, test_stores, test_agents, test_context,
               test_gemelo):
        _t()
    print("\n" + ("=" * 50))
    if _fallos:
        print(f"❌ {len(_fallos)} fallo(s): " + "; ".join(_fallos))
        sys.exit(1)
    print("✅ TODOS LOS TESTS PASARON")
