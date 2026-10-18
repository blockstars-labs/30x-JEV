"""Fase 4 · Selección de variables: el código decide cuáles sirven, con los datos.

Mismo enfoque de aprendizaje en datos que scripts/entrenar_programas.py (Jairo): regresión logística,
validación con datos no vistos y umbrales que salen de los datos. Se descartan, en orden:
1. las que casi no varían (no separan a nadie),
2. las inestables (JEV responde distinto al repetir la pregunta),
3. las que duplican a otra (correlación muy alta),
4. las que no ayudan a predecir el resultado ni el programa: selección por estabilidad, una regresión
   logística L1 sobre 30 submuestras; se queda lo que el modelo elige de forma consistente.
"""

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict

MIN_CASOS_CLASE = 8


def estandarizar(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    media = X.mean(axis=0)
    desv = X.std(axis=0)
    desv[desv < 1e-9] = 1.0
    return (X - media) / desv, media, desv


def _l1(C: float, multiclase: bool) -> LogisticRegression:
    # scikit-learn 1.9: la penalización L1 se pide con l1_ratio=1; liblinear solo acepta dos clases.
    return LogisticRegression(C=C, l1_ratio=1.0, solver="saga" if multiclase else "liblinear", max_iter=5000)


def _frecuencias_l1(Z: np.ndarray, y: np.ndarray, C: float, repeticiones: int, semilla: int) -> np.ndarray:
    rng = np.random.default_rng(semilla)
    conteo = np.zeros(Z.shape[1])
    hechas = 0
    multiclase = len(set(y.tolist())) > 2
    for _ in range(repeticiones):
        idx = rng.choice(len(y), size=len(y) // 2, replace=False)
        if len(set(y[idx])) < 2:
            continue
        m = _l1(C, multiclase)
        m.fit(Z[idx], y[idx])
        conteo += (np.abs(m.coef_) > 1e-6).any(axis=0)
        hechas += 1
    return conteo / max(1, hechas)


def _mejor_C(Z: np.ndarray, y: np.ndarray, semilla: int) -> float:
    """C de la L1 elegido por validación cruzada (pérdida logarítmica fuera de muestra)."""
    from sklearn.metrics import log_loss
    clases = np.unique(y)
    if min(np.bincount(np.searchsorted(clases, y))) < 3:
        return 0.3
    cv = StratifiedKFold(3, shuffle=True, random_state=semilla)
    mejor, mejor_perdida = 0.3, float("inf")
    for C in (0.03, 0.1, 0.3, 1.0):
        p = cross_val_predict(_l1(C, len(clases) > 2), Z, y, cv=cv, method="predict_proba")
        perdida = log_loss(y, p, labels=clases)
        if perdida < mejor_perdida:
            mejor, mejor_perdida = C, perdida
    return mejor


def seleccionar(X: np.ndarray, claves: list[str], y: np.ndarray | None, y_accion: list | None,
                inestables: dict[str, float], cfg: dict, semilla: int = 30, prioritarias: set[str] | None = None) -> dict:
    """Devuelve las claves usadas, su relevancia y el motivo de cada descarte.

    `prioritarias`: variables que se conservan aunque no predigan el resultado (las de novedad en un
    redescubrimiento: describen a la gente que acaba de llegar, que es justo la razón de redescubrir).
    """
    prioritarias = prioritarias or set()
    descartes, relevancia = {}, {}
    vivas = []
    for j, k in enumerate(claves):
        col = X[:, j]
        binaria = set(np.unique(col)) <= {0.0, 1.0}
        minoria = min(col.mean(), 1 - col.mean()) if binaria else None
        if col.std() < 1e-6 or (binaria and minoria < 0.02):
            descartes[k] = "Casi no varía: no separa a nadie."
        elif k.split("=", 1)[0] in inestables and inestables[k.split("=", 1)[0]] > cfg["inestable_max"]:
            descartes[k] = f"Inestable: JEV cambia de respuesta al repetirla ({inestables[k.split('=', 1)[0]]:.0%} de las veces)."
        else:
            vivas.append(j)
    Z, _, _ = estandarizar(X[:, vivas]) if vivas else (np.zeros((len(X), 0)), None, None)

    # Relevancia: qué tan seguido la L1 elige cada variable para predecir el resultado y el programa.
    rel = np.zeros(len(vivas))
    if y is not None and len(set(y)) > 1 and vivas:
        C = _mejor_C(Z, y, semilla)
        rel = np.maximum(rel, _frecuencias_l1(Z, y, C, cfg["repeticiones_estabilidad"], semilla))
        if y_accion is not None:
            idx = np.array([i for i, a in enumerate(y_accion) if a and y[i]])
            if len(idx) >= 2 * MIN_CASOS_CLASE:
                etiquetas = np.array([y_accion[i] for i in idx])
                valores, cuentas = np.unique(etiquetas, return_counts=True)
                grandes = set(valores[cuentas >= MIN_CASOS_CLASE])
                etiquetas = np.array([e if e in grandes else "Otro" for e in etiquetas])
                if len(set(etiquetas)) > 1:
                    rel = np.maximum(rel, _frecuencias_l1(Z[idx], etiquetas, 0.5, cfg["repeticiones_estabilidad"], semilla + 1))
    elif vivas:
        # Sin resultado: se prefieren las variables con más variación (las que más separan a las personas).
        var = X[:, vivas].var(axis=0)
        rel = var / var.max() if var.max() > 0 else var
    for j, r in zip(vivas, rel):
        relevancia[claves[j]] = float(r)

    # Duplicadas: de cada par casi idéntico se queda la más relevante.
    orden = sorted(vivas, key=lambda j: -relevancia[claves[j]])
    elegidas = []
    if vivas:
        corr = np.corrcoef(X[:, orden].T) if len(orden) > 1 else np.ones((1, 1))
        corr = np.nan_to_num(corr)
        for a, j in enumerate(orden):
            dup = next((orden[b] for b in range(a) if orden[b] in elegidas and abs(corr[a, b]) >= cfg["corr_max"]), None)
            if dup is not None:
                descartes[claves[j]] = f"Duplica a «{claves[dup]}»."
            else:
                elegidas.append(j)

    usadas = [j for j in elegidas if claves[j].split("=", 1)[0] in prioritarias]
    usadas += [j for j in elegidas if relevancia[claves[j]] >= cfg["frecuencia_min"] and j not in usadas]
    # Si el resultado da poca señal, se completa con los rasgos que más estructuran los datos (ejes principales):
    # un segmento también tiene que ser un grupo de personas parecidas, no solo una tasa.
    objetivo = min(len(elegidas), max(cfg["min_variables"], cfg["max_variables"] // 3))
    if len(usadas) < objetivo:
        estructura = _estructura(X[:, elegidas])
        for j in [elegidas[i] for i in np.argsort(-estructura)]:
            if len(usadas) >= objetivo:
                break
            if j not in usadas:
                usadas.append(j)
    usadas = usadas[: cfg["max_variables"]]
    for j in elegidas:
        if j not in usadas:
            descartes[claves[j]] = (f"No ayuda a predecir el resultado ni el programa (la eligió el {relevancia[claves[j]]:.0%} "
                                    "de las veces)." if y is not None else "Separa menos que las demás.")
    return {"usadas": [claves[j] for j in usadas], "relevancia": relevancia, "descartes": descartes}


def _estructura(X: np.ndarray) -> np.ndarray:
    """Cuánto pesa cada rasgo en los ejes que explican la mitad de la variación de los datos (0 a 1)."""
    if X.shape[1] == 0:
        return np.zeros(0)
    Z, _, _ = estandarizar(X)
    _, S, Vt = np.linalg.svd(Z, full_matrices=False)
    var = S ** 2 / max((S ** 2).sum(), 1e-12)
    m = int(np.searchsorted(np.cumsum(var), 0.5)) + 1
    puntaje = (Vt[:m] ** 2 * var[:m, None]).sum(axis=0)
    return puntaje / max(puntaje.max(), 1e-12)


def predicciones_fuera_de_muestra(X: np.ndarray, y: np.ndarray, semilla: int = 30) -> np.ndarray:
    """Probabilidad del resultado de cada fila, predicha sin haberla visto (para la siguiente ronda de propuesta)."""
    Z, _, _ = estandarizar(X)
    cv = StratifiedKFold(5, shuffle=True, random_state=semilla)
    return cross_val_predict(LogisticRegression(C=0.5, max_iter=3000), Z, y, cv=cv, method="predict_proba")[:, 1]


def inestabilidad(rasgos_a: list[dict], rasgos_b: list[dict]) -> dict[str, float]:
    """Fracción de filas donde la respuesta cruza 0,5 entre dos repeticiones de la misma pregunta."""
    if not rasgos_a:
        return {}
    claves = rasgos_a[0].keys()
    out = {}
    for k in claves:
        cruces = sum((a[k] >= 0.5) != (b[k] >= 0.5) for a, b in zip(rasgos_a, rasgos_b))
        out[k.split("=", 1)[0]] = max(out.get(k.split("=", 1)[0], 0.0), cruces / len(rasgos_a))
    return out
