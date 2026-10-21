"""Tarjeta compartible del Gemelo Digital (imagen PNG con PIL).

Genera una imagen cuadrada lista para compartir con el resultado de la
predicción (rango de ventas, semana, marca). Self-contained: solo usa PIL.
Devuelve los bytes PNG; si PIL fallara, devuelve (None, error).
"""
from __future__ import annotations

import io

MORADO = (124, 58, 237)        # #7C3AED
MORADO_OSC = (76, 29, 149)     # #4C1D95
BLANCO = (255, 255, 255)
LILA = (221, 214, 254)         # #DDD6FE


def _fuente(tam, bold=False):
    """Carga una fuente TrueType si existe; si no, la default de PIL."""
    from PIL import ImageFont
    _cands = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for _c in _cands:
        try:
            return ImageFont.truetype(_c, tam)
        except Exception:
            continue
    return ImageFont.load_default()


def _centrar(draw, texto, y, fuente, color, ancho):
    """Dibuja `texto` centrado horizontalmente en una imagen de ancho `ancho`."""
    try:
        _bb = draw.textbbox((0, 0), texto, font=fuente)
        _w = _bb[2] - _bb[0]
    except Exception:
        _w = len(texto) * (fuente.size // 2 if hasattr(fuente, "size") else 8)
    draw.text(((ancho - _w) / 2, y), texto, font=fuente, fill=color)


def generar_tarjeta(marca, ventas_p10, ventas_p90, semana, moneda="S/",
                    ingresos_p50=None):
    """Crea la tarjeta PNG. Devuelve (bytes, None) o (None, error)."""
    try:
        from PIL import Image, ImageDraw

        W = H = 1080
        img = Image.new("RGB", (W, H), MORADO_OSC)
        d = ImageDraw.Draw(img)

        # Degradado vertical simple (morado oscuro -> morado)
        for y in range(H):
            t = y / H
            r = int(MORADO_OSC[0] + (MORADO[0] - MORADO_OSC[0]) * t)
            g = int(MORADO_OSC[1] + (MORADO[1] - MORADO_OSC[1]) * t)
            b = int(MORADO_OSC[2] + (MORADO[2] - MORADO_OSC[2]) * t)
            d.line([(0, y), (W, y)], fill=(r, g, b))

        _centrar(d, "TENTAKL.AI", 90, _fuente(68, bold=True), BLANCO, W)
        _centrar(d, "GEMELO DIGITAL", 180, _fuente(34, bold=True), LILA, W)

        _centrar(d, "Mi gemelo predijo esta semana", 330, _fuente(40), BLANCO, W)

        # Rango grande
        _p10 = f"{int(round(ventas_p10)):,}".replace(",", " ")
        _p90 = f"{int(round(ventas_p90)):,}".replace(",", " ")
        _centrar(d, f"{_p10} – {_p90}", 430, _fuente(130, bold=True), BLANCO, W)
        _centrar(d, "ventas", 600, _fuente(46), LILA, W)

        if ingresos_p50 is not None:
            _centrar(d, f"≈ {moneda}{int(round(ingresos_p50)):,}".replace(",", " ") + " en ingresos",
                     690, _fuente(40), BLANCO, W)

        # Pie: marca + semana
        _centrar(d, f"{marca}" if marca else "Mi negocio", 880, _fuente(44, bold=True), BLANCO, W)
        _centrar(d, f"Semana {semana}", 950, _fuente(34), LILA, W)
        _centrar(d, "hecho con tentakl.ai", 1010, _fuente(28), LILA, W)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)
