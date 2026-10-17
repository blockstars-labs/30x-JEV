"""Extrae proporciones agregadas del archivo de demo de 30X (uso local).

El archivo de 30X nunca entra al repo. Este script solo guarda conteos agregados por categoría
(sin filas ni IDs) en data/distribuciones.json, que el generador usa para que los perfiles
sintéticos tengan proporciones realistas.

Uso:
    python scripts/construir_distribuciones.py "C:/ruta/perfiles-30x-anonimo.xlsx"
"""

import collections
import json
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalogo import DOLORES, OBJETIVOS, PROGRAMAS, ROLES  # noqa: E402

SALIDA = Path(__file__).resolve().parent.parent / "data" / "distribuciones.json"


def mapa(opciones) -> dict[str, str]:
    return {o.etiqueta: o.id for o in opciones}


def main(ruta_xlsx: str) -> None:
    hoja = openpyxl.load_workbook(ruta_xlsx)["Perfiles"]
    filas = hoja.iter_rows(values_only=True)
    columnas = next(filas)
    idx = {nombre: i for i, nombre in enumerate(columnas)}

    roles, dolores, objetivos = mapa(ROLES), mapa(DOLORES), mapa(OBJETIVOS)
    programas = {v: k for k, v in PROGRAMAS.items()}
    bandas = {"0-3 (baja)": "baja", "4-6 (media)": "media", "7-8 (alta)": "alta", "9-10 (muy alta)": "muy_alta"}

    por_programa = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    total = collections.Counter()
    for fila in filas:
        if len(fila) < len(columnas) or fila[idx["ID"]] is None:
            continue
        prog = programas[fila[idx["Programa sugerido"]]]
        total[prog] += 1
        grupo = por_programa[prog]
        grupo["rol"][roles[fila[idx["Rol"]]]] += 1
        grupo["dolor"][dolores[fila[idx["Dolor principal"]]]] += 1
        grupo["objetivo"][objetivos[fila[idx["Objetivo principal"]]]] += 1
        grupo["banda"][bandas[fila[idx["Banda de afinidad"]]]] += 1
        temas = [t.strip() for t in str(fila[idx["Temas de interés"]]).split(",") if t.strip() not in ("", "—")]
        grupo["n_temas"][str(len(temas))] += 1
        for t in temas:
            grupo["temas"][t] += 1

    salida = {
        "_nota": "Conteos agregados derivados de la muestra de demo de 30X. No contiene filas ni datos de personas.",
        "programa_sugerido": dict(total),
        "por_programa": {p: {k: dict(c) for k, c in g.items()} for p, g in por_programa.items()},
    }
    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Escrito {SALIDA} ({sum(total.values())} perfiles agregados)")


if __name__ == "__main__":
    main(sys.argv[1])
