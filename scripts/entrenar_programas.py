"""Aprende qué perfil tiene cada programa de 30X a partir de los deals del CRM.

Entrada: el archivo anonimizado de perfiles de 30X (data/privado/, nunca se sube al repo).
Usa solo a las personas con un programa en el CRM (deal abierto, ganado o perdido) y solo las
variables que Pálpito tiene al clasificar a alguien nuevo: rol, dolor y objetivo (respuestas de JEV,
mismas categorías del catálogo) y temas de interés (dato del formulario). No usa país (casi vacío),
ni afinidad, banda o programa sugerido: son salidas de la clasificación actual de 30X y usarlas
haría que el modelo copiara esa regla (fuga de datos).

Qué hace:
1. Agrupa los programas con pocos casos en "Otro" (con menos de MIN_CASOS no se puede aprender).
2. Separa 80 % para entrenar y 20 % para probar (estratificado, semilla fija). Además corre
   validación cruzada de 5 particiones, porque con ~300 casos un solo corte depende de la suerte.
3. Entrena una red neuronal pequeña (MLP) y una regresión logística, y las compara contra dos
   líneas base: "siempre el programa más común" y la columna "Programa sugerido" de 30X.
4. Calcula el umbral de confianza: la probabilidad mínima desde la cual el modelo acierta al menos
   PRECISION_OBJETIVO de las veces (con predicciones fuera de muestra).
5. Saca los rasgos que más distinguen a cada programa (lift frente al total). Solo publica rasgos
   que comparten al menos MIN_CELDA personas, para no exponer a nadie.

Salidas:
- reportes/entrenamiento_programas.json: métricas completas (reportes/ no se sube).
- config/politica.json, sección "perfiles_por_programa": umbral y rasgos agregados. No se activa
  sola: app/politica.py no la usa hasta que el equipo lo decida.

Uso:
    python scripts/entrenar_programas.py [ruta_xlsx]
"""

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import openpyxl
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.inspection import permutation_importance

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app.catalogo import DOLORES, OBJETIVOS, ROLES, TEMAS  # noqa: E402

XLSX = RAIZ / "data" / "privado" / "perfiles-30x-anonimo.xlsx"
REPORTE = RAIZ / "reportes" / "entrenamiento_programas.json"
POLITICA = RAIZ / "config" / "politica.json"

SEMILLA = 30
MIN_CASOS = 19            # programas con menos casos van a "Otro"
MIN_CELDA = 5             # mínimo de personas para publicar un rasgo agregado
PRECISION_OBJETIVO = 0.8  # el umbral busca esta precisión cuando el modelo actúa solo
PESO_ESTADO = {"Cliente (pagó)": 2.0, "En proceso": 1.0, "Oportunidad perdida": 0.5}

# Cómo se compara la columna "Programa sugerido" de 30X con los programas del CRM (supuesto).
SUGERIDO_A_CRM = {"AI Sales": "AI Sales", "Inmersión Ejecutiva": "30X Executive Program",
                  "Sales Machine": "Sales Machine", "Hardcore AI": "AI for devs"}


# Programa del CRM -> programa del catálogo de Pálpito (supuesto: debe confirmarlo 30X). Los que no
# tienen equivalente (AI for Executives, AI Second Brain, Otro) nunca reemplazan a la regla actual.
PROGRAMA_CRM_A_CATALOGO = {"AI Sales": "ai_sales", "Sales Machine": "sales_machine",
                           "30X Executive Program": "inmersion_ejecutiva", "AI for devs": "hardcore_ai"}


def cargar(ruta: Path) -> list[dict]:
    ws = openpyxl.load_workbook(ruta, read_only=True)["Perfiles"]
    filas = list(ws.iter_rows(values_only=True))
    enc = filas[0]
    return [dict(zip(enc, f)) for f in filas[1:] if f and f[0] and f[enc.index("Programa")] not in (None, "", "—")]


def a_id(opciones, etiqueta: str) -> str:
    for o in opciones:
        if o.etiqueta == etiqueta:
            return o.id
    return "otro"


def rasgos(fila: dict) -> dict[str, int]:
    r = {f"rol={a_id(ROLES, fila['Rol'])}": 1,
         f"dolor={a_id(DOLORES, fila['Dolor principal'])}": 1,
         f"objetivo={a_id(OBJETIVOS, fila['Objetivo principal'])}": 1}
    for t in str(fila["Temas de interés"] or "").replace("—", "").split(","):
        if t.strip() in TEMAS:
            r[f"tema={t.strip()}"] = 1
    return r


def nombre_rasgo(clave: str) -> str:
    campo, valor = clave.split("=", 1)
    fuente = {"rol": ROLES, "dolor": DOLORES, "objetivo": OBJETIVOS}.get(campo)
    if fuente:
        etiqueta = next((o.etiqueta for o in fuente if o.id == valor), valor)
        return f"{campo.capitalize()}: {etiqueta}"
    return f"Tema: {valor}"


def umbral_de_confianza(prob: np.ndarray, y: np.ndarray, clases: np.ndarray) -> dict:
    pred, conf = clases[prob.argmax(1)], prob.max(1)
    curva = []
    for t in np.round(np.arange(0.2, 0.96, 0.05), 2):
        m = conf >= t
        if m.sum() >= 10:
            curva.append({"umbral": float(t), "cobertura": round(float(m.mean()), 3), "precision": round(float((pred[m] == y[m]).mean()), 3), "casos": int(m.sum())})
    elegido = next((c for c in curva if c["precision"] >= PRECISION_OBJETIVO), None)
    return {"elegido": elegido, "curva": curva}


def escribir_seccion(seccion: dict) -> None:
    """Agrega o reemplaza "perfiles_por_programa" en config/politica.json sin reformatear el resto."""
    texto = POLITICA.read_text(encoding="utf-8")
    json.loads(texto)  # falla aquí si el archivo ya venía roto
    marca = ',\n\n  "perfiles_por_programa": '
    if marca in texto:
        texto = texto[: texto.index(marca)] + "\n}\n"
    cuerpo = texto.rstrip()
    assert cuerpo.endswith("}")
    bloque = json.dumps(seccion, ensure_ascii=False, indent=2).replace("\n", "\n  ")
    nuevo = cuerpo[:-1].rstrip() + marca + bloque + "\n}\n"
    json.loads(nuevo)
    POLITICA.write_text(nuevo, encoding="utf-8")


def main(ruta: Path = XLSX) -> None:
    filas = cargar(ruta)
    conteo = Counter(f["Programa"] for f in filas)
    grande = {p for p, n in conteo.items() if n >= MIN_CASOS}
    y = np.array([f["Programa"] if f["Programa"] in grande else "Otro" for f in filas])
    pesos = np.array([PESO_ESTADO.get(f["Estado"], 1.0) for f in filas])
    dic = [rasgos(f) for f in filas]
    columnas = sorted({k for d in dic for k in d})
    X = np.array([[d.get(c, 0) for c in columnas] for d in dic], dtype=float)
    clases = np.array(sorted(set(y)))

    idx = np.arange(len(y))
    tr, te = train_test_split(idx, test_size=0.2, stratify=y, random_state=SEMILLA)

    modelos = {
        "red_neuronal": MLPClassifier(hidden_layer_sizes=(16,), alpha=1.0, max_iter=3000, random_state=SEMILLA),
        "regresion_logistica": LogisticRegression(C=0.5, max_iter=3000),
    }
    resultados = {}
    for nombre, m in modelos.items():
        if nombre == "red_neuronal":
            m.fit(X[tr], y[tr])  # MLPClassifier no admite pesos por muestra
        else:
            m.fit(X[tr], y[tr], sample_weight=pesos[tr])
        p = m.predict(X[te])
        prob = m.predict_proba(X[te])
        top2 = np.mean([y[te][i] in m.classes_[np.argsort(prob[i])[-2:]] for i in range(len(te))])
        oof = cross_val_predict(type(m)(**m.get_params()), X, y, cv=StratifiedKFold(5, shuffle=True, random_state=SEMILLA), method="predict_proba")
        resultados[nombre] = {
            "prueba_20": {"exactitud": round(accuracy_score(y[te], p), 3), "f1_macro": round(f1_score(y[te], p, average="macro"), 3), "top2": round(float(top2), 3), "casos": len(te)},
            "validacion_cruzada_5": {"exactitud": round(float((m.classes_[oof.argmax(1)] == y).mean()), 3), "f1_macro": round(f1_score(y, m.classes_[oof.argmax(1)], average="macro"), 3)},
            "umbral": umbral_de_confianza(oof, y, m.classes_),
        }

    mayoritaria = Counter(y[tr]).most_common(1)[0][0]
    sug = np.array([SUGERIDO_A_CRM.get(f["Programa sugerido"], "Otro") for f in filas])
    sug = np.where(np.isin(sug, clases), sug, "Otro")
    lineas_base = {
        "siempre_el_mas_comun": {"programa": mayoritaria, "exactitud": round(float((y[te] == mayoritaria).mean()), 3)},
        "programa_sugerido_30x": {"exactitud": round(float((sug[te] == y[te]).mean()), 3), "nota": "Mapeo supuesto entre 'Programa sugerido' y programas del CRM."},
    }

    red = modelos["red_neuronal"]
    imp = permutation_importance(red, X[te], y[te], n_repeats=30, random_state=SEMILLA)
    importancia = sorted(({"rasgo": nombre_rasgo(c), "importancia": round(float(v), 4)} for c, v in zip(columnas, imp.importances_mean)), key=lambda d: -d["importancia"])[:12]

    # Rasgos que distinguen a cada programa: lift = P(rasgo | programa) / P(rasgo).
    perfiles = {}
    base = X.mean(0)
    for c in clases:
        sel = X[y == c]
        lista = []
        for j, col in enumerate(columnas):
            n = int(sel[:, j].sum())
            if n >= MIN_CELDA and base[j] > 0:
                lista.append({"rasgo": nombre_rasgo(col), "clave": col, "personas": n, "frecuencia": round(float(sel[:, j].mean()), 3), "lift": round(float(sel[:, j].mean() / base[j]), 2)})
        perfiles[c] = {"casos": int((y == c).sum()), "rasgos": sorted([r for r in lista if r["lift"] > 1.1], key=lambda r: -r["lift"])[:6]}

    mejor = max(resultados, key=lambda k: resultados[k]["validacion_cruzada_5"]["f1_macro"])
    reporte = {
        "datos": {"personas_con_programa": len(y), "entrenamiento": len(tr), "prueba": len(te), "programas": {c: int((y == c).sum()) for c in clases}, "variables": len(columnas)},
        "modelos": resultados, "lineas_base": lineas_base, "mejor_modelo": mejor,
        "importancia_red_neuronal": importancia, "perfiles_por_programa": perfiles,
    }
    REPORTE.parent.mkdir(exist_ok=True)
    REPORTE.write_text(json.dumps(reporte, ensure_ascii=False, indent=1), encoding="utf-8")

    elegido = resultados[mejor]["umbral"]["elegido"]
    # Modelo que usa app/politica.py: regresión logística entrenada con todos los casos (pesos agregados,
    # sin datos de personas). Es el que eligió el umbral y se puede calcular sin scikit-learn.
    final = LogisticRegression(C=0.5, max_iter=3000).fit(X, y, sample_weight=pesos)
    seccion = {
        "_nota": ("Aprendido de los deals del CRM de 30X con scripts/entrenar_programas.py (agregados; ningún dato de personas). "
                  "Aún no lo usa app/politica.py: activarlo es decisión del equipo."),
        "modelo": mejor,
        "umbral_confianza": elegido["umbral"] if elegido else None,
        "precision_objetivo": PRECISION_OBJETIVO,
        "cobertura_con_umbral": elegido["cobertura"] if elegido else None,
        "programas": {c: {"casos": v["casos"], "rasgos": [{k: r[k] for k in ("clave", "rasgo", "lift", "frecuencia")} for r in v["rasgos"]]} for c, v in perfiles.items()},
        "activo": True,
        "programa_catalogo": PROGRAMA_CRM_A_CATALOGO,
        "pesos": {
            "variables": columnas,
            "clases": [str(c) for c in final.classes_],
            "coeficientes": [[round(float(w), 4) for w in fila] for fila in final.coef_],
            "intercepto": [round(float(b), 4) for b in final.intercept_],
        },
    }
    escribir_seccion(seccion)

    print(f"{len(y)} personas con programa · entrenamiento {len(tr)} · prueba {len(te)} · {len(columnas)} variables")
    for k, v in lineas_base.items():
        print(f"  línea base {k:24} exactitud {v['exactitud']:.0%}")
    for k, v in resultados.items():
        u = v["umbral"]["elegido"]
        umbral = f"umbral {u['umbral']} (cobertura {u['cobertura']:.0%})" if u else f"sin umbral que llegue a {PRECISION_OBJETIVO:.0%} de precisión"
        print(f"  {k:24} prueba: exactitud {v['prueba_20']['exactitud']:.0%} · top-2 {v['prueba_20']['top2']:.0%} · F1 {v['prueba_20']['f1_macro']:.2f}"
              f" | CV5: exactitud {v['validacion_cruzada_5']['exactitud']:.0%} · F1 {v['validacion_cruzada_5']['f1_macro']:.2f} | {umbral}")
    print(f"Reporte: {REPORTE}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else XLSX)
