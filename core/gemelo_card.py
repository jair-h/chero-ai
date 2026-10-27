"""Tarjeta compartible del Gemelo Digital (imagen PNG con PIL).

Genera una imagen cuadrada lista para compartir (WhatsApp/Instagram) con el
resultado de la predicción. Self-contained: solo usa PIL. Devuelve los bytes
PNG; si PIL fallara, devuelve (None, error).

Diseño honesto: la insignia y el titular se ADAPTAN al veredicto real —
celebra cuando conviene, y cuando no, muestra que el Gemelo avisó a tiempo.
Nunca falsea el número.
"""
from __future__ import annotations

import io

MORADO = (124, 58, 237)        # #7C3AED
MORADO_OSC = (59, 18, 110)     # morado profundo (fondo)
BLANCO = (255, 255, 255)
LILA = (205, 196, 248)
# Colores de veredicto (coinciden con la UI)
_VERDICTO_COLOR = {
    "hazlo":   (22, 163, 74),    # verde
    "cuidado": (217, 119, 6),    # ámbar
    "no":      (220, 38, 38),    # rojo
}
_VERDICTO_LABEL = {
    "hazlo":   ("CONVIENE INVERTIR", "WORTH IT"),
    "cuidado": ("INVERTIR CON CUIDADO", "BE CAREFUL"),
    "no":      ("EL GEMELO ME AVISÓ", "THE TWIN WARNED ME"),
}
_VERDICTO_TITULAR = {
    "hazlo":   ("Mi predicción de ventas", "My sales forecast"),
    "cuidado": ("Mi Gemelo me avisó a tiempo", "My Twin warned me in time"),
    "no":      ("Mi Gemelo me salvó de una pérdida", "My Twin saved me from a loss"),
}


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


def _ancho(draw, texto, fuente):
    try:
        _bb = draw.textbbox((0, 0), texto, font=fuente)
        return _bb[2] - _bb[0]
    except Exception:
        return len(texto) * (getattr(fuente, "size", 16) // 2)


def _centrar(draw, texto, y, fuente, color, ancho):
    """Dibuja `texto` centrado horizontalmente."""
    _w = _ancho(draw, texto, fuente)
    draw.text(((ancho - _w) / 2, y), texto, font=fuente, fill=color)


def _fuente_que_cabe(draw, texto, tam_max, ancho_max, bold=False):
    """Baja el tamaño de fuente hasta que `texto` quepa en `ancho_max`."""
    tam = tam_max
    while tam > 40:
        f = _fuente(tam, bold=bold)
        if _ancho(draw, texto, f) <= ancho_max:
            return f
        tam -= 6
    return _fuente(tam, bold=bold)


def _pill(draw, texto, y, fuente, color_fondo, color_texto, ancho_img, pad_x=46, pad_y=22):
    """Dibuja una insignia redondeada centrada. Devuelve el alto usado."""
    tw = _ancho(draw, texto, fuente)
    th = getattr(fuente, "size", 36)
    w = tw + pad_x * 2
    h = th + pad_y * 2
    x0 = (ancho_img - w) / 2
    try:
        draw.rounded_rectangle([x0, y, x0 + w, y + h], radius=h / 2, fill=color_fondo)
    except Exception:
        draw.rectangle([x0, y, x0 + w, y + h], fill=color_fondo)
    draw.text((x0 + pad_x, y + pad_y - 2), texto, font=fuente, fill=color_texto)
    return h


def generar_tarjeta(marca, ventas_p10, ventas_p90, semana, moneda="S/",
                    ingresos_p50=None, veredicto=None, periodo="semana", en=False):
    """Crea la tarjeta PNG. Devuelve (bytes, None) o (None, error).

    veredicto: dict del motor {nivel, icono, titulo, razon, roas} (opcional).
    periodo: "mes" o "semana" — ajusta el texto del rango.
    """
    try:
        from PIL import Image, ImageDraw

        _nivel = (veredicto or {}).get("nivel", "hazlo")
        _col_ver = _VERDICTO_COLOR.get(_nivel, MORADO)
        _lbl = _VERDICTO_LABEL.get(_nivel, ("MI PREDICCIÓN", "MY FORECAST"))[1 if en else 0]
        _titular = _VERDICTO_TITULAR.get(_nivel, ("Mi predicción de ventas", "My sales forecast"))[1 if en else 0]

        W = H = 1080
        img = Image.new("RGB", (W, H), MORADO_OSC)
        d = ImageDraw.Draw(img)

        # Degradado vertical (morado profundo -> morado de marca)
        for y in range(H):
            t = y / H
            r = int(MORADO_OSC[0] + (MORADO[0] - MORADO_OSC[0]) * t)
            g = int(MORADO_OSC[1] + (MORADO[1] - MORADO_OSC[1]) * t)
            b = int(MORADO_OSC[2] + (MORADO[2] - MORADO_OSC[2]) * t)
            d.line([(0, y), (W, y)], fill=(r, g, b))

        # Marca
        _centrar(d, "TENTAKL", 86, _fuente(76, bold=True), BLANCO, W)
        _centrar(d, "Gemelo Digital", 184, _fuente(36), LILA, W)

        # Insignia de veredicto (color honesto según el resultado)
        _pill(d, _lbl, 290, _fuente(40, bold=True), _col_ver, BLANCO, W)

        # Titular (se adapta al veredicto)
        _centrar(d, _titular, 408, _fuente(42), BLANCO, W)

        # Rango grande (se encoge si el número es muy ancho)
        _p10 = f"{int(round(ventas_p10)):,}".replace(",", " ")
        _p90 = f"{int(round(ventas_p90)):,}".replace(",", " ")
        _rango = f"{_p10} – {_p90}"
        _f_rango = _fuente_que_cabe(d, _rango, 132, W - 120, bold=True)
        _centrar(d, _rango, 486, _f_rango, BLANCO, W)

        _periodo_txt = (("en ventas este mes" if not en else "in sales this month") if periodo == "mes"
                        else ("en ventas" if not en else "in sales"))
        _centrar(d, _periodo_txt, 648, _fuente(44), LILA, W)

        if ingresos_p50 is not None:
            _ing = f"{moneda}{int(round(ingresos_p50)):,}".replace(",", " ")
            _centrar(d, (f"≈ {_ing} en ingresos" if not en else f"≈ {_ing} revenue"),
                     726, _fuente(40), BLANCO, W)

        # Pie: marca del negocio + branding
        _centrar(d, (marca or ("Mi negocio" if not en else "My business")),
                 884, _fuente(46, bold=True), BLANCO, W)
        _centrar(d, (f"calculado con mi Gemelo · {semana}" if not en else f"made with my Twin · {semana}"),
                 956, _fuente(30), LILA, W)
        _centrar(d, "tentakl.ai", 1012, _fuente(32, bold=True), LILA, W)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)
