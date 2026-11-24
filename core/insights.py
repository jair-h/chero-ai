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

import datetime


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


def zonas_desde_clientes(clientes, top_n: int = 5) -> dict:
    """Agrega los clientes por zona (ciudad/distrito) para ver de dónde viene la
    plata y el ticket promedio por pedido. Todo real; '' si no hay clientes."""
    zonas: dict[str, dict] = {}
    total_gasto = 0.0
    total_pedidos = 0
    for c in (clientes or []):
        z = (c.get("ciudad") or c.get("provincia") or "").strip()
        g = _f(c.get("total_gastado"))
        ped = int(_f(c.get("pedidos")))
        total_gasto += g
        total_pedidos += ped
        if z:
            zz = zonas.setdefault(z, {"zona": z, "clientes": 0, "gasto": 0.0})
            zz["clientes"] += 1
            zz["gasto"] += g
    top = sorted(zonas.values(), key=lambda x: x["gasto"], reverse=True)[:max(int(top_n), 1)]
    for z in top:
        z["gasto"] = round(z["gasto"], 2)
        z["share"] = round(z["gasto"] / total_gasto * 100.0, 1) if total_gasto > 0 else 0.0
    ticket = round(total_gasto / total_pedidos, 2) if total_pedidos > 0 else 0.0
    return {"zonas_top": top, "zona_top": (top[0] if top else None),
            "ticket_promedio": ticket, "total_gasto": round(total_gasto, 2),
            "pedidos": total_pedidos, "n_clientes": len(clientes or [])}


def recomendar_acciones(rad_prod: dict, zonas: dict, hoy=None) -> list:
    """Recomendaciones CONCRETAS por reglas sobre datos reales (sin IA).
    Cada acción se dispara por un número real del negocio; si no hay señal,
    no inventa recomendaciones."""
    hoy = hoy or datetime.date.today()
    recs: list[str] = []
    top = (rad_prod or {}).get("top") or []
    if top:
        if (rad_prod.get("concentracion_top1") or 0) >= 40:
            recs.append(f"🧩 Diversifica: **{top[0]['nombre']}** es el {rad_prod['concentracion_top1']:.0f}% "
                        f"de tus ingresos. Si se cae, te golpea fuerte — empuja 2 o 3 productos más.")
        else:
            recs.append(f"⭐ Tu estrella es **{top[0]['nombre']}**. Asegura stock y dale prioridad en tus anuncios.")
    for e in ((rad_prod or {}).get("estancados") or [])[:1]:
        recs.append(f"🔻 Reactiva **{e['nombre']}**: cayó {abs(e['tendencia']):.0f}%. "
                    f"Prueba una promo o bájalo de precio antes de que se quede en stock.")
    for a in ((rad_prod or {}).get("en_alza") or [])[:1]:
        recs.append(f"🚀 Métele más a **{a['nombre']}**: viene subiendo (+{a['tendencia']:.0f}%). "
                    f"Súbele presupuesto de ads mientras tiene impulso.")
    zt = (zonas or {}).get("zona_top")
    if zt and zt.get("share", 0) >= 15:
        recs.append(f"📍 Concentra publicidad en **{zt['zona']}**: es tu zona que más compra "
                    f"({zt['share']:.0f}% de la plata). Segmenta tus ads por ahí.")
    m = hoy.month
    if m in (10, 11):
        recs.append("🎄 Se vienen Cyber/Black y Navidad: prepara stock de tu estrella y sube el "
                    "presupuesto de campaña — la gente ya está comprando.")
    elif m == 12:
        recs.append("🎁 Es Navidad, tu mejor momento: prioriza tu estrella y tus productos en alza.")
    return recs[:5]


def radiografia_negocio(productos, clientes, moneda: str = "S/", hoy=None) -> dict:
    """Radiografía COMPLETA del negocio con datos reales: productos, zona que más
    compra, ticket promedio, de dónde viene la plata y recomendaciones concretas.
    Nada se inventa: cada parte sale de la tienda/CRM; lo que falte, queda vacío."""
    rad_prod = analizar_productos(productos, top_n=5)
    zonas = zonas_desde_clientes(clientes, top_n=5)
    ticket = zonas["ticket_promedio"]
    if ticket <= 0 and rad_prod["total_unidades"] > 0:
        # Sin clientes con pedidos: ticket aproximado = ingreso medio por unidad
        ticket = round(rad_prod["total_ingresos"] / rad_prod["total_unidades"], 2)
    recs = recomendar_acciones(rad_prod, zonas, hoy=hoy)
    return {
        "productos": rad_prod,
        "zonas_top": zonas["zonas_top"],
        "zona_top": zonas["zona_top"],
        "ticket_promedio": ticket,
        "n_clientes": zonas["n_clientes"],
        "pedidos": zonas["pedidos"],
        "recomendaciones": recs,
        "moneda": moneda,
    }
