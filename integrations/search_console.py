"""Google Search Console — SEO real (keywords y posiciones del PROPIO sitio).

Fase 1 del SEO de verdad: en vez de inventar keywords "del modelo", trae lo que
Google REALMENTE registra del sitio del usuario:
  - Palabras por las que la gente lo encuentra (consultas reales).
  - Clics, impresiones, CTR y posición promedio de cada una.
  - Las páginas que más tráfico orgánico reciben.

Reusa la MISMA app OAuth de Google que Analytics (no hay que registrar otra),
solo con un scope adicional (webmasters.readonly) y la "Search Console API"
habilitada en Google Cloud.

Todas las funciones de red devuelven (data, error); nunca inventan datos.
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote, urlencode

import requests

# Reusamos el canje/renovación de tokens de Analytics (misma app OAuth).
from .analytics import (  # noqa: F401
    AUTH_ENDPOINT,
    access_token_valido,
    exchange_code,
    oauth_configurado,
    parsear_token_guardado,
    serializar_bundle,
)

SC_API = "https://www.googleapis.com/webmasters/v3"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
_TIMEOUT = 20


def build_auth_url(secrets: dict, state: str = "tentaklsc") -> str:
    """URL para autorizar el acceso de SOLO LECTURA a Search Console.
    Reusa la misma app OAuth que Analytics, con el scope de webmasters."""
    params = {
        "client_id": secrets.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        "redirect_uri": secrets.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip(),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",      # para recibir refresh_token
        "prompt": "consent",           # fuerza refresh_token siempre
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def listar_sitios(access_token: str):
    """Lista los sitios verificados en Search Console del usuario.
    Devuelve (lista, error). lista: [{"url": "https://...", "permiso": "..."}]."""
    try:
        r = requests.get(f"{SC_API}/sites",
                         headers={"Authorization": f"Bearer {access_token}"}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return [], f"Search Console respondió {r.status_code}: {str(r.text)[:200]}"
        sitios = []
        for s in (r.json() or {}).get("siteEntry", []):
            url = (s.get("siteUrl") or "").strip()
            if url:
                sitios.append({"url": url, "permiso": s.get("permissionLevel", "")})
        return sitios, None
    except Exception as ex:  # noqa: BLE001
        return [], f"Error de red con Search Console: {ex}"


def _fila(row):
    """Normaliza una fila del reporte (clics, impresiones, CTR %, posición)."""
    return {
        "clicks": int(row.get("clicks", 0) or 0),
        "impressions": int(row.get("impressions", 0) or 0),
        "ctr": round(float(row.get("ctr", 0) or 0) * 100, 1),       # 0.07 -> 7.0 %
        "position": round(float(row.get("position", 0) or 0), 1),
    }


def _query(site_url, access_token, body):
    """Una consulta al Search Analytics API. Devuelve (rows, error)."""
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    # El siteUrl va URL-encodeado en la ruta (incluye ':' y '/').
    url = f"{SC_API}/sites/{quote(site_url, safe='')}/searchAnalytics/query"
    r = requests.post(url, json=body, headers=headers, timeout=_TIMEOUT)
    if r.status_code != 200:
        return None, f"Search Console respondió {r.status_code}: {str(r.text)[:200]}"
    return (r.json() or {}).get("rows", []), None


def fetch_search_analytics(site_url: str, access_token: str, dias: int = 28, limite: int = 25):
    """Trae el panorama SEO real del sitio en los últimos `dias` días.

    Devuelve (data, error). data = {
        "rango": {"desde","hasta"},
        "totales": {"clicks","impressions","ctr","position"},
        "keywords": [{"query","clicks","impressions","ctr","position"}, ...],
        "paginas":  [{"pagina","clicks","impressions","ctr","position"}, ...],
    }
    Nunca inventa datos: si la API falla, data=None.
    """
    site_url = (site_url or "").strip()
    if not site_url:
        return None, "Falta la URL del sitio de Search Console."
    # Search Console tiene ~2-3 días de rezago; igual pedimos hasta hoy y la API
    # devuelve lo que tenga.
    hasta = date.today()
    desde = hasta - timedelta(days=max(1, int(dias)))
    rango = {"startDate": desde.isoformat(), "endDate": hasta.isoformat()}

    # 1) Totales (sin dimensiones)
    rows_tot, err = _query(site_url, access_token, dict(rango))
    if err:
        return None, err
    totales = _fila(rows_tot[0]) if rows_tot else {
        "clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}

    # 2) Keywords (dimension query)
    rows_kw, err = _query(site_url, access_token,
                          dict(rango, dimensions=["query"], rowLimit=int(limite)))
    if err:
        return None, err
    keywords = []
    for row in rows_kw:
        d = _fila(row)
        d["query"] = (row.get("keys") or [""])[0]
        keywords.append(d)

    # 3) Páginas (dimension page)
    rows_pg, err = _query(site_url, access_token,
                          dict(rango, dimensions=["page"], rowLimit=int(limite)))
    if err:
        return None, err
    paginas = []
    for row in rows_pg:
        d = _fila(row)
        d["pagina"] = (row.get("keys") or [""])[0]
        paginas.append(d)

    data = {
        "rango": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "totales": totales,
        "keywords": keywords,
        "paginas": paginas,
    }
    return data, None
