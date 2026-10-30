"""Conectores de tiendas (Shopify / WooCommerce / TiendaNube).

Centraliza la lógica HTTP que antes estaba duplicada en varios puntos de
`app.py` (importar catálogo "primera vez" vs "agregar"). La UI sigue en
app.py; aquí solo vive el fetch, que devuelve (lineas, error).

Cada función devuelve:
    (lineas, error)
        lineas : list[str]  -> ["Producto - $precio", ...] listas para mostrar/guardar
        error  : str | None -> mensaje de error legible, o None si todo bien
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

SHOPIFY_API_VERSION = "2024-01"
_TIMEOUT = 15

_MES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
           "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
# Estados de pedido que cuentan como venta real (no cancelados/fallidos/pendientes).
_WOO_ESTADOS_VENTA = ("completed", "processing")


def _normalizar_base(url: str) -> str:
    """Asegura que la URL tenga esquema y sin barra final."""
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


def fetch_shopify_products(url: str, access_token: str, moneda: str = "$",
                           limite: int = 100):
    """Trae productos de Shopify Admin API. Devuelve (lineas, error)."""
    base = _normalizar_base(url)
    if not base or not (access_token or "").strip():
        return [], "Faltan la URL o el Access Token de Shopify."
    try:
        r = requests.get(
            f"{base}/admin/api/{SHOPIFY_API_VERSION}/products.json?limit={int(limite)}",
            headers={"X-Shopify-Access-Token": access_token.strip()},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return [], f"Error {r.status_code}: {r.text[:200]}"
        prods = r.json().get("products", [])
        lineas = [
            f"{p.get('title', '')} - {moneda}{(p.get('variants', [{}]) or [{}])[0].get('price', '')}"
            for p in prods
        ]
        return lineas, None
    except Exception as ex:  # noqa: BLE001 - se reporta al usuario
        return [], f"Error: {ex}"


def fetch_woocommerce_products(url: str, consumer_key: str, consumer_secret: str,
                               moneda: str = "$", per_page: int = 100):
    """Trae productos de WooCommerce REST API. Devuelve (lineas, error)."""
    base = _normalizar_base(url)
    if not base or not (consumer_key or "").strip() or not (consumer_secret or "").strip():
        return [], "Faltan la URL, Consumer Key o Consumer Secret de WooCommerce."
    try:
        r = requests.get(
            f"{base}/wp-json/wc/v3/products",
            params={"per_page": int(per_page)},
            auth=(consumer_key.strip(), consumer_secret.strip()),
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return [], f"Error {r.status_code}: {r.text[:200]}"
        lineas = [f"{p.get('name', '')} - {moneda}{p.get('price', '')}" for p in r.json()]
        return lineas, None
    except Exception as ex:  # noqa: BLE001 - se reporta al usuario
        return [], f"Error: {ex}"


def fetch_woocommerce_sales_by_month(url: str, consumer_key: str, consumer_secret: str,
                                     meses: int = 6, max_paginas: int = 15):
    """Lee los pedidos de WooCommerce y suma las VENTAS por mes (últimos `meses`).

    Sirve para autollenar el Gemelo con ventas reales. Solo cuenta pedidos en
    estado de venta real (completado / en proceso), ignorando cancelados,
    reembolsados, fallidos y pendientes. Devuelve (filas, error):
        filas: [{"mes": "Jul 2026", "ventas": <float>, "ym": "2026-07"}, ...]
               de más antiguo a más reciente, un item por cada uno de los
               últimos `meses` (relleno con 0 si ese mes no tuvo ventas).
    """
    base = _normalizar_base(url)
    ck, cs = (consumer_key or "").strip(), (consumer_secret or "").strip()
    if not base or not ck or not cs:
        return [], "Faltan la URL, Consumer Key o Consumer Secret de WooCommerce."

    hoy = datetime.now(timezone.utc)
    # Mes inicial de la ventana (meses-1 atrás del actual).
    _mm, _yy = hoy.month - (meses - 1), hoy.year
    while _mm <= 0:
        _mm += 12
        _yy -= 1
    desde = f"{_yy:04d}-{_mm:02d}-01T00:00:00"

    acum: dict[str, float] = {}
    try:
        for page in range(1, int(max_paginas) + 1):
            r = requests.get(
                f"{base}/wp-json/wc/v3/orders",
                params={"per_page": 100, "page": page, "after": desde,
                        "status": "any", "orderby": "date", "order": "asc"},
                auth=(ck, cs), timeout=_TIMEOUT,
            )
            if r.status_code != 200:
                return [], f"Error {r.status_code}: {str(r.text)[:200]}"
            pedidos = r.json() or []
            if not pedidos:
                break
            for o in pedidos:
                if o.get("status") not in _WOO_ESTADOS_VENTA:
                    continue
                ym = str(o.get("date_paid") or o.get("date_created") or "")[:7]
                if len(ym) != 7:
                    continue
                try:
                    total = float(o.get("total", 0) or 0)
                except (TypeError, ValueError):
                    total = 0.0
                acum[ym] = acum.get(ym, 0.0) + total
            if len(pedidos) < 100:
                break
    except Exception as ex:  # noqa: BLE001 - se reporta al usuario
        return [], f"Error: {ex}"

    return _rellenar_meses(acum, meses, hoy), None


def _rellenar_meses(acum: dict, meses: int, hoy) -> list:
    """Arma la lista de los últimos `meses` (de más antiguo a más reciente),
    rellenando con 0 los meses sin ventas. Reutilizado por Woo y Shopify."""
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
        filas.append({"mes": f"{_MES_ES[cm - 1]} {cy}", "ventas": round(acum.get(ym, 0.0), 2), "ym": ym})
    return filas


def _shopify_next_page_info(headers) -> str:
    """Extrae el page_info del header Link rel="next" de Shopify (o '' si no hay).
    Shopify pagina por cursor: el 'siguiente' viene en el header Link."""
    import re
    link = ""
    try:
        link = headers.get("Link") or headers.get("link") or ""
    except Exception:
        link = ""
    for parte in str(link).split(","):
        if 'rel="next"' in parte:
            m = re.search(r"[?&]page_info=([^>&]+)", parte)
            if m:
                return m.group(1)
    return ""


def fetch_shopify_sales_by_month(url: str, access_token: str,
                                 meses: int = 6, max_paginas: int = 20):
    """Lee los pedidos PAGADOS de Shopify y suma las VENTAS por mes.

    Mismo formato que WooCommerce para autollenar el Gemelo:
        filas: [{"mes": "Jul 2026", "ventas": <float>, "ym": "2026-07"}, ...]
    Solo cuenta pedidos pagados (financial_status=paid) e ignora cancelados.
    Devuelve (filas, error).
    """
    base = _normalizar_base(url)
    tok = (access_token or "").strip()
    if not base or not tok:
        return [], "Faltan la URL o el Access Token de Shopify."

    hoy = datetime.now(timezone.utc)
    _mm, _yy = hoy.month - (meses - 1), hoy.year
    while _mm <= 0:
        _mm += 12
        _yy -= 1
    desde = f"{_yy:04d}-{_mm:02d}-01T00:00:00Z"

    acum: dict[str, float] = {}
    headers = {"X-Shopify-Access-Token": tok}
    params = {"status": "any", "financial_status": "paid",
              "created_at_min": desde, "limit": 250}
    try:
        for _pg in range(int(max_paginas)):
            r = requests.get(
                f"{base}/admin/api/{SHOPIFY_API_VERSION}/orders.json",
                params=params, headers=headers, timeout=_TIMEOUT,
            )
            if r.status_code != 200:
                return [], f"Error {r.status_code}: {str(r.text)[:200]}"
            pedidos = (r.json() or {}).get("orders", [])
            if not pedidos:
                break
            for o in pedidos:
                if o.get("cancelled_at"):
                    continue
                ym = str(o.get("created_at") or o.get("processed_at") or "")[:7]
                if len(ym) != 7:
                    continue
                try:
                    total = float(o.get("total_price", 0) or 0)
                except (TypeError, ValueError):
                    total = 0.0
                acum[ym] = acum.get(ym, 0.0) + total
            # Cursor de la siguiente página (sin header Link -> fin).
            _next = _shopify_next_page_info(getattr(r, "headers", {}) or {})
            if not _next:
                break
            params = {"limit": 250, "page_info": _next}  # con page_info solo va el limit
    except Exception as ex:  # noqa: BLE001 - se reporta al usuario
        return [], f"Error: {ex}"

    return _rellenar_meses(acum, meses, hoy), None
