"""Mercado Pago — Checkout Pro (cobro de planes). Esqueleto listo para enchufar
el Access Token del dueño. El dinero/HTTP vive aquí; la UI va en app.py.

Flujo SIN servidor de webhooks (apto para Streamlit):
  1. crear_preferencia(...) -> init_point (URL de pago). Rediriges al cliente.
  2. El cliente paga en Mercado Pago.
  3. MP lo devuelve a tu back_url con
     ?payment_id=...&status=approved&external_reference=email|plan
  4. La app lee esos parámetros y llama verificar_pago(...) para CONFIRMAR con la
     API de MP (nunca confíes solo en la URL) y recién ahí activa el plan.

El Access Token del vendedor se guarda en st.secrets["MERCADOPAGO_ACCESS_TOKEN"].
"""
from __future__ import annotations

import requests

_API = "https://api.mercadopago.com"
_TIMEOUT = 15


def construir_preferencia(titulo, precio, moneda_id, external_reference,
                          back_url, notification_url=None):
    """Arma el payload de la preferencia (función pura, testeable)."""
    pref = {
        "items": [{
            "title": str(titulo)[:250],
            "quantity": 1,
            "unit_price": round(float(precio), 2),
            "currency_id": moneda_id,            # "PEN" para Perú, "USD", etc.
        }],
        "external_reference": str(external_reference),
        "back_urls": {"success": back_url, "failure": back_url, "pending": back_url},
        "auto_return": "approved",
    }
    if notification_url:
        pref["notification_url"] = notification_url
    return pref


def crear_preferencia(access_token, titulo, precio, moneda_id, external_reference,
                      back_url, notification_url=None):
    """Crea la preferencia en Mercado Pago. Devuelve (init_point, pref_id, error)."""
    tok = (access_token or "").strip()
    if not tok:
        return None, None, "Falta el Access Token de Mercado Pago."
    try:
        r = requests.post(
            f"{_API}/checkout/preferences",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json=construir_preferencia(titulo, precio, moneda_id, external_reference,
                                       back_url, notification_url),
            timeout=_TIMEOUT,
        )
        if r.status_code not in (200, 201):
            return None, None, f"Error {r.status_code}: {str(r.text)[:200]}"
        d = r.json() or {}
        return (d.get("init_point") or d.get("sandbox_init_point")), d.get("id"), None
    except Exception as ex:  # noqa: BLE001
        return None, None, f"Error: {ex}"


def verificar_pago(access_token, payment_id):
    """Confirma un pago con la API de MP. Devuelve (datos, error) donde datos =
    {status, external_reference, monto, moneda}. status 'approved' = pagado.
    NUNCA actives un plan solo por el parámetro de la URL: confirma aquí."""
    tok = (access_token or "").strip()
    if not tok or not payment_id:
        return None, "Falta el Access Token o el payment_id."
    try:
        r = requests.get(f"{_API}/v1/payments/{payment_id}",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None, f"Error {r.status_code}: {str(r.text)[:200]}"
        d = r.json() or {}
        return {"status": d.get("status"),
                "external_reference": d.get("external_reference"),
                "monto": d.get("transaction_amount"),
                "moneda": d.get("currency_id")}, None
    except Exception as ex:  # noqa: BLE001
        return None, f"Error: {ex}"


def plan_desde_referencia(external_reference):
    """external_reference = 'email|plan'. Devuelve (email, plan) en minúsculas."""
    s = str(external_reference or "")
    if "|" in s:
        _email, _plan = s.split("|", 1)
        return _email.strip().lower(), _plan.strip()
    return s.strip().lower(), ""
