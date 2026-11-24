"""Insights de productos (Python puro, SIN IA) — la 'radiografía' del negocio.

Toma la lista de productos vendidos (que arma integrations/stores.py desde la
tienda) y saca lo concreto que hace que el Gemelo se sienta un asesor, no una
calculadora: qué se vende más, qué está estancado y qué tan concentrado está
el negocio. Determinista y testeable; la UI (app.py) solo muestra.

Cada producto de entrada es un dict:
    {"nombre", "sku", "unidades", "ingresos",
     "unidades_rec", "unidades_prev", "ultima_venta"}
  unidades_rec  = unidades vendidas en los últimos ~30 días
  unidades_prev = unidades vendidas en los ~30 días anteriores a esos
"""
from __future__ import annotations


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def tendencia(prod) -> float | None:
    """% de cambio reciente vs previo. None si no hay base previa para comparar."""
    prev = _f(prod.get("unidades_prev"))
    if prev <= 0:
        return None
    rec = _f(prod.get("unidades_rec"))
    return (rec - prev) / prev


def analizar_productos(productos, top_n: int = 5, caida_min: float = 0.40,
                       prev_min: int = 2) -> dict:
    """Devuelve la radiografía: top, estancados, estrellas que suben, totales.

    - top: los `top_n` productos por ingresos (cada uno con su % del total).
    - estancados: productos cuyas ventas CAYERON >= `caida_min` (40%) vs el
      periodo anterior (y que tenían al menos `prev_min` unidades antes).
    - en_alza: productos que SUBIERON >= `caida_min`.
    - concentracion_top1: % de los ingresos que depende del producto #1.
    """
    prods = [p for p in (productos or [])
             if _f(p.get("ingresos")) > 0 or _f(p.get("unidades")) > 0]
    total_ing = sum(_f(p.get("ingresos")) for p in prods)
    total_unid = int(sum(_f(p.get("unidades")) for p in prods))

    ordenados = sorted(prods, key=lambda p: _f(p.get("ingresos")), reverse=True)
    top = []
    for p in ordenados[:max(int(top_n), 1)]:
        share = (_f(p.get("ingresos")) / total_ing * 100.0) if total_ing > 0 else 0.0
        top.append({**p, "ingresos": round(_f(p.get("ingresos")), 2),
                    "share": round(share, 1)})

    estancados, en_alza = [], []
    for p in prods:
        t = tendencia(p)
        if t is None:
            continue
        if t <= -abs(caida_min) and _f(p.get("unidades_prev")) >= prev_min:
            estancados.append({**p, "tendencia": round(t * 100.0, 0)})
        elif t >= abs(caida_min) and _f(p.get("unidades_rec")) >= prev_min:
            en_alza.append({**p, "tendencia": round(t * 100.0, 0)})
    estancados.sort(key=lambda p: p["tendencia"])            # más caída primero
    en_alza.sort(key=lambda p: p["tendencia"], reverse=True)  # más subida primero

    concentracion = (_f(top[0].get("ingresos")) / total_ing * 100.0) if (top and total_ing > 0) else 0.0

    return {
        "top": top,
        "estancados": estancados[:max(int(top_n), 1)],
        "en_alza": en_alza[:max(int(top_n), 1)],
        "total_ingresos": round(total_ing, 2),
        "total_unidades": total_unid,
        "n_productos": len(prods),
        "concentracion_top1": round(concentracion, 1),
    }


def resumen_texto(rad: dict, moneda: str = "S/") -> str:
    """Una línea honesta con lo más importante (sin IA). '' si no hay datos."""
    if not rad or not rad.get("top"):
        return ""
    t0 = rad["top"][0]
    partes = [f"Tu producto estrella es **{t0['nombre']}** "
              f"({t0['share']:.0f}% de tus ingresos)."]
    if rad["concentracion_top1"] >= 40:
        partes.append(f"⚠️ Dependes mucho de un solo producto ({rad['concentracion_top1']:.0f}%); "
                      f"conviene empujar otros.")
    if rad.get("estancados"):
        e = rad["estancados"][0]
        partes.append(f"**{e['nombre']}** cayó {abs(e['tendencia']):.0f}% — revísalo.")
    if rad.get("en_alza"):
        a = rad["en_alza"][0]
        partes.append(f"**{a['nombre']}** viene subiendo ({a['tendencia']:.0f}%) — métele más.")
    return " ".join(partes)
