"""Fase 6 · Umbrales y acciones aprendidos: 30X no fija números, solo elige cuánto riesgo acepta.

Lo que se aprende de los datos (fuera de muestra, como el umbral de programa de scripts/entrenar_programas.py):
- confianza de asignación: desde qué probabilidad de pertenencia la asignación a un segmento se mantiene
  con datos que el modelo no vio (validación cruzada; los segmentos de cada partición se emparejan con los
  definitivos por cercanía de centros),
- propensión individual: regresión logística del resultado; desde qué probabilidad una persona tiene una
  tasa de resultado claramente mayor que la base (así alguien con señales fuertes llega a un asesor aunque
  su segmento no lo haga),
- acción de cada segmento: asesor si su tasa supera la base con margen; si no, el contenido del programa que
  más eligen (catálogo: todos los programas que aparecen en los datos); si no, contenido general.
Lo que no se aprende: cuánto riesgo acepta 30X (conservador, normal o agresivo) y las reglas fijas
(perfil no genuino → persona; duda → LLM y luego persona).
"""

import math

import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, KFold, cross_val_predict

from app.descubrimiento.seleccionar import estandarizar

REJILLA = [round(float(x), 2) for x in np.arange(0.30, 0.96, 0.05)]


def probabilidades(Z: np.ndarray, centros: np.ndarray, tau: float) -> np.ndarray:
    """Probabilidad de pertenencia a cada segmento: softmax de la distancia al centro (escala tau)."""
    d2 = ((Z[:, None, :] - centros[None, :, :]) ** 2).sum(axis=2)
    logits = -d2 / tau
    logits -= logits.max(axis=1, keepdims=True)
    e = np.exp(logits)
    return e / e.sum(axis=1, keepdims=True)


def escala(Z: np.ndarray, centros: np.ndarray, etiquetas: np.ndarray) -> float:
    d2 = ((Z - centros[etiquetas]) ** 2).sum(axis=1)
    return float(max(np.median(d2), 1e-6))


def umbral_desde_curva(conf: np.ndarray, acierto: np.ndarray, objetivo: float, minimo: int = 10) -> dict:
    curva = []
    for t in REJILLA:
        m = conf >= t
        if m.sum() >= minimo:
            curva.append({"umbral": t, "cobertura": round(float(m.mean()), 3), "precision": round(float(acierto[m].mean()), 3),
                          "casos": int(m.sum())})
    elegido = next((c for c in curva if c["precision"] >= objetivo), None)
    if elegido is None and curva:
        elegido = max(curva, key=lambda c: c["precision"])
    return {"elegido": elegido, "curva": curva}


def umbral_asignacion(Z: np.ndarray, k: int, etiquetas: np.ndarray, centros: np.ndarray, objetivo: float,
                      semilla: int = 30, objetivo_asesor: float | None = None) -> dict:
    """Confianza mínima para asignar sin ayuda, medida con filas que el modelo no vio. Con `objetivo_asesor`,
    también la confianza (más estricta) que exige pasar a alguien a un asesor."""
    conf, acierto = [], []
    for tr, te in KFold(5, shuffle=True, random_state=semilla).split(Z):
        km = KMeans(n_clusters=k, n_init=10, random_state=semilla).fit(Z[tr])
        costo = ((km.cluster_centers_[:, None, :] - centros[None, :, :]) ** 2).sum(axis=2)
        filas, cols = linear_sum_assignment(costo)
        mapa = dict(zip(filas, cols))
        tau = escala(Z[tr], km.cluster_centers_, km.labels_)
        p = probabilidades(Z[te], km.cluster_centers_, tau)
        pred = np.array([mapa[i] for i in p.argmax(axis=1)])
        conf += p.max(axis=1).tolist()
        acierto += (pred == etiquetas[te]).tolist()
    conf, acierto = np.array(conf), np.array(acierto, dtype=float)
    resultado = umbral_desde_curva(conf, acierto, objetivo)
    resultado["tasa_baja_confianza"] = round(1 - (resultado["elegido"] or {}).get("cobertura", 0.0), 3)
    if objetivo_asesor is not None:
        resultado["asesor"] = umbral_desde_curva(conf, acierto, objetivo_asesor)["elegido"]
    return resultado


def modelo_propension(X: np.ndarray, y: np.ndarray, base: float, lift_objetivo: float, semilla: int = 30) -> dict:
    """Regresión logística del resultado, exportada como pesos (se aplica en línea sin scikit-learn)."""
    Z, media, desv = estandarizar(X)
    m = LogisticRegression(C=0.5, max_iter=3000)
    oof = cross_val_predict(m, Z, y, cv=StratifiedKFold(5, shuffle=True, random_state=semilla), method="predict_proba")[:, 1]
    m.fit(Z, y)
    # Umbral: desde qué probabilidad la tasa real (fuera de muestra) llega a lift_objetivo veces la base.
    objetivo = min(0.95, base * lift_objetivo)
    curva, elegido = [], None
    for t in np.unique(np.round(np.quantile(oof, np.linspace(0.5, 0.97, 25)), 3)):
        sel = oof >= t
        if sel.sum() >= 10:
            tasa = float(y[sel].mean())
            curva.append({"umbral": float(t), "cobertura": round(float(sel.mean()), 3), "tasa": round(tasa, 3), "casos": int(sel.sum())})
    elegido = next((c for c in curva if c["tasa"] >= objetivo), None)
    from sklearn.metrics import roc_auc_score
    auc = float(roc_auc_score(y, oof)) if len(set(y)) > 1 else None
    return {"coeficientes": m.coef_[0].round(5).tolist(), "intercepto": float(round(m.intercept_[0], 5)),
            "media": media.tolist(), "desv": desv.tolist(), "auc_fuera_de_muestra": None if auc is None else round(auc, 3),
            "tasa_objetivo": round(objetivo, 3), "umbral": None if elegido is None else elegido["umbral"],
            "cobertura": None if elegido is None else elegido["cobertura"], "curva": curva}


def acciones_por_segmento(segmentos: list[dict], base: float | None, riesgo: dict, tipo_resultado: str | None,
                          hay_accion: bool) -> None:
    """Asigna a cada segmento su siguiente paso y la frase que lo justifica (in situ)."""
    abandono = tipo_resultado == "abandono"
    for s in segmentos:
        tasa, ic = s.get("tasa"), s.get("ic", [0, 1])
        top = s.get("accion_top") if s.get("accion_top", {}).get("confiable") else None
        if base is None:
            s["accion"] = {"tipo": "contenido_tema", "programa": None,
                           "porque": "Sin columna de resultado: se le envía contenido sobre lo que lo distingue."}
            continue
        if abandono:
            if tasa >= base * riesgo["lift_asesor"] and ic[0] > base:
                s["accion"] = {"tipo": "contactar", "programa": None,
                               "porque": f"Abandona el {tasa:.0%} frente al {base:.0%} del total: el equipo lo contacta a tiempo."}
            else:
                s["accion"] = {"tipo": "seguimiento", "programa": None,
                               "porque": f"Abandona el {tasa:.0%}: seguimiento normal."}
            continue
        if tasa >= base * riesgo["lift_asesor"] and ic[0] > base:
            s["accion"] = {"tipo": "asesor", "programa": top["valor"] if top else None,
                           "porque": (f"Convierte el {tasa:.0%} frente al {base:.0%} del total ({tasa / base:.1f} veces)"
                                      + (f"; de quienes compraron aquí, el {top['proporcion']:.0%} eligió {top['valor']}." if top else "."))}
        elif top and tasa >= base * 0.5:
            s["accion"] = {"tipo": "contenido_programa", "programa": top["valor"],
                           "porque": f"Convierte el {tasa:.0%}; de quienes compraron aquí, el {top['proporcion']:.0%} eligió {top['valor']}."}
        else:
            s["accion"] = {"tipo": "contenido_general", "programa": None,
                           "porque": f"Convierte el {tasa:.0%} frente al {base:.0%} del total: contenido general, sin presión comercial."}
        if not hay_accion and s["accion"]["tipo"] == "contenido_programa":
            s["accion"]["tipo"] = "contenido_general"
