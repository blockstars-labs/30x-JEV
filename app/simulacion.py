"""Simula una política sobre respuestas de JEV ya obtenidas: cero llamadas al modelo.

La usan la calibración (scripts/calibrar.py) y el panel de política de la vista. La decisión
esperada se calcula con la MISMA política simulada, porque los pesos cambian también qué programa
le corresponde a cada persona según la verdad conocida.
"""

from collections import Counter

from app.motor import juicios_desde_etiquetas
from app.politica import Juicios, decidir


def medir(perfiles: list[dict], juicios: dict[str, Juicios], politica: dict) -> dict:
    rutas = Counter()
    auto = ok = ventas_indebidas = invalidos = 0
    for p in perfiles:
        d = decidir(juicios[p["id"]], p["temas"], politica)
        rutas[d.ruta] += 1
        if d.ruta != "automatico":
            continue
        e = decidir(juicios_desde_etiquetas(p["etiquetas"]), p["temas"], politica)
        auto += 1
        ok += (d.accion, d.programa) == (e.accion, e.programa)
        ventas_indebidas += d.accion == "pasar_a_ventas" and e.accion != "pasar_a_ventas"
        invalidos += not p["etiquetas"]["perfil_valido"]
    return {"perfiles": len(perfiles), "automatizacion": auto / len(perfiles),
            "precision": ok / auto if auto else 0.0, "pases_a_ventas_indebidos": ventas_indebidas,
            "invalidos_automaticos": invalidos, "rutas": dict(rutas)}
