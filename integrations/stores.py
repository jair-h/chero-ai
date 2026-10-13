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

import requests

SHOPIFY_API_VERSION = "2024-01"
_TIMEOUT = 15


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
