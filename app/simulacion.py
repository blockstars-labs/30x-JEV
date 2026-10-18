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
    # Desglose para el análisis en lenguaje natural del panel de reglas (app/analisis.py).
    contenido_programa, motivos, dudas, errores = Counter(), Counter(), Counter(), Counter()
    ventas_directo = ventas_por_confirmar = contenido_general = 0
    for p in perfiles:
        d = decidir(juicios[p["id"]], p["temas"], politica)
        rutas[d.ruta] += 1
        if d.ruta != "automatico":
            motivos[d.motivo] += 1
            dudas.update(d.dudas)
            ventas_por_confirmar += d.accion_propuesta == "pasar_a_ventas"
            continue
        e = decidir(juicios_desde_etiquetas(p["etiquetas"]), p["temas"], politica)
        auto += 1
        ok += (d.accion, d.programa) == (e.accion, e.programa)
        ventas_indebidas += d.accion == "pasar_a_ventas" and e.accion != "pasar_a_ventas"
        invalidos += not p["etiquetas"]["perfil_valido"]
        if d.accion == "pasar_a_ventas":
            ventas_directo += 1
        elif d.accion == "nutrir_programa":
            contenido_programa[d.programa] += 1
        else:
            contenido_general += 1
        if (d.accion, d.programa) != (e.accion, e.programa):
            if d.accion == "pasar_a_ventas":
                errores["ventas_indebidas"] += 1
            elif e.accion == "pasar_a_ventas":
                errores["ventas_no_detectadas"] += 1
            else:
                errores["contenido_distinto"] += 1
    return {"perfiles": len(perfiles), "automatizacion": auto / len(perfiles),
            "precision": ok / auto if auto else 0.0, "pases_a_ventas_indebidos": ventas_indebidas,
            "invalidos_automaticos": invalidos, "rutas": dict(rutas),
            "detalle": {"ventas_directo": ventas_directo, "ventas_por_confirmar": ventas_por_confirmar,
                        "contenido_programa": dict(contenido_programa), "contenido_general": contenido_general,
                        "motivos": dict(motivos), "dudas": dict(dudas), "errores": dict(errores)}}
