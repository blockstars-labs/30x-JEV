"""Genera datos demográficos y de origen sintéticos para los perfiles de data/perfiles_sinteticos.json.

Por cada perfil: país y ciudad (con coordenadas para el globo), rango de edad, sector, tamaño de
empresa y de dónde llegó (Luma, campañas, newsletter, referidos...). Todo es inventado: no sale de
ninguna persona real. El origen es coherente con el canal del perfil (un formulario de Luma viene de
Luma; un correo, de newsletter o campaña; un mensaje, de redes o referidos).

La vista "Personas" de la página lee el resultado en web/demografia.json.

Uso:
    python scripts/generar_demografia.py [semilla]
"""

import json
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PERFILES = RAIZ / "data" / "perfiles_sinteticos.json"
SALIDA = RAIZ / "web" / "demografia.json"

# Ciudades donde 30X tiene comunidad o inmersiones, con un peso relativo.
CIUDADES = [
    ("Colombia", "Bogotá", 4.711, -74.072, 26),
    ("Colombia", "Medellín", 6.244, -75.581, 16),
    ("Colombia", "Cali", 3.452, -76.532, 5),
    ("Colombia", "Barranquilla", 10.964, -74.796, 4),
    ("México", "Ciudad de México", 19.433, -99.133, 14),
    ("México", "Monterrey", 25.686, -100.316, 6),
    ("México", "Guadalajara", 20.659, -103.349, 3),
    ("Perú", "Lima", -12.046, -77.043, 8),
    ("Venezuela", "Caracas", 10.481, -66.904, 4),
    ("Estados Unidos", "Miami", 25.762, -80.192, 5),
    ("Argentina", "Buenos Aires", -34.604, -58.382, 3),
    ("Chile", "Santiago", -33.449, -70.669, 2),
    ("Ecuador", "Quito", -0.181, -78.468, 2),
    ("España", "Madrid", 40.417, -3.704, 2),
]

EDADES = [("25-34", 34), ("35-44", 38), ("45-54", 20), ("18-24", 4), ("55+", 4)]
SECTORES = [("Tecnología", 22), ("Servicios profesionales", 16), ("Comercio y retail", 14), ("Fintech", 9),
            ("Salud", 8), ("Educación", 8), ("Manufactura", 7), ("Logística", 6), ("Inmobiliario", 5),
            ("Alimentos y bebidas", 5)]
TAMANOS = [("1-10", 30), ("11-50", 32), ("51-200", 22), ("201-1.000", 11), ("Más de 1.000", 5)]

# Origen según el canal por el que llegó el perfil.
ORIGENES = {
    "formulario_luma": [("Luma · clase gratuita", 55), ("Luma · evento presencial", 25), ("Luma · webinar de IA", 20)],
    "correo": [("Newsletter 30X", 40), ("Campaña LinkedIn Ads", 30), ("Campaña Google Ads", 15), ("Referido de un alumno", 15)],
    "mensaje": [("Campaña Meta Ads", 35), ("Instagram orgánico", 25), ("Referido de un alumno", 25), ("YouTube 30X", 15)],
}
CAMPANAS = {
    "Campaña LinkedIn Ads": ["IA para líderes · oct", "Sales Machine · retargeting"],
    "Campaña Google Ads": ["Búsqueda: curso ventas B2B", "Búsqueda: MBA alternativo"],
    "Campaña Meta Ads": ["Inmersión Bogotá · oct", "Clase gratuita IA · reels"],
}


def elegir(rng, opciones):
    valores, pesos = zip(*opciones)
    return rng.choices(valores, weights=pesos, k=1)[0]


def main(semilla: int = 30) -> None:
    rng = random.Random(semilla)
    perfiles = json.loads(PERFILES.read_text(encoding="utf-8"))
    salida = {}
    for p in perfiles:
        pais, ciudad, lat, lon, _ = rng.choices(CIUDADES, weights=[c[4] for c in CIUDADES], k=1)[0]
        origen = elegir(rng, ORIGENES.get(p["canal"], ORIGENES["mensaje"]))
        salida[p["id"]] = {
            "pais": pais,
            "ciudad": ciudad,
            # Pequeño desplazamiento para que los puntos de una ciudad no caigan exactamente encima.
            "lat": round(lat + rng.uniform(-0.25, 0.25), 3),
            "lon": round(lon + rng.uniform(-0.25, 0.25), 3),
            "edad": elegir(rng, EDADES),
            "sector": elegir(rng, SECTORES),
            "tamano_empresa": elegir(rng, TAMANOS),
            "origen": origen,
            "campana": rng.choice(CAMPANAS[origen]) if origen in CAMPANAS else None,
        }
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Demografía sintética de {len(salida)} perfiles en {SALIDA}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
