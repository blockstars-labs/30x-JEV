"""Reporte de clusterización dinámica: la historia completa en datos y en palabras, para la vista y en Markdown.

Cuenta lo que pasa sin que nadie defina nada: Pálpito lee un dataset, crea sus variables, encuentra los
segmentos, llega gente nueva, detecta que los segmentos dejaron de describirla, redescubre y explica qué cambió.
"""

from datetime import datetime, timezone

from app.descubrimiento.asignar import Segmentador
from app.descubrimiento.pipeline import descubrir
from app.descubrimiento.versiones import MonitorDeDeriva, comparar, guardar

COSTO_POR_PERSONA_TXT = "asignar a una persona nueva"


def resumen(v: dict) -> dict:
    """Lo que la vista necesita de una versión (sin la muestra completa ni los centros)."""
    usadas = set(v["seleccion"]["usadas"])
    bases_usadas = {k.split("=", 1)[0] for k in usadas}
    variables = [{"id": x["id"], "descripcion": x["descripcion"], "instrucciones": x["instrucciones"], "origen": x["origen"],
                  "ronda": x["ronda"], "estado": "usada" if x["id"] in bases_usadas else x["estado"],
                  "motivo": x["motivo"] or v["seleccion"]["descartes"].get(x["id"], ""),
                  "relevancia": round(v["seleccion"]["relevancia"].get(x["id"], 0.0), 2)} for x in v["variables"]]
    estructuradas = [{"id": k, "relevancia": round(r, 2), "estado": "usada" if k in usadas else "descartada",
                      "motivo": v["seleccion"]["descartes"].get(k, "")}
                     for k, r in v["seleccion"]["relevancia"].items() if not k.split("=", 1)[0] in {x["id"] for x in v["variables"]}]
    u = v["umbrales"]
    return {
        "dataset": v["dataset"], "version": v.get("version"), "padre": v.get("padre"), "fecha": v["fecha"], "modo": v.get("modo"),
        "proponente": v.get("proponente"), "riesgo": v["riesgo"], "vetos": v.get("vetos"),
        "ficha": {k: v["ficha"][k] for k in ("filas", "resultado", "tipo_resultado", "valores_positivos", "tasa_positiva", "accion", "acciones")}
                 | {"columnas": [{k: c[k] for k in ("nombre", "tipo", "rol", "motivo")} for c in v["ficha"]["columnas"]]},
        "segmentos": [{k: s.get(k) for k in ("id", "nombre", "descripcion", "n", "proporcion", "tasa", "ic", "lift", "accion",
                                              "accion_top", "rasgos", "rasgos_negativos")} for s in v["segmentos"]],
        "variables": variables, "estructuradas": estructuradas,
        "umbrales": {"asignacion": u["asignacion"]["elegido"], "asesor": u.get("asesor"), "genuino_min": u["genuino_min"],
                     "nivel": u["nivel"], "propension": None if not u.get("propension") else
                     {k: u["propension"][k] for k in ("auc_fuera_de_muestra", "umbral", "cobertura", "tasa_objetivo")},
                     "curva_asignacion": u["asignacion"]["curva"]},
        "k_puntajes": v["k_puntajes"], "linea_base": v["linea_base"], "costo": v["costo"], "segundos": v.get("segundos"),
        "muestra": len(v["muestra"]["ids"]),
    }


def ciclo_dinamico(filas: list[dict], lote: list[dict], dataset: str, cliente, cfg: dict, llm=None, guardar_en=None) -> dict:
    """v1 → llega un lote → el monitor avisa → v2 → comparación. Devuelve todo lo que cuenta la historia."""
    v1 = descubrir(filas, dataset, cliente, llm, cfg)
    v1["motivo"] = "Primer descubrimiento"
    v1 = guardar(v1, guardar_en) if guardar_en else {**v1, "version": 1}
    seg1 = Segmentador(v1, cliente)
    monitor = MonitorDeDeriva(v1, cfg)
    id_col = next(c["nombre"] for c in v1["ficha"]["columnas"] if c["tipo"] == "identificador")
    asig_lote_1 = {}
    for f, a in zip(lote, seg1.asignar_lote(lote)):
        monitor.registrar(a)
        asig_lote_1[f[id_col]] = a
    estado = monitor.estado()
    v2 = descubrir(filas + lote, dataset, cliente, llm, cfg, padre=v1, nuevas_desde=len(filas))
    v2["motivo"] = "Redescubrimiento: " + ("; ".join(estado["alertas"]) if estado["alertas"] else "lote nuevo")
    v2 = guardar(v2, guardar_en) if guardar_en else {**v2, "version": 2}
    seg2 = Segmentador(v2, cliente)
    asig_lote_2 = {f[id_col]: a for f, a in zip(lote, seg2.asignar_lote(lote))}
    recientes = set(asig_lote_1)
    cmp = comparar(v1, v2, {**v1["asignaciones_muestra"], **{k: a["segmento"] for k, a in asig_lote_1.items()}},
                   {**v2["asignaciones_muestra"], **{k: a["segmento"] for k, a in asig_lote_2.items()}}, recientes)
    nombres1 = {s["id"]: s["nombre"] for s in v1["segmentos"]}
    nombres2 = {s["id"]: s["nombre"] for s in v2["segmentos"]}
    pareja = cmp.get("pareja", {})
    movidos = [{"persona": k, "antes": nombres1[a["segmento"]], "ahora": nombres2[asig_lote_2[k]["segmento"]],
                "accion_antes": a["accion"]["tipo"], "accion_ahora": asig_lote_2[k]["accion"]["tipo"],
                "por_que": asig_lote_2[k]["explicacion"]}
               for k, a in asig_lote_1.items() if pareja.get(a["segmento"]) != asig_lote_2[k]["segmento"]]
    costo_asignar = [a["costo_usd"] for a in asig_lote_2.values() if a["costo_usd"]]
    por_persona = sum(costo_asignar) / len(costo_asignar) if costo_asignar else 0.0
    return {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dataset": dataset,
        "v1": resumen(v1), "v2": resumen(v2), "lote": {"n": len(lote), "monitor": estado},
        "comparacion": {k: cmp[k] for k in ("comunes", "cambios", "flujos", "movidas")},
        "movidos": movidos[:12], "n_movidos": len(movidos),
        "costo": {"descubrir_v1_usd": v1["costo"]["total_usd"], "descubrir_v2_usd": v2["costo"]["total_usd"],
                  "estimado_live_v1": v1["costo"]["estimado_live"], "estimado_live_v2": v2["costo"]["estimado_live"],
                  "por_persona_usd": round(por_persona, 6), "por_10000_usd": round(por_persona * 10_000, 3)},
        "_versiones": (v1, v2),
    }


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.0f} %"


def markdown(rep: dict, otro: dict | None = None) -> str:
    """Reporte de clusterización dinámica en Markdown (se descarga desde la vista)."""
    v1, v2, cmp, lote = rep["v1"], rep["v2"], rep["comparacion"], rep["lote"]
    lineas = [f"# Reporte de clusterización dinámica · {rep['dataset']}", "",
              f"Generado {rep['generado']} · modo JEV: {v1['modo']} · proponente de variables: {v1['proponente']}.",
              "Nadie definió las variables, los umbrales ni los segmentos: salieron de los datos.", "",
              "## 1. Primer descubrimiento", "",
              f"Pálpito leyó {v1['ficha']['filas']} filas y {len(v1['ficha']['columnas'])} columnas. Resultado detectado: "
              f"«{v1['ficha']['resultado']}» ({', '.join(v1['ficha']['valores_positivos'])}), tasa {_pct(v1['ficha']['tasa_positiva'])}.", ""]
    excluidas = [c for c in v1["ficha"]["columnas"] if c["rol"] == "excluida"]
    if excluidas:
        lineas += ["Columnas que no usó, y por qué:", ""] + [f"- **{c['nombre']}**: {c['motivo']}" for c in excluidas] + [""]
    usadas = [x for x in v1["variables"] if x["estado"] == "usada"]
    lineas += [f"Creó {len(v1['variables'])} variables como preguntas para JEV y se quedó con {len(usadas)}; "
               f"encontró {len(v1['segmentos'])} segmentos:", "", "| Segmento | Personas | Tasa | Siguiente paso |", "| --- | --- | --- | --- |"]
    lineas += [f"| {s['nombre']} | {_pct(s['proporcion'])} | {_pct(s.get('tasa'))} | {s['accion']['tipo'].replace('_', ' ')}"
               f"{' · ' + s['accion']['programa'] if s['accion'].get('programa') else ''} |" for s in v1["segmentos"]]
    lineas += ["", "## 2. Llega gente nueva", "", f"Llegaron {lote['n']} personas. El monitor de deriva comparó con la línea base:", ""]
    lineas += [f"- {a}" for a in lote["monitor"]["alertas"]] or ["- Sin cambios relevantes."]
    lineas += ["", "## 3. Redescubrimiento", "", f"Con la gente nueva, Pálpito encontró {len(v2['segmentos'])} segmentos. Qué cambió:", ""]
    lineas += [f"- {c['texto']}" for c in cmp["cambios"]]
    lineas += ["", "| Segmento | Personas | Tasa | Siguiente paso |", "| --- | --- | --- | --- |"]
    lineas += [f"| {s['nombre']} | {_pct(s['proporcion'])} | {_pct(s.get('tasa'))} | {s['accion']['tipo'].replace('_', ' ')}"
               f"{' · ' + s['accion']['programa'] if s['accion'].get('programa') else ''} |" for s in v2["segmentos"]]
    if rep["movidos"]:
        lineas += ["", "## 4. Personas que cambiaron de segmento", ""]
        lineas += [f"- {m['persona']}: de «{m['antes']}» a «{m['ahora']}»" for m in rep["movidos"][:8]]
    u = v2["umbrales"]
    lineas += ["", "## 5. Umbrales que aprendió", "",
               f"- Confianza mínima para asignar sin ayuda: {u['asignacion']['umbral']:.2f} (cobertura {_pct(u['asignacion']['cobertura'])}, "
               f"acierto fuera de muestra {_pct(u['asignacion']['precision'])}).",
               f"- Perfil genuino (regla fija, calibrada con JEV real): {u['genuino_min']}."]
    if u.get("propension"):
        lineas.append(f"- Modelo individual: AUC fuera de muestra {u['propension']['auc_fuera_de_muestra']}; pasa a un asesor desde "
                      f"{_pct(u['propension']['umbral'])} de probabilidad.")
    c = rep["costo"]
    lineas += ["", "## 6. Costo", "",
               f"- Descubrir con JEV real y el LLM: ~USD {c['estimado_live_v2']['total_usd']} (solo JEV: USD {c['estimado_live_v2']['jev_usd']}; "
               f"con Claude Haiku: USD {c['estimado_live_v2']['con_haiku_usd']}).",
               f"- {COSTO_POR_PERSONA_TXT.capitalize()}: USD {c['por_persona_usd']:.6f}; 10.000 personas: USD {c['por_10000_usd']}."]
    if otro:
        lineas += ["", "## 7. El mismo motor, otro dataset", "",
                   f"«{otro['dataset']}» trae otras columnas y otro resultado («{otro['ficha']['resultado']}»). Sin cambiar código, "
                   f"encontró {len(otro['segmentos'])} segmentos:", ""]
        lineas += [f"- {s['nombre']}: {_pct(s['proporcion'])} de las personas, tasa {_pct(s.get('tasa'))}" for s in otro["segmentos"]]
    if v1["modo"] == "mock":
        lineas += ["", "> Generado con el motor local (JEV sin conectar). Con JEV conectado, el mismo reporte usa sus respuestas."]
    return "\n".join(lineas) + "\n"
