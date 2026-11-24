"""Tarjeta compartible del Gemelo Digital (imagen PNG con PIL).

Genera una imagen cuadrada lista para compartir (WhatsApp/Instagram) con el
resultado de la predicción. Self-contained: solo usa PIL. Devuelve los bytes
PNG; si PIL fallara, devuelve (None, error).

La fuente se incluye en el repo (core/assets/fonts) para que la tarjeta se vea
IGUAL en cualquier servidor (Streamlit Cloud, Render, etc.) y no dependa de las
fuentes del sistema.

Diseño honesto: la insignia y el titular se ADAPTAN al veredicto real —
celebra cuando conviene, y cuando no, muestra que el Gemelo avisó a tiempo.
Nunca falsea el número.
"""
from __future__ import annotations

import io
import os

# ── Paleta de marca (coincide con el landing) ───────────────────────────────
BG_TOP = (18, 10, 40)          # navy profundo
BG_BOT = (58, 26, 110)         # morado de marca (abajo)
MORADO = (124, 58, 237)
LILA = (199, 186, 250)
CYAN = (45, 212, 191)
BLANCO = (255, 255, 255)
PANEL = (47, 28, 96)           # panel del número (un poco más claro que el fondo)
PANEL_BORDE = (120, 94, 210)

_VERDICTO_COLOR = {
    "hazlo":   (22, 163, 74),
    "cuidado": (217, 119, 6),
    "no":      (220, 38, 38),
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

_DIR_FUENTES = os.path.join(os.path.dirname(__file__), "assets", "fonts")


def _fuente(tam, bold=False):
    """Carga la fuente incluida en el repo; si no, una del sistema; si no, default."""
    from PIL import ImageFont
    _cands = [
        os.path.join(_DIR_FUENTES, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for _c in _cands:
        try:
            return ImageFont.truetype(_c, tam)
        except Exception:
            continue
    try:
        return ImageFont.load_default(tam)
    except Exception:
        return ImageFont.load_default()


def _ancho(draw, texto, fuente):
    try:
        _bb = draw.textbbox((0, 0), texto, font=fuente)
        return _bb[2] - _bb[0]
    except Exception:
        return len(texto) * (getattr(fuente, "size", 16) // 2)


def _centrar(draw, texto, y, fuente, color, ancho):
    _w = _ancho(draw, texto, fuente)
    draw.text(((ancho - _w) / 2, y), texto, font=fuente, fill=color)


def _fuente_que_cabe(draw, texto, tam_max, ancho_max, bold=False):
    tam = tam_max
    while tam > 44:
        f = _fuente(tam, bold=bold)
        if _ancho(draw, texto, f) <= ancho_max:
            return f
        tam -= 6
    return _fuente(tam, bold=bold)


def _pill(draw, texto, y, fuente, color_fondo, color_texto, ancho_img, pad_x=50, pad_y=24):
    """Insignia redondeada centrada. Devuelve (alto, y_centro_del_texto)."""
    tw = _ancho(draw, texto, fuente)
    th = getattr(fuente, "size", 36)
    w = tw + pad_x * 2
    h = th + pad_y * 2
    x0 = (ancho_img - w) / 2
    try:
        draw.rounded_rectangle([x0, y, x0 + w, y + h], radius=h / 2, fill=color_fondo)
    except Exception:
        draw.rectangle([x0, y, x0 + w, y + h], fill=color_fondo)
    # centra el texto dentro de la pastilla
    draw.text((x0 + (w - tw) / 2, y + (h - th) / 2 - 4), texto, font=fuente, fill=color_texto)
    return h


def _pulpo(draw, cx, cy, s, color):
    """Dibuja un pulpo minimalista (cabeza + ojos + tentáculos)."""
    # cabeza (domo)
    draw.ellipse([cx - s, cy - s, cx + s, cy + s * 0.75], fill=color)
    draw.rectangle([cx - s, cy - s * 0.1, cx + s, cy + s * 0.45], fill=color)
    # ojos
    r = s * 0.17
    for dx in (-0.42, 0.42):
        ex = cx + dx * s
        draw.ellipse([ex - r, cy - r * 0.6, ex + r, cy + r * 1.4], fill=BG_TOP)
    # tentáculos
    ty = cy + s * 0.45
    wline = max(int(s * 0.16), 3)
    for dx in (-0.72, -0.36, 0.0, 0.36, 0.72):
        x = cx + dx * s
        try:
            draw.line([(x, ty), (x, ty + s * 0.75)], fill=color, width=wline)
            draw.ellipse([x - wline / 2, ty + s * 0.75 - wline / 2,
                          x + wline / 2, ty + s * 0.75 + wline / 2], fill=color)
        except Exception:
            pass


def generar_tarjeta(marca, ventas_p10, ventas_p90, semana, moneda="S/",
                    ingresos_p50=None, veredicto=None, periodo="semana", en=False):
    """Crea la tarjeta PNG. Devuelve (bytes, None) o (None, error)."""
    try:
        from PIL import Image, ImageDraw

        _nivel = (veredicto or {}).get("nivel", "hazlo")
        _col_ver = _VERDICTO_COLOR.get(_nivel, MORADO)
        _lbl = _VERDICTO_LABEL.get(_nivel, ("MI PREDICCIÓN", "MY FORECAST"))[1 if en else 0]
        _titular = _VERDICTO_TITULAR.get(_nivel, ("Mi predicción de ventas", "My sales forecast"))[1 if en else 0]

        W = H = 1080
        img = Image.new("RGB", (W, H), BG_TOP)
        d = ImageDraw.Draw(img)

        # Fondo: degradado diagonal navy -> morado + glow suave arriba
        for y in range(H):
            t = y / H
            r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
            g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
            b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
            d.line([(0, y), (W, y)], fill=(r, g, b))

        # Marca: pulpo + wordmark
        _pulpo(d, W / 2, 118, 54, LILA)
        _centrar(d, "Tentakul", 198, _fuente(70, bold=True), BLANCO, W)
        _centrar(d, "Gemelo Digital", 286, _fuente(34), LILA, W)

        # Insignia de veredicto (color honesto)
        _pill(d, _lbl, 356, _fuente(40, bold=True), _col_ver, BLANCO, W)

        # Titular
        _centrar(d, _titular, 470, _fuente(42), BLANCO, W)

        # Panel del número grande
        _px0, _py0, _px1, _py1 = 90, 548, W - 90, 772
        try:
            d.rounded_rectangle([_px0, _py0, _px1, _py1], radius=36, fill=PANEL, outline=PANEL_BORDE, width=2)
        except Exception:
            d.rectangle([_px0, _py0, _px1, _py1], fill=PANEL)

        _p10 = f"{int(round(ventas_p10)):,}".replace(",", " ")
        _p90 = f"{int(round(ventas_p90)):,}".replace(",", " ")
        _rango = f"{_p10} – {_p90}"
        _f_rango = _fuente_que_cabe(d, _rango, 130, (_px1 - _px0) - 80, bold=True)
        _centrar(d, _rango, 584, _f_rango, BLANCO, W)
        _periodo_txt = (("ventas este mes" if not en else "sales this month") if periodo == "mes"
                        else ("ventas" if not en else "sales"))
        _centrar(d, _periodo_txt, 716, _fuente(38), LILA, W)

        # Ingresos probables
        if ingresos_p50 is not None:
            _ing = f"{moneda}{int(round(ingresos_p50)):,}".replace(",", " ")
            _centrar(d, (f"≈ {_ing} en ingresos" if not en else f"≈ {_ing} in revenue"),
                     812, _fuente(40, bold=True), CYAN, W)

        # Línea divisoria
        d.line([(160, 902), (W - 160, 902)], fill=PANEL_BORDE, width=2)

        # Pie: negocio + branding
        _centrar(d, (marca or ("Mi negocio" if not en else "My business")),
                 928, _fuente(44, bold=True), BLANCO, W)
        _suf = f" · {semana}" if str(semana or "").strip() else ""
        _centrar(d, (f"calculado con mi Gemelo Digital{_suf}" if not en
                     else f"made with my Digital Twin{_suf}"),
                 992, _fuente(27), LILA, W)
        _centrar(d, "tentakul.com", 1034, _fuente(30, bold=True), CYAN, W)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)
