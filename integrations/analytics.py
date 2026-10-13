"""Google Analytics 4 — OAuth real + extracción completa de datos.

Reemplaza el enfoque viejo (API Key + datos "demo" falsos). Ahora:
  1. OAuth de un clic: el usuario hace "Conectar" e inicia sesión con Google.
     Tentakl se registra UNA vez como app OAuth; el usuario no crea nada.
  2. Trae el panorama COMPLETO (totales, canales, páginas top, dispositivos,
     países y serie diaria), tal cual lo reporta GA4 — sin inventar nada.

IMPORTANTE: el GA4 Data API usa el ID NUMÉRICO de propiedad (ej. 123456789),
NO el measurement ID "G-XXXXXXX". Por eso antes fallaba y caía al modo demo.

Credenciales (en st.secrets o variables de entorno):
    GOOGLE_OAUTH_CLIENT_ID
    GOOGLE_OAUTH_CLIENT_SECRET
    GOOGLE_OAUTH_REDIRECT_URI   (la URL pública de tu app en Streamlit Cloud)

Todas las funciones de red devuelven (data, error) para que la UI decida
qué mostrar; nunca devuelven datos inventados.
"""
from __future__ import annotations

import json
import time

import requests

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DATA_API = "https://analyticsdata.googleapis.com/v1beta"
ADMIN_API = "https://analyticsadmin.googleapis.com/v1beta"
SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_TIMEOUT = 20


# ──────────────────────────────────────────────────────────────────────────
# OAuth
# ──────────────────────────────────────────────────────────────────────────
def oauth_configurado(secrets: dict) -> bool:
    """True si están las credenciales OAuth necesarias."""
    return bool(
        (secrets.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
        and (secrets.get("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
        and (secrets.get("GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    )


def build_auth_url(secrets: dict, state: str = "tentakl") -> str:
    """Construye la URL a la que mandamos al usuario para que autorice."""
    from urllib.parse import urlencode

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


def exchange_code(secrets: dict, code: str):
    """Canjea el ?code= por un bundle de tokens. Devuelve (bundle, error)."""
    try:
        r = requests.post(TOKEN_ENDPOINT, data={
            "code": code,
            "client_id": secrets.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
            "client_secret": secrets.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
            "redirect_uri": secrets.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip(),
            "grant_type": "authorization_code",
        }, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None, f"Error al canjear el código ({r.status_code}): {r.text[:200]}"
        tok = r.json()
        bundle = {
            "access_token": tok.get("access_token", ""),
            "refresh_token": tok.get("refresh_token", ""),
            "expiry": time.time() + int(tok.get("expires_in", 3600)),
        }
        return bundle, None
    except Exception as ex:  # noqa: BLE001
        return None, f"Error de red en OAuth: {ex}"


def refresh_access_token(secrets: dict, refresh_token: str):
    """Renueva el access_token usando el refresh_token. Devuelve (bundle, error)."""
    try:
        r = requests.post(TOKEN_ENDPOINT, data={
            "refresh_token": refresh_token,
            "client_id": secrets.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
            "client_secret": secrets.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
            "grant_type": "refresh_token",
        }, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None, f"Error al renovar token ({r.status_code}): {r.text[:200]}"
        tok = r.json()
        bundle = {
            "access_token": tok.get("access_token", ""),
            "refresh_token": refresh_token,  # Google no reenvía el refresh
            "expiry": time.time() + int(tok.get("expires_in", 3600)),
        }
        return bundle, None
    except Exception as ex:  # noqa: BLE001
        return None, f"Error de red al renovar token: {ex}"


# ── Serialización del bundle para guardarlo en Supabase (columna access_token)
def serializar_bundle(bundle: dict) -> str:
    return json.dumps(bundle)


def parsear_token_guardado(valor: str) -> dict:
    """Lee lo guardado en Supabase. Soporta el bundle JSON nuevo y, por
    compatibilidad, una API key vieja en texto plano."""
    valor = (valor or "").strip()
    if not valor:
        return {}
    try:
        data = json.loads(valor)
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001 - no era JSON: era una API key vieja
        return {"api_key_legacy": valor}
    return {}


def access_token_valido(secrets: dict, bundle: dict):
    """Devuelve (access_token, bundle_actualizado, error), renovando si expiró."""
    if not bundle:
        return None, bundle, "No hay token guardado."
    # Token aún vigente (con 60s de margen)
    if bundle.get("access_token") and float(bundle.get("expiry", 0)) > time.time() + 60:
        return bundle["access_token"], bundle, None
    # Expiró: renovar con refresh_token
    if bundle.get("refresh_token"):
        nuevo, err = refresh_access_token(secrets, bundle["refresh_token"])
        if err:
            return None, bundle, err
        return nuevo["access_token"], nuevo, None
    return None, bundle, "Token expirado y sin refresh_token; vuelve a conectar."


# ──────────────────────────────────────────────────────────────────────────
# Admin API — listar propiedades GA4 del usuario (para elegir el ID numérico)
# ──────────────────────────────────────────────────────────────────────────
def listar_propiedades(access_token: str):
    """Lista las propiedades GA4 accesibles. Devuelve (lista, error).

    lista: [{"id": "123456789", "nombre": "Mi Sitio"}]
    """
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        # 1) cuentas
        r_acc = requests.get(f"{ADMIN_API}/accounts", headers=headers, timeout=_TIMEOUT)
        if r_acc.status_code != 200:
            return [], f"Error listando cuentas ({r_acc.status_code}): {r_acc.text[:200]}"
        props = []
        for acc in r_acc.json().get("accounts", []):
            acc_name = acc.get("name", "")  # "accounts/123"
            r_prop = requests.get(
                f"{ADMIN_API}/properties",
                params={"filter": f"parent:{acc_name}"},
                headers=headers, timeout=_TIMEOUT,
            )
            if r_prop.status_code != 200:
                continue
            for p in r_prop.json().get("properties", []):
                pid = (p.get("name", "") or "").split("/")[-1]  # "properties/123" -> "123"
                props.append({"id": pid, "nombre": p.get("displayName", pid)})
        return props, None
    except Exception as ex:  # noqa: BLE001
        return [], f"Error de red con Admin API: {ex}"


# ──────────────────────────────────────────────────────────────────────────
# Data API — reporte COMPLETO (sin demo, tal cual GA4)
# ──────────────────────────────────────────────────────────────────────────
def _fila_valor(row, i):
    return row["metricValues"][i]["value"]


def fetch_ga4_report(property_id: str, access_token: str, start_date: str = "30daysAgo"):
    """Trae el panorama completo de una propiedad GA4.

    property_id: ID NUMÉRICO (ej. "123456789"), no "G-XXXX".
    Devuelve (data, error). data nunca es inventado: si falla, data=None.
    """
    pid = (property_id or "").strip()
    if not pid:
        return None, "Falta el ID numérico de propiedad GA4."
    if pid.upper().startswith("G-"):
        return None, ("Ese es el measurement ID (G-XXXX). El Data API necesita el "
                      "ID NUMÉRICO de la propiedad (ej. 123456789).")
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    rango = [{"startDate": start_date, "endDate": "today"}]
    cuerpo = {"requests": [
        # 0) Totales
        {"dateRanges": rango, "metrics": [
            {"name": "sessions"}, {"name": "activeUsers"}, {"name": "newUsers"},
            {"name": "screenPageViews"}, {"name": "bounceRate"},
            {"name": "averageSessionDuration"}, {"name": "screenPageViewsPerSession"},
            {"name": "engagementRate"},
        ]},
        # 1) Por canal
        {"dateRanges": rango, "dimensions": [{"name": "sessionDefaultChannelGroup"}],
         "metrics": [{"name": "sessions"}],
         "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}]},
        # 2) Páginas top
        {"dateRanges": rango, "dimensions": [{"name": "pagePath"}],
         "metrics": [{"name": "screenPageViews"}],
         "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
         "limit": 10},
        # 3) Dispositivos
        {"dateRanges": rango, "dimensions": [{"name": "deviceCategory"}],
         "metrics": [{"name": "sessions"}]},
        # 4) Países
        {"dateRanges": rango, "dimensions": [{"name": "country"}],
         "metrics": [{"name": "sessions"}],
         "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}], "limit": 10},
        # 5) Serie diaria
        {"dateRanges": rango, "dimensions": [{"name": "date"}],
         "metrics": [{"name": "sessions"}, {"name": "activeUsers"}],
         "orderBys": [{"dimension": {"dimensionName": "date"}}]},
    ]}
    try:
        r = requests.post(f"{DATA_API}/properties/{pid}:batchRunReports",
                          json=cuerpo, headers=headers, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None, f"GA4 respondió {r.status_code}: {r.text[:300]}"
        reps = r.json().get("reports", [])
        if len(reps) < 6:
            return None, "Respuesta incompleta de GA4."

        # 0) Totales
        tot_rows = reps[0].get("rows", [])
        if tot_rows:
            tv = tot_rows[0]["metricValues"]
            totales = {
                "sessions": int(float(tv[0]["value"])),
                "activeUsers": int(float(tv[1]["value"])),
                "newUsers": int(float(tv[2]["value"])),
                "pageViews": int(float(tv[3]["value"])),
                "bounceRate": round(float(tv[4]["value"]) * 100, 1),
                "avgDuration": int(float(tv[5]["value"])),
                "pagesPerSession": round(float(tv[6]["value"]), 2),
                "engagementRate": round(float(tv[7]["value"]) * 100, 1),
            }
        else:
            totales = {"sessions": 0, "activeUsers": 0, "newUsers": 0, "pageViews": 0,
                       "bounceRate": 0.0, "avgDuration": 0, "pagesPerSession": 0.0,
                       "engagementRate": 0.0}

        def _dim_dict(rep):
            out = {}
            for row in rep.get("rows", []):
                out[row["dimensionValues"][0]["value"]] = int(float(_fila_valor(row, 0)))
            return out

        data = {
            "totales": totales,
            "canales": _dim_dict(reps[1]),
            "paginas": [
                {"ruta": row["dimensionValues"][0]["value"],
                 "vistas": int(float(_fila_valor(row, 0)))}
                for row in reps[2].get("rows", [])
            ],
            "dispositivos": _dim_dict(reps[3]),
            "paises": _dim_dict(reps[4]),
            "serie": [
                {"fecha": row["dimensionValues"][0]["value"],
                 "sesiones": int(float(row["metricValues"][0]["value"])),
                 "usuarios": int(float(row["metricValues"][1]["value"]))}
                for row in reps[5].get("rows", [])
            ],
        }
        return data, None
    except Exception as ex:  # noqa: BLE001
        return None, f"Error de red con GA4 Data API: {ex}"
