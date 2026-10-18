"""Clasifica un lote de perfiles con el formato del archivo de perfiles de 30X (CRM).

Esos perfiles ya vienen categorizados (Rol, Dolor principal, Objetivo principal, Temas de interés),
así que no se le pregunta a JEV: se les aplica directo la política de Pálpito, con certeza total en
esas categorías. Las columnas que 30X ya calculó (Programa del CRM, Programa sugerido) no entran a la
decisión: solo se devuelven para comparar.

El archivo de 30X no trae intención de compra; si la fila no la trae, se asume "Explorando", que es
conservador: sin intención declarada nadie pasa a ventas.
"""

from app.catalogo import DOLORES, INTENCION, OBJETIVOS, PROGRAMAS, ROLES, TEMAS
from app.motor import juicios_desde_etiquetas
from app.politica import ACCIONES, decidir, explicar

LIMITE_LOTE = 100
INTENCION_POR_DEFECTO = 1  # "Explorando"


def _normal(t) -> str:
    return " ".join(str(t or "").strip().lower().split())


def _indice(opciones) -> dict[str, str]:
    """Acepta la etiqueta de 30X o el id del catálogo, sin importar mayúsculas."""
    idx = {}
    for o in opciones:
        idx[_normal(o.etiqueta)] = o.id
        idx[_normal(o.id)] = o.id
    return idx


ROL, DOLOR, OBJETIVO = _indice(ROLES), _indice(DOLORES), _indice(OBJETIVOS)
NIVEL_INTENCION = {_normal(o.etiqueta): i for i, o in enumerate(INTENCION)} | {_normal(o.id): i for i, o in enumerate(INTENCION)}


def _campo(fila: dict, *nombres: str) -> str:
    claves = {_normal(k): v for k, v in fila.items()}
    for n in nombres:
        if _normal(n) in claves:
            return str(claves[_normal(n)] or "").strip()
    return ""


def clasificar_perfil(fila: dict, politica: dict) -> dict:
    rol_txt, dolor_txt, obj_txt = _campo(fila, "Rol"), _campo(fila, "Dolor principal", "Dolor"), _campo(fila, "Objetivo principal", "Objetivo")
    rol = ROL.get(_normal(rol_txt), "sin_dato")
    dolor = DOLOR.get(_normal(dolor_txt), "ninguno")
    objetivo = OBJETIVO.get(_normal(obj_txt), "otro")
    temas = [t.strip().lower() for t in _campo(fila, "Temas de interés", "Temas").replace("—", "").replace("|", ",").split(",")]
    temas = [t for t in dict.fromkeys(temas) if t in TEMAS]
    intencion_txt = _campo(fila, "Intención", "Intencion")
    intencion = NIVEL_INTENCION.get(_normal(intencion_txt), INTENCION_POR_DEFECTO)

    no_reconocidos = [f"{n}: “{t}”" for n, t, v, d in (("Rol", rol_txt, rol, "sin_dato"), ("Dolor", dolor_txt, dolor, "ninguno"), ("Objetivo", obj_txt, objetivo, "otro"))
                      if t and t != "—" and v == d and _normal(t) not in (ROL | DOLOR | OBJETIVO)]
    j = juicios_desde_etiquetas({"rol": rol, "dolor": dolor, "objetivo": objetivo, "intencion": intencion, "perfil_valido": True})
    d = decidir(j, temas, politica)
    return {
        "id": _campo(fila, "ID") or None,
        "entrada": {"rol": rol, "dolor": dolor, "objetivo": objetivo, "temas": temas, "intencion": INTENCION[intencion].etiqueta,
                    "intencion_supuesta": not intencion_txt},
        "programa": d.programa,
        "programa_nombre": PROGRAMAS[d.programa],
        "regla": d.regla_programa,
        "accion_propuesta": d.accion_propuesta,
        "accion_texto": ACCIONES[d.accion_propuesta],
        "ruta": d.ruta,
        "razones": d.razones,
        "explicacion": explicar(j, d),
        "no_reconocidos": no_reconocidos,
        "comparar": {"programa_crm": _campo(fila, "Programa") or None, "programa_sugerido_30x": _campo(fila, "Programa sugerido") or None},
    }


def clasificar_lote(filas: list[dict], politica: dict) -> dict:
    if not filas:
        raise ValueError("El archivo no tiene perfiles debajo del encabezado.")
    if len(filas) > LIMITE_LOTE:
        raise ValueError(f"Máximo {LIMITE_LOTE} perfiles por lote; llegaron {len(filas)}.")
    return {"resultados": [clasificar_perfil(f, politica) for f in filas], "limite": LIMITE_LOTE}
