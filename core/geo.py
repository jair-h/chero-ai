"""Coordenadas para el mapa del Gemelo (sin red, sin token).

Tabla práctica de distritos de Lima + principales ciudades del Perú y capitales
de LATAM/España, para ubicar las zonas del usuario en un mapa real. Si una zona
no está en la tabla, el usuario pone Lat/Lon a mano (así el mapa sirve en
cualquier ciudad o país). Todo es data pura + funciones testeables.
"""
from __future__ import annotations

import unicodedata


def _norm(s: str) -> str:
    """minúsculas, sin tildes y sin espacios extra, para hacer match flexible."""
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


# (lat, lon) aproximados a nivel de distrito/ciudad — suficiente para un mapa.
COORDS = {
    # ── Lima: distritos ──────────────────────────────────────────────
    "Miraflores": (-12.1211, -77.0297), "San Isidro": (-12.0977, -77.0365),
    "Santiago de Surco": (-12.1450, -76.9917), "Surco": (-12.1450, -76.9917),
    "Barranco": (-12.1489, -77.0206), "San Borja": (-12.1089, -76.9975),
    "La Molina": (-12.0792, -76.9447), "Jesus Maria": (-12.0747, -77.0497),
    "Lince": (-12.0860, -77.0360), "Magdalena del Mar": (-12.0969, -77.0719),
    "San Miguel": (-12.0776, -77.0922), "Pueblo Libre": (-12.0747, -77.0628),
    "Chorrillos": (-12.1760, -77.0197), "Surquillo": (-12.1120, -77.0170),
    "San Juan de Lurigancho": (-11.9939, -77.0064), "San Juan de Miraflores": (-12.1569, -76.9700),
    "Villa El Salvador": (-12.2136, -76.9389), "Villa Maria del Triunfo": (-12.1667, -76.9375),
    "Comas": (-11.9353, -77.0531), "Los Olivos": (-11.9714, -77.0700),
    "Independencia": (-11.9892, -77.0536), "Callao": (-12.0566, -77.1181),
    "Ate": (-12.0264, -76.9178), "Santa Anita": (-12.0433, -76.9719),
    "El Agustino": (-12.0411, -76.9939), "Rimac": (-12.0272, -77.0289),
    "Brena": (-12.0589, -77.0506), "La Victoria": (-12.0697, -77.0156),
    "Cercado de Lima": (-12.0464, -77.0428), "Lima": (-12.0464, -77.0428),
    "San Luis": (-12.0756, -76.9967), "Carabayllo": (-11.8978, -77.0381),
    "Puente Piedra": (-11.8622, -77.0747), "Lurin": (-12.2744, -76.8683),
    "Pachacamac": (-12.2297, -76.8686), "La Perla": (-12.0689, -77.1136),
    # ── Perú: principales ciudades ───────────────────────────────────
    "Arequipa": (-16.4090, -71.5375), "Trujillo": (-8.1159, -79.0300),
    "Chiclayo": (-6.7714, -79.8409), "Piura": (-5.1945, -80.6328),
    "Cusco": (-13.5319, -71.9675), "Huancayo": (-12.0686, -75.2103),
    "Iquitos": (-3.7491, -73.2538), "Tacna": (-18.0066, -70.2463),
    "Chimbote": (-9.0853, -78.5783), "Juliaca": (-15.4997, -70.1333),
    "Pucallpa": (-8.3791, -74.5539), "Cajamarca": (-7.1617, -78.5128),
    "Ica": (-14.0678, -75.7286), "Huanuco": (-9.9306, -76.2422),
    "Ayacucho": (-13.1588, -74.2239), "Tarapoto": (-6.4847, -76.3719),
    "Puno": (-15.8402, -70.0219), "Tumbes": (-3.5669, -80.4515),
    # ── LATAM / España: capitales (otras ciudades → Lat/Lon manual) ──
    "Bogota": (4.7110, -74.0721), "Ciudad de Mexico": (19.4326, -99.1332),
    "CDMX": (19.4326, -99.1332), "Santiago": (-33.4489, -70.6693),
    "Buenos Aires": (-34.6037, -58.3816), "Quito": (-0.1807, -78.4678),
    "La Paz": (-16.4897, -68.1193), "Montevideo": (-34.9011, -56.1645),
    "Asuncion": (-25.2637, -57.5759), "Caracas": (10.4806, -66.9036),
    "San Jose": (9.9281, -84.0907), "Guayaquil": (-2.1894, -79.8891),
    "Medellin": (6.2442, -75.5812), "Guadalajara": (20.6597, -103.3496),
    "Monterrey": (25.6866, -100.3161), "Madrid": (40.4168, -3.7038),
    "Barcelona": (41.3851, 2.1734),
}

_TABLA = {_norm(k): v for k, v in COORDS.items()}


def resolver(nombre):
    """Devuelve (lat, lon) de un distrito/ciudad conocido, o None si no está."""
    return _TABLA.get(_norm(nombre))


def centro_y_zoom(puntos):
    """Dado una lista de (lat, lon), devuelve (lat_centro, lon_centro, zoom) para
    encuadrar todos los puntos. Si no hay puntos, centra en Lima."""
    pts = []
    for p in (puntos or []):
        try:
            la, lo = float(p[0]), float(p[1])
            if la == la and lo == lo:   # descarta NaN
                pts.append((la, lo))
        except (TypeError, ValueError, IndexError):
            continue
    if not pts:
        return (-12.05, -77.04, 10.0)
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    clat = sum(lats) / len(lats)
    clon = sum(lons) / len(lons)
    span = max(max(lats) - min(lats), max(lons) - min(lons))
    for limite, z in ((0.03, 13), (0.08, 12), (0.2, 11), (0.5, 10),
                      (1.5, 8), (5.0, 6), (15.0, 4)):
        if span < limite:
            return (clat, clon, float(z))
    return (clat, clon, 3.0)
