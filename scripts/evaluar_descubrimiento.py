"""Evalúa el descubrimiento automático de segmentos y las alertas de riesgo contra la verdad conocida.

Mide lo que importa para confiar en el motor sin mirar los datos a mano:
1. Calidad: ARI entre los segmentos descubiertos y los grupos reales de cada dataset.
2. Estabilidad: ARI entre dos descubrimientos con semillas distintas sobre los mismos datos.
3. Dinámica: si el monitor detecta el lote nuevo y si el segmento que aparece es el grupo nuevo real.
4. Reglas fijas: ninguna fila marcada como no genuina entra a un segmento.
5. Generalidad: el mismo motor, sin cambios, sobre otro dataset (registro a webinar).
6. Alertas: precisión y cobertura del riesgo de abandono en la cohorte en curso.
7. Costo estimado con JEV conectado.

La verdad (data/*/verdad.json) solo la lee este script; el motor nunca la ve.

Uso:
    python scripts/evaluar_descubrimiento.py          # modo de .env (motor local si no hay llave)
    python scripts/evaluar_descubrimiento.py live     # JEV conectado (cuesta, ver docs/PUESTA_EN_MARCHA.md)
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

from sklearn.metrics import adjusted_rand_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.alertas import cargar_registros, construir_filas, entrenar, generar_alertas  # noqa: E402
from app.descubrimiento.datos import leer_dataset  # noqa: E402
from app.descubrimiento.jev_dinamico import crear_cliente_dinamico  # noqa: E402
from app.descubrimiento.pipeline import cargar_config, descubrir  # noqa: E402
from app.descubrimiento.reporte import ciclo_dinamico  # noqa: E402
from app.llm import crear_llm  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "data" / "descubrimiento"
SALIDA = RAIZ / "reportes" / "evaluacion_descubrimiento"


def ari(asig: dict, verdad: dict) -> tuple[float, int]:
    """ARI sobre las filas genuinas asignadas, y cuántas filas no genuinas se colaron en un segmento."""
    ids = [i for i in asig if verdad.get(i, "trampa") != "trampa"]
    coladas = sum(1 for i in asig if verdad.get(i) == "trampa")
    return round(adjusted_rand_score([verdad[i] for i in ids], [asig[i] for i in ids]), 3), coladas


def evaluar(modo: str | None = None) -> dict:
    cfg = cargar_config()
    cliente = crear_cliente_dinamico(modo, modelo=cfg["modelo_jev"], trabajadores=cfg["trabajadores"])
    llm = crear_llm()
    llm = llm if llm.__class__.__name__ == "LLMLive" else None
    verdad = json.loads((DATOS / "verdad.json").read_text(encoding="utf-8"))
    inicio = time.time()
    r = {"modo": cliente.modo, "llm": getattr(llm, "modelo", None) if llm else None}

    a, lote = leer_dataset(DATOS / "inscripciones_eventos.csv"), leer_dataset(DATOS / "inscripciones_eventos_lote2.csv")
    rep = ciclo_dinamico(a, lote, "inscripciones_eventos", cliente, cfg, llm)
    v1, v2 = rep.pop("_versiones")
    r["calidad"], r["reglas_fijas"] = {}, {}
    r["calidad"]["inscripciones_v1"], r["reglas_fijas"]["coladas_v1"] = ari(v1["asignaciones_muestra"], verdad["inscripciones_eventos"])

    # Estabilidad: otra semilla, mismos datos.
    otra = descubrir(a, "inscripciones_eventos", cliente, llm, cfg, semilla=31)
    comunes = [i for i in v1["asignaciones_muestra"] if i in otra["asignaciones_muestra"]]
    r["estabilidad_ari"] = round(adjusted_rand_score([v1["asignaciones_muestra"][i] for i in comunes],
                                                     [otra["asignaciones_muestra"][i] for i in comunes]), 3)

    # Dinámica: el monitor y el segmento que aparece.
    verdad_v2 = {**verdad["inscripciones_eventos"], **verdad["inscripciones_eventos_lote2"]}
    r["calidad"]["inscripciones_v2"], r["reglas_fijas"]["coladas_v2"] = ari(v2["asignaciones_muestra"], verdad_v2)
    aparecidos = [c["segmento"] for c in rep["comparacion"]["cambios"] if c["tipo"] == "aparecio"]
    grupos = {sid: Counter(verdad_v2[i] for i, s in v2["asignaciones_muestra"].items() if s == sid) for sid in aparecidos}
    nuevos_reales = sum(1 for g in verdad["inscripciones_eventos_lote2"].values() if g == "clinicas_normativa")
    r["dinamica"] = {
        "monitor_pidio_redescubrir": rep["lote"]["monitor"]["redescubrir"],
        "alertas_monitor": rep["lote"]["monitor"]["alertas"],
        "segmentos_aparecidos": [{"segmento": sid, "grupo_real_principal": g.most_common(1)[0][0] if g else None,
                                  "pureza": round(g.most_common(1)[0][1] / sum(g.values()), 3) if g else 0.0,
                                  "cobertura_grupo_nuevo": round(g.get("clinicas_normativa", 0) / max(1, nuevos_reales), 3)}
                                 for sid, g in grupos.items()],
        "personas_movidas": rep["n_movidos"],
    }

    # Generalidad: otro dataset, mismo código.
    web = descubrir(leer_dataset(DATOS / "registro_webinar.csv"), "registro_webinar", cliente, llm, cfg)
    r["calidad"]["webinar"], r["reglas_fijas"]["coladas_webinar"] = ari(web["asignaciones_muestra"], verdad["registro_webinar"])

    # Alertas de riesgo: la cohorte en curso contra quién abandona de verdad.
    filas = construir_filas(cargar_registros())
    version = entrenar(filas, cliente, llm, cfg)
    actuales = [f for f in filas if not f["estado_final"]]
    al = generar_alertas(version, actuales, cliente)
    abandona = json.loads((RAIZ / "data" / "alumnos" / "verdad.json").read_text(encoding="utf-8"))["alumnos"]
    altas = [x["alumno"] for x in al["alertas"] if x["nivel"] == "alto"]
    todas = [x["alumno"] for x in al["alertas"]]
    reales = [f["alumno"] for f in actuales if abandona[f["alumno"]]["abandona"]]
    r["alertas"] = {"alumnos": len(actuales), "abandonaran": len(reales), "alto": len(altas), "medio": al["medias"],
                    "precision_alto": round(sum(abandona[i]["abandona"] for i in altas) / max(1, len(altas)), 3),
                    "precision_alertados": round(sum(abandona[i]["abandona"] for i in todas) / max(1, len(todas)), 3),
                    "cobertura": round(sum(i in todas for i in reales) / max(1, len(reales)), 3),
                    "auc_fuera_de_muestra": al["modelo"]["auc_fuera_de_muestra"]}

    e = v2["costo"]["estimado_live"]
    r["costo_jev_conectado"] = {"descubrir_usd": e.get("jev_usd"), "llm_usd": e.get("llm_usd"),
                                "asignar_10000_usd": rep["costo"]["por_10000_usd"], "alertas_150_usd": al["costo_jev_usd"]}
    r["segundos"] = round(time.time() - inicio, 1)
    return r


def markdown(r: dict) -> str:
    c, d, al = r["calidad"], r["dinamica"], r["alertas"]
    lineas = [f"# Evaluación del descubrimiento ({'JEV conectado' if r['modo'] == 'live' else 'motor local'})", "",
              "| Medida | Valor |", "|---|---|",
              f"| ARI inscripciones, versión 1 | {c['inscripciones_v1']} |",
              f"| ARI inscripciones, versión 2 | {c['inscripciones_v2']} |",
              f"| ARI webinar (mismo motor) | {c['webinar']} |",
              f"| Estabilidad entre semillas (ARI) | {r['estabilidad_ari']} |",
              f"| Filas no genuinas dentro de un segmento | {sum(r['reglas_fijas'].values())} |",
              f"| El monitor pidió redescubrir | {'sí' if d['monitor_pidio_redescubrir'] else 'no'} |"]
    for s in d["segmentos_aparecidos"]:
        lineas.append(f"| Segmento que apareció ({s['segmento']}) | grupo real «{s['grupo_real_principal']}», pureza {s['pureza']:.0%}, "
                      f"cubre el {s['cobertura_grupo_nuevo']:.0%} del grupo nuevo |")
    lineas += [f"| Alertas: precisión en riesgo alto | {al['precision_alto']:.0%} ({al['alto']} alumnos) |",
               f"| Alertas: cobertura de quienes abandonarán | {al['cobertura']:.0%} de {al['abandonaran']} |",
               f"| Alertas: AUC fuera de muestra | {al['auc_fuera_de_muestra']} |",
               f"| Costo con JEV: descubrir / asignar 10.000 | USD {r['costo_jev_conectado']['descubrir_usd']} / "
               f"USD {r['costo_jev_conectado']['asignar_10000_usd']} |", "",
               f"Tiempo total: {r['segundos']} s."]
    if r["modo"] != "live":
        lineas += ["", "Con el motor local, JEV se reemplaza por coincidencia de palabras: agrupar por significado (sobre todo en "
                       "texto libre, como el webinar) necesita JEV conectado. Estas cifras validan la mecánica del motor."]
    return "\n".join(lineas) + "\n"


if __name__ == "__main__":
    resultado = evaluar(sys.argv[1] if len(sys.argv) > 1 else None)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    sufijo = resultado["modo"]
    Path(f"{SALIDA}_{sufijo}.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    Path(f"{SALIDA}_{sufijo}.md").write_text(markdown(resultado), encoding="utf-8")
    print(markdown(resultado))
