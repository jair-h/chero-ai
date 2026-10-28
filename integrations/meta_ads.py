"""Conexión con Meta (Facebook/Instagram) Ads — Marketing API.

Trae el GASTO y el ROAS reales de las campañas para autollenar el Gemelo y
mostrar métricas de publicidad. Mismo patrón que integrations/analytics.py:
OAuth (el usuario autoriza con 1 clic) + lectura por la Graph API.

Self-contained: solo usa `requests`. Nunca inventa datos: si falla, error claro.

Secrets necesarios (una sola vez, los pone el dueño de Tentakl):
    META_APP_ID, META_APP_SECRET, META_OAUTH_REDIRECT_URI
La app de Meta necesita el permiso `ads_read` (y revisión para uso público).
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

API_VERSION = "v20.0"
GRAPH = f"https://graph.facebook.com/{API_VERSION}"
DIALOG = f"https://www.facebook.com/{API_VERSION}/dialog/oauth"
SCOPE = "ads_read"
_TIMEOUT = 20

_MES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
           "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def oauth_configurado(secrets) -> bool:
    """True si están los 3 secrets de Meta."""
    try:
        return bool(secrets.get("META_APP_ID") and secrets.get("META_APP_SECRET")
                    and secrets.get("META_OAUTH_REDIRECT_URI"))
    except Exception:
        return False


def build_auth_url(secrets, state: str = "tentakl") -> str:
    """URL para que el usuario autorice la lectura de sus ads (1 clic)."""
    from urllib.parse import urlencode
    params = {
        "client_id": secrets.get("META_APP_ID", ""),
        "redirect_uri": secrets.get("META_OAUTH_REDIRECT_URI", ""),
        "scope": SCOPE,
        "state": state,
        "response_type": "code",
    }
    return f"{DIALOG}?{urlencode(params)}"


def exchange_code(secrets, code: str):
    """Canjea el code por un token. Devuelve (token_largo, error).

    Primero obtiene un token corto y luego lo cambia por uno de larga duración
    (~60 días), que es el que se guarda.
    """
    try:
        r = requests.get(f"{GRAPH}/oauth/access_token", params={
            "client_id": secrets.get("META_APP_ID", ""),
            "client_secret": secrets.get("META_APP_SECRET", ""),
            "redirect_uri": secrets.get("META_OAUTH_REDIRECT_URI", ""),
            "code": code,
        }, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None, f"Meta respondió {r.status_code}: {str(r.text)[:200]}"
        corto = (r.json() or {}).get("access_token", "")
        if not corto:
            return None, "Meta no devolvió access_token."
        # Cambia a token de larga duración
        r2 = requests.get(f"{GRAPH}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": secrets.get("META_APP_ID", ""),
            "client_secret": secrets.get("META_APP_SECRET", ""),
            "fb_exchange_token": corto,
        }, timeout=_TIMEOUT)
        if r2.status_code == 200 and (r2.json() or {}).get("access_token"):
            return r2.json()["access_token"], None
        return corto, None  # al menos el corto sirve de inmediato
    except Exception as ex:  # noqa: BLE001
        return None, f"Error: {ex}"


def listar_cuentas_ads(access_token: str):
    """Lista las cuentas publicitarias del usuario. Devuelve (cuentas, error).
    cuentas: [{"id": "123", "nombre": "...", "moneda": "PEN"}]."""
    try:
        r = requests.get(f"{GRAPH}/me/adaccounts", params={
            "fields": "name,account_id,currency",
            "access_token": access_token,
        }, timeout=_TIMEOUT)
        if r.status_code != 200:
            return [], f"Meta respondió {r.status_code}: {str(r.text)[:200]}"
        cuentas = []
        for c in (r.json() or {}).get("data", []):
            cuentas.append({"id": str(c.get("account_id", "")),
                            "nombre": c.get("name", ""),
                            "moneda": c.get("currency", "")})
        return cuentas, None
    except Exception as ex:  # noqa: BLE001
        return [], f"Error: {ex}"


def _roas_de_fila(fila):
    """Extrae el ROAS de compra de una fila de insights (puede faltar)."""
    try:
        for p in (fila.get("purchase_roas") or []):
            return round(float(p.get("value", 0) or 0), 2)
    except (TypeError, ValueError):
        pass
    return 0.0


def fetch_ad_spend_by_month(account_id: str, access_token: str, meses: int = 6):
    """Trae gasto (y ROAS) por MES de una cuenta de ads. Devuelve (filas, error).

    filas: [{"mes": "Jul 2026", "ym": "2026-07", "gasto": <float>, "roas": <float>}]
    de más antiguo a más reciente. Sirve para autollenar la inversión del Gemelo.
    """
    acc = str(account_id or "").strip().replace("act_", "")
    if not acc or not (access_token or "").strip():
        return [], "Falta la cuenta de ads o el token de Meta."

    hoy = datetime.now(timezone.utc)
    _mm, _yy = hoy.month - (meses - 1), hoy.year
    while _mm <= 0:
        _mm += 12
        _yy -= 1
    desde = f"{_yy:04d}-{_mm:02d}-01"
    hasta = hoy.strftime("%Y-%m-%d")

    try:
        r = requests.get(f"{GRAPH}/act_{acc}/insights", params={
            "fields": "spend,purchase_roas",
            "level": "account",
            "time_increment": "monthly",
            "time_range": f'{{"since":"{desde}","until":"{hasta}"}}',
            "access_token": access_token,
        }, timeout=_TIMEOUT)
        if r.status_code != 200:
            return [], f"Meta respondió {r.status_code}: {str(r.text)[:200]}"
        acum = {}  # ym -> {"gasto", "roas"}
        for fila in (r.json() or {}).get("data", []):
            ym = str(fila.get("date_start", ""))[:7]
            if len(ym) != 7:
                continue
            try:
                gasto = float(fila.get("spend", 0) or 0)
            except (TypeError, ValueError):
                gasto = 0.0
            acum[ym] = {"gasto": round(gasto, 2), "roas": _roas_de_fila(fila)}
    except Exception as ex:  # noqa: BLE001
        return [], f"Error: {ex}"

    filas = []
    for k in range(int(meses)):
        cm, cy = hoy.month - (meses - 1) + k, hoy.year
        while cm <= 0:
            cm += 12
            cy -= 1
        while cm > 12:
            cm -= 12
            cy += 1
        ym = f"{cy:04d}-{cm:02d}"
        _d = acum.get(ym, {"gasto": 0.0, "roas": 0.0})
        filas.append({"mes": f"{_MES_ES[cm - 1]} {cy}", "ym": ym,
                      "gasto": _d["gasto"], "roas": _d["roas"]})
    return filas, None
