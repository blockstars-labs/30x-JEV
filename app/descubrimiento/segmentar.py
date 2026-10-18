"""Fase 5 · Descubrimiento de segmentos: nadie dice cuántos hay ni cuáles son.

El código prueba de 2 a k_max segmentos (k-means) y elige el número que mejor combina:
- estabilidad: los mismos segmentos aparecen con otras submuestras (índice de Rand ajustado),
- separación: qué tan distintos son entre sí (silueta),
- diferencia en el resultado: que se distingan en conversión (o abandono) y en el programa que eligen
  (V de Cramér). Es el criterio de un buen segmento que pidió 30X.
Las variables que predicen el resultado pesan más en la distancia, así los segmentos se forman alrededor
de lo que importa para decidir. Cada segmento queda descrito por sus rasgos distintivos (lift frente al
total, como scripts/entrenar_programas.py) y con nombre: lo escribe el LLM o, sin llave, una plantilla.
"""

import json
import math
from collections import Counter

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score

from app.descubrimiento.seleccionar import estandarizar


def cramer_v(etiquetas: np.ndarray, otra: np.ndarray) -> float:
    a, b = np.unique(etiquetas), np.unique(otra)
    if len(a) < 2 or len(b) < 2:
        return 0.0
    tabla = np.array([[np.sum((etiquetas == x) & (otra == z)) for z in b] for x in a], dtype=float)
    esperado = tabla.sum(1, keepdims=True) * tabla.sum(0, keepdims=True) / tabla.sum()
    chi2 = np.nansum((tabla - esperado) ** 2 / np.where(esperado == 0, 1, esperado))
    return float(math.sqrt(chi2 / (tabla.sum() * (min(tabla.shape) - 1))))


def espacio(X: np.ndarray, relevancia: list[float], hay_resultado: bool) -> tuple[np.ndarray, dict]:
    """Escala y pondera los rasgos para medir distancias entre personas.

    Las probabilidades de JEV y los indicadores ya viven entre 0 y 1: se dejan en esa escala (estandarizarlos
    haría que un rasgo raro pesara más que uno común). Los números continuos se estandarizan a media 0 y
    desviación 0,5, comparable a un rasgo 0/1. Lo que predice el resultado pesa más en la distancia.
    """
    media = X.mean(axis=0)
    unitario = (X.min(axis=0) >= 0) & (X.max(axis=0) <= 1)
    desv = np.where(unitario, 1.0, np.maximum(X.std(axis=0), 1e-9) * 2)
    pesos = np.array([0.4 + 0.6 * r for r in relevancia]) if hay_resultado else np.ones(X.shape[1])
    Z = (X - media) / desv * pesos
    return Z, {"media": media.tolist(), "desv": desv.tolist(), "pesos": pesos.tolist()}


def _p_dos_proporciones(e1: int, n1: int, e2: int, n2: int) -> float:
    """Valor p (dos colas) de que dos tasas sean iguales."""
    if min(n1, n2) == 0:
        return 1.0
    p = (e1 + e2) / (n1 + n2)
    if p in (0.0, 1.0):
        return 1.0
    z = (e1 / n1 - e2 / n2) / math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return math.erfc(abs(z) / math.sqrt(2))


def _se_distinguen(a: int, b: int, etiquetas: np.ndarray, y: np.ndarray, y_accion: list | None, min_casos: int = 5) -> bool:
    ma, mb = etiquetas == a, etiquetas == b
    if _p_dos_proporciones(int(y[ma].sum()), int(ma.sum()), int(y[mb].sum()), int(mb.sum())) < 0.05:
        return True
    if y_accion is None:
        return False
    tops = []
    for m in (ma, mb):
        acciones = Counter(y_accion[i] for i in np.where(m)[0] if y[i] and y_accion[i])
        total = sum(acciones.values())
        if total < min_casos:
            return False
        accion, n = acciones.most_common(1)[0]
        tops.append((accion, n / total))
    return tops[0][0] != tops[1][0] and min(tops[0][1], tops[1][1]) >= 0.4


def fusionar_indistintos(Z: np.ndarray, etiquetas: np.ndarray, y: np.ndarray, y_accion: list | None) -> np.ndarray:
    """Une, de a pares, segmentos vecinos que no se distinguen en el resultado ni en el programa que eligen."""
    etiquetas = etiquetas.copy()
    while True:
        ids = sorted(set(etiquetas.tolist()))
        if len(ids) <= 2:
            return etiquetas
        centros = {i: Z[etiquetas == i].mean(axis=0) for i in ids}
        pares = sorted(((float(((centros[a] - centros[b]) ** 2).sum()), a, b) for a in ids for b in ids if a < b))
        fusion = next(((a, b) for _, a, b in pares if not _se_distinguen(a, b, etiquetas, y, y_accion)), None)
        if fusion is None:
            return etiquetas
        etiquetas[etiquetas == fusion[1]] = fusion[0]


def elegir_k(Z: np.ndarray, y: np.ndarray | None, y_accion: list | None, cfg: dict, semilla: int = 30) -> tuple[int, list[dict], np.ndarray | None]:
    """Cuántos segmentos hay, sin que nadie lo diga.

    Con resultado: para cada k se fusionan los segmentos vecinos que no se distinguen en el resultado
    (prueba de dos proporciones) ni en el programa que eligen; gana el k que deja más segmentos distintos y
    estables. Es la definición de buen segmento que dio 30X: no basta con agrupar gente parecida, tiene que
    diferenciarse. Sin resultado: el que mejor combina estabilidad y silueta.
    Devuelve (k, puntajes, etiquetas finales ya fusionadas o None).
    """
    n = len(Z)
    minimo = max(10, int(cfg["min_segmento"] * n))
    rng = np.random.default_rng(semilla)
    puntajes = []
    for k in range(2, min(cfg["k_max"], n // minimo) + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=semilla).fit(Z)
        etiquetas = km.labels_
        tam = np.bincount(etiquetas, minlength=k)
        if tam.min() < minimo:
            puntajes.append({"k": k, "valido": False, "motivo": f"un segmento con menos de {minimo} personas"})
            continue
        sil = silhouette_score(Z, etiquetas, sample_size=min(n, 1500), random_state=semilla)
        aris = []
        for b in range(cfg["bootstrap_k"]):
            idx = rng.choice(n, size=int(0.8 * n), replace=False)
            otro = KMeans(n_clusters=k, n_init=4, random_state=semilla + b + 1).fit(Z[idx])
            aris.append(adjusted_rand_score(etiquetas, otro.predict(Z)))
        estabilidad = float(np.mean(aris))
        fila = {"k": k, "valido": True, "estabilidad": round(estabilidad, 3), "silueta": round(float(sil), 3)}
        if y is not None:
            finales = fusionar_indistintos(Z, etiquetas, y, y_accion)
            fila.update({"separacion": round(cramer_v(etiquetas, y), 3), "distintos": len(set(finales.tolist())),
                         "_finales": finales})
        fila["puntaje"] = round(0.55 * estabilidad + 0.45 * (sil + 1) / 2, 4)
        puntajes.append(fila)
    validos = [p for p in puntajes if p["valido"]]
    if not validos:
        return 2, puntajes, None
    if y is not None:
        buenos = [p for p in validos if p["estabilidad"] >= cfg.get("estabilidad_min", 0.7)] or validos
        mejor = max(buenos, key=lambda p: (p["distintos"], p["estabilidad"]))
        finales = mejor["_finales"]
        for p in puntajes:
            p.pop("_finales", None)
        return mejor["k"], puntajes, finales
    mejor = max(validos, key=lambda p: (p["puntaje"], -p["k"]))
    return mejor["k"], puntajes, None


def ajustar(Z: np.ndarray, k: int, semilla: int = 30) -> KMeans:
    return KMeans(n_clusters=k, n_init=20, random_state=semilla).fit(Z)


def wilson(exitos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = exitos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centro - margen), min(1.0, centro + margen)


def describir(Xraw: np.ndarray, claves: list[str], descripciones: dict[str, tuple[str, str, str]], etiquetas: np.ndarray,
              y: np.ndarray | None, y_accion: list | None, min_celda: int = 5) -> list[dict]:
    """Tamaño, resultado, programa típico y rasgos distintivos de cada segmento."""
    n = len(etiquetas)
    media_total = Xraw.mean(axis=0)
    desv_total = Xraw.std(axis=0)
    desv_total[desv_total < 1e-9] = 1.0
    base = float(y.mean()) if y is not None else None
    segmentos = []
    for c in sorted(set(etiquetas.tolist())):
        m = etiquetas == c
        seg = {"id": f"s{c + 1}", "indice": int(c), "n": int(m.sum()), "proporcion": round(float(m.mean()), 4)}
        if y is not None:
            exitos = int(y[m].sum())
            seg["tasa"] = round(exitos / m.sum(), 4)
            seg["ic"] = [round(v, 4) for v in wilson(exitos, int(m.sum()))]
            seg["lift"] = round(seg["tasa"] / base, 2) if base else None
        if y_accion is not None and y is not None:
            acciones = Counter(y_accion[i] for i in np.where(m)[0] if y[i] and y_accion[i])
            if acciones:
                a, na = acciones.most_common(1)[0]
                seg["accion_top"] = {"valor": a, "casos": na, "proporcion": round(na / sum(acciones.values()), 3),
                                     "confiable": na >= min_celda}
                seg["acciones"] = dict(acciones.most_common())
        media_seg = Xraw[m].mean(axis=0)
        efecto = (media_seg - media_total) / desv_total
        rasgos = []
        for j in np.argsort(-efecto):
            if efecto[j] < 0.4 or len(rasgos) >= 4:
                break
            rasgos.append(_rasgo(claves[j], descripciones, media_seg[j], media_total[j], efecto[j], Xraw[:, j]))
        if not rasgos:   # ningún rasgo fuerte: se describe con los que más se acercan
            rasgos = [_rasgo(claves[j], descripciones, media_seg[j], media_total[j], efecto[j], Xraw[:, j])
                      for j in np.argsort(-efecto)[:2] if efecto[j] > 0.1]
        negativos = [_rasgo(claves[j], descripciones, media_seg[j], media_total[j], efecto[j], Xraw[:, j])
                     for j in np.argsort(efecto)[:2] if efecto[j] <= -0.6]
        seg["rasgos"], seg["rasgos_negativos"] = rasgos, negativos
        segmentos.append(seg)
    return segmentos


def _rasgo(clave, descripciones, seg, total, efecto, columna) -> dict:
    desc, corta, fuente = descripciones[clave]
    proporcion = set(np.unique(columna)) <= {0.0, 1.0} or (columna.min() >= 0 and columna.max() <= 1)
    return {"clave": clave, "descripcion": desc, "corta": corta, "fuente": fuente, "segmento": round(float(seg), 3),
            "total": round(float(total), 3), "efecto": round(float(efecto), 2), "proporcion": bool(proporcion)}


# ---------- Nombres ----------
SISTEMA_NOMBRES = """Pones nombre a segmentos de personas que descubrió un sistema a partir de los datos de 30X.
Para cada segmento recibes su tamaño, su tasa de resultado, el programa que más eligen y sus rasgos distintivos.
nombre: de 3 a 7 palabras en español, concreto, que describa a las personas (por ejemplo "Fundadores que quieren ordenar sus ventas").
descripcion: una frase en español con lo que los distingue, sin inventar nada que no esté en los rasgos."""

ESQUEMA_NOMBRES = {
    "type": "object",
    "properties": {"segmentos": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"}, "nombre": {"type": "string"}, "descripcion": {"type": "string"}},
        "required": ["id", "nombre", "descripcion"], "additionalProperties": False}}},
    "required": ["segmentos"], "additionalProperties": False,
}


def _pct(x: float) -> str:
    return f"{x * 100:.0f} %"


def nombrar(segmentos: list[dict], tipo_resultado: str | None, llm=None, modelo: str | None = None) -> dict:
    """Pone nombre y descripción a cada segmento. Devuelve el uso del LLM (o vacío si se usó la plantilla)."""
    if llm is not None and hasattr(llm, "json"):
        resumen = [{"id": s["id"], "proporcion": s["proporcion"], "tasa": s.get("tasa"), "lift": s.get("lift"),
                    "programa_top": (s.get("accion_top") or {}).get("valor"),
                    "rasgos": [f"{r['descripcion']} ({_pct(r['segmento'])} vs {_pct(r['total'])})" if r["proporcion"]
                               else r["descripcion"] for r in s["rasgos"]]} for s in segmentos]
        datos, entrada, salida = llm.json(SISTEMA_NOMBRES, json.dumps({"tipo_resultado": tipo_resultado, "segmentos": resumen},
                                                                       ensure_ascii=False), ESQUEMA_NOMBRES, max_tokens=8000,
                                          **({"modelo": modelo} if modelo else {}))
        if datos:
            por_id = {d["id"]: d for d in datos["segmentos"]}
            for s in segmentos:
                d = por_id.get(s["id"])
                if d:
                    s["nombre"], s["descripcion"] = d["nombre"], d["descripcion"]
            if all("nombre" in s for s in segmentos):
                return {"tokens_entrada": entrada, "tokens_salida": salida, "modelo": modelo}
    for s in segmentos:
        s.setdefault("nombre", _nombre_plantilla(s))
        s.setdefault("descripcion", _descripcion_plantilla(s, tipo_resultado))
    return {}


def _nombre_plantilla(s: dict) -> str:
    """Nombre sin LLM: los dos rasgos que más lo distinguen, en una frase corta."""
    partes = []
    for r in s["rasgos"]:
        texto = f"hablan de «{r['corta']}»" if r["fuente"] == "jev" else (r["corta"] if r["proporcion"] else f"más {r['corta']}")
        if texto not in partes:
            partes.append(texto)
        if len(partes) == 2:
            break
    if not partes and s.get("rasgos_negativos"):
        partes = [f"sin {s['rasgos_negativos'][0]['corta']}"]
    if not partes:
        return "Perfil promedio"
    nombre = " · ".join(partes)
    return nombre[0].upper() + nombre[1:]


def _descripcion_plantilla(s: dict, tipo_resultado: str | None) -> str:
    partes = [f"{_pct(s['proporcion'])} de las personas"]
    if s.get("tasa") is not None:
        verbo = "abandona" if tipo_resultado == "abandono" else "convierte"
        partes.append(f"{verbo} el {_pct(s['tasa'])} ({s['lift']:.1f} veces el promedio)".replace(".", ","))
    if s.get("accion_top", {}).get("confiable"):
        partes.append(f"suele elegir {s['accion_top']['valor']}")
    rasgos = [r["descripcion"] for r in s["rasgos"][:2]]
    texto = ", ".join(partes) + "."
    if rasgos:
        texto += " Se distingue porque " + "; ".join(r[0].lower() + r[1:] for r in rasgos) + "."
    return texto
