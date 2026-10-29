"""SEO fase 1 (gratis, sin IA): auditoría on-page + ideas de keywords reales.

Tres piezas, todas con datos REALES (nunca inventados):
  1. auditar_onpage(html, url) — diagnóstico técnico de una página con un score
     por REGLAS (no lo decide la IA): title, meta, H1, imágenes sin alt, viewport,
     canonical, cantidad de texto, etc. Devuelve (data, error).
  2. sugerencias_google(termino) — ideas de keywords del Autocompletar REAL de
     Google (lo que la gente realmente escribe). Devuelve (lista, error).
  3. estacionalidad(termino) — interés en el tiempo vía Google Trends, con
     fallback claro si Trends se bloquea en la nube. Devuelve (data, error).

Red mockeable: usa el `requests` a nivel de módulo (como analytics/stores).
"""
from __future__ import annotations

import requests

_TIMEOUT = 12
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# ──────────────────────────────────────────────────────────────────────────
# 1) Auditoría on-page (score por reglas, sin IA)
# ──────────────────────────────────────────────────────────────────────────
def auditar_onpage(html: str, url: str = ""):
    """Analiza el HTML de una página y devuelve (data, error).

    El score (0-100) sale de REGLAS objetivas, no de la IA, para no inventar.
    data = {
        "url", "title", "title_len", "meta", "meta_len",
        "h1": [...], "h1_count", "h2_count",
        "img_total", "img_sin_alt", "palabras",
        "canonical", "lang", "viewport", "https",
        "score", "issues": [{"nivel","msg"}]
    }
    nivel ∈ {"critico","importante","menor"} (peso 20/10/4 en el score).
    """
    if not (html or "").strip():
        return None, "No hay HTML para analizar."
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return None, "Falta beautifulsoup4 (está en requirements.txt — redeploy)."

    soup = BeautifulSoup(html, "html.parser")
    for _t in soup(["script", "style", "noscript"]):
        _t.decompose()

    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    meta = ""
    _m = soup.find("meta", attrs={"name": "description"})
    if _m:
        meta = (_m.get("content") or "").strip()
    h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    h2_count = len(soup.find_all("h2"))
    imgs = soup.find_all("img")
    img_sin_alt = sum(1 for i in imgs if not (i.get("alt") or "").strip())
    palabras = len(soup.get_text(" ", strip=True).split())
    canonical = ""
    _c = soup.find("link", attrs={"rel": lambda v: v and "canonical" in (v if isinstance(v, list) else [v])})
    if _c:
        canonical = (_c.get("href") or "").strip()
    lang = ""
    _html_tag = soup.find("html")
    if _html_tag:
        lang = (_html_tag.get("lang") or "").strip()
    viewport = bool(soup.find("meta", attrs={"name": "viewport"}))
    https = (url or "").strip().lower().startswith("https://")

    issues = []

    def _add(nivel, msg):
        issues.append({"nivel": nivel, "msg": msg})

    # Title
    if not title:
        _add("critico", "Falta el <title> (es lo primero que ve Google).")
    elif len(title) < 30:
        _add("menor", f"El título es muy corto ({len(title)} car.); ideal 30–60.")
    elif len(title) > 60:
        _add("menor", f"El título es muy largo ({len(title)} car.); Google corta ~60.")
    # Meta description
    if not meta:
        _add("importante", "Falta la meta descripción (el texto bajo el título en Google).")
    elif len(meta) < 70:
        _add("menor", f"La meta descripción es corta ({len(meta)} car.); ideal 70–160.")
    elif len(meta) > 160:
        _add("menor", f"La meta descripción es larga ({len(meta)} car.); Google corta ~160.")
    # H1
    if len(h1) == 0:
        _add("critico", "No hay <h1> (el encabezado principal de la página).")
    elif len(h1) > 1:
        _add("importante", f"Hay {len(h1)} <h1>; debería haber solo uno.")
    # Imágenes sin alt
    if img_sin_alt > 0:
        _add("menor", f"{img_sin_alt} de {len(imgs)} imágenes no tienen texto alternativo (alt).")
    # Contenido delgado
    if palabras < 300:
        _add("importante", f"Poco contenido ({palabras} palabras); Google premia páginas con más texto útil.")
    # Mobile
    if not viewport:
        _add("importante", "Falta la etiqueta viewport (la web no se verá bien en celular).")
    # Idioma
    if not lang:
        _add("menor", "El <html> no declara idioma (atributo lang).")
    # HTTPS
    if url and not https:
        _add("importante", "La página no usa HTTPS (candado de seguridad).")

    _peso = {"critico": 20, "importante": 10, "menor": 4}
    score = 100 - sum(_peso[i["nivel"]] for i in issues)
    score = max(0, min(100, score))

    data = {
        "url": url, "title": title, "title_len": len(title),
        "meta": meta, "meta_len": len(meta),
        "h1": h1, "h1_count": len(h1), "h2_count": h2_count,
        "img_total": len(imgs), "img_sin_alt": img_sin_alt, "palabras": palabras,
        "canonical": canonical, "lang": lang, "viewport": viewport, "https": https,
        "score": score, "issues": issues,
    }
    return data, None


def fetch_y_auditar(url: str):
    """Descarga la URL y la audita. Devuelve (data, error). No inventa datos."""
    url = (url or "").strip()
    if not url:
        return None, "Falta la URL."
    if not url.startswith("http"):
        url = "https://" + url
    try:
        r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": _UA})
        if r.status_code in (401, 403):
            return None, (f"Esa página bloquea el acceso automático (error {r.status_code}). "
                          "Puedes pegar el contenido a mano en la Auditoría SEO.")
        if r.status_code == 404:
            return None, "Esa página no existe (404). Revisa la URL."
        if r.status_code != 200:
            return None, f"La página respondió {r.status_code}."
        return auditar_onpage(r.text, url)
    except requests.exceptions.Timeout:
        return None, "La página tardó demasiado (timeout). Intenta de nuevo."
    except requests.exceptions.RequestException:
        return None, "No se pudo acceder a esa URL. Revisa que esté bien escrita (ej: mitienda.com)."


# ──────────────────────────────────────────────────────────────────────────
# 2) Ideas de keywords reales — Google Autocomplete
# ──────────────────────────────────────────────────────────────────────────
_AUTOCOMPLETE = "https://suggestqueries.google.com/complete/search"


def sugerencias_google(termino: str, hl: str = "es", gl: str = "PE", max_n: int = 10):
    """Devuelve (lista, error) con lo que Google autocompleta para `termino`.

    Son búsquedas REALES de la gente (no inventadas por IA). Ideal para ideas de
    keywords y de contenido. hl=idioma, gl=país (PE, MX, CO, CL, AR, ES, US...).
    """
    termino = (termino or "").strip()
    if not termino:
        return [], "Escribe una palabra o frase base."
    try:
        r = requests.get(_AUTOCOMPLETE, params={
            "client": "firefox", "hl": hl, "gl": gl, "q": termino,
        }, timeout=_TIMEOUT, headers={"User-Agent": _UA})
        if r.status_code != 200:
            return [], f"Google respondió {r.status_code}."
        datos = r.json()
        # Formato firefox: [termino, [sug1, sug2, ...]]
        sugs = datos[1] if isinstance(datos, list) and len(datos) > 1 else []
        limpio = []
        for s in sugs:
            s = (s or "").strip()
            if s and s.lower() != termino.lower() and s not in limpio:
                limpio.append(s)
            if len(limpio) >= max_n:
                break
        return limpio, None
    except ValueError:
        return [], "Google devolvió una respuesta inesperada."
    except requests.exceptions.RequestException:
        return [], "No se pudo consultar Google ahora. Intenta de nuevo en un momento."


# ──────────────────────────────────────────────────────────────────────────
# 3) Estacionalidad — Google Trends (con fallback claro)
# ──────────────────────────────────────────────────────────────────────────
def estacionalidad(termino: str, geo: str = "PE"):
    """Interés en el tiempo (12 meses) vía Google Trends. Devuelve (data, error).

    Trends se bloquea seguido en servidores de nube (429). Por eso SIEMPRE
    devolvemos un error claro en vez de dejar la pantalla vacía.
    data = {"serie": [{"mes","valor"}], "pico": "YYYY-MM", "valle": "YYYY-MM"}
    """
    termino = (termino or "").strip()
    if not termino:
        return None, "Escribe un término para ver su estacionalidad."
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="es", tz=300)
        pt.build_payload([termino], timeframe="today 12-m", geo=geo)
        df = pt.interest_over_time()
        if df is None or df.empty or termino not in df.columns:
            return None, ("Google Trends no devolvió datos para ese término "
                          "(prueba uno más general o cambia el país).")
        serie = [{"mes": str(idx)[:7], "valor": int(v)}
                 for idx, v in df[termino].items()]
        if not serie:
            return None, "Google Trends no devolvió datos."
        _pico = max(serie, key=lambda x: x["valor"])
        _valle = min(serie, key=lambda x: x["valor"])
        return {"serie": serie, "pico": _pico["mes"], "valle": _valle["mes"]}, None
    except Exception as ex:  # noqa: BLE001 - pytrends lanza varios tipos
        _m = str(ex)
        if "429" in _m or "quota" in _m.lower() or "rate" in _m.lower():
            return None, ("Google Trends está limitando las consultas ahora mismo "
                          "(muy común en la nube). Intenta de nuevo en unos minutos.")
        return None, "Google Trends no está disponible en este momento. Intenta más tarde."
