"""Orquesta el descubrimiento: fases 1 a 6 sobre un dataset, con presupuesto y sin volver a pagar.

descubrir()  → ficha, propuesta, medición (con 2 rondas) y modelo: una versión completa.
recalcular() → solo el modelo (fases 4 a 6) desde lo ya medido: vetos y cambios de riesgo, cero llamadas a JEV.

Barato por diseño:
- se mide una muestra estratificada (por defecto hasta 400 filas), no todo el dataset,
- todas las preguntas de una fila van en una sola llamada y las filas sin texto no llaman a JEV,
- las candidatas se revisan antes de medirlas, la segunda ronda solo mide las variables nuevas,
- con JEV real, lo ya preguntado sale de la caché y hay un tope de gasto por descubrimiento,
- el LLM se llama 1 a 3 veces por descubrimiento, nunca por persona.
"""

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.descubrimiento.aprender import acciones_por_segmento, escala, modelo_propension, probabilidades, umbral_asignacion
from app.descubrimiento.esquema import Ficha, perfilar
from app.descubrimiento.jev_dinamico import PRECIO_USD_POR_MTOK, estimar_tokens
from app.descubrimiento.medir import ajustar_codificador, claves_variable, codificar, describir_rasgo, estado_fila, medir_jev, pregunta_genuina
from app.descubrimiento.proponer import (Variable, prompt_propuesta, proponer_estadistico, proponer_llm, proponer_novedad,
                                         proponer_temas, revisar)
from app.descubrimiento.segmentar import ajustar, describir, elegir_k, espacio, nombrar
from app.descubrimiento.seleccionar import inestabilidad, predicciones_fuera_de_muestra, seleccionar

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = RAIZ / "config" / "descubrimiento.json"
PRECIOS_LLM = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}


class PresupuestoExcedido(RuntimeError):
    pass


def cargar_config(ruta: Path = CONFIG) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def costo_llm(modelo: str, entrada: int, salida: int) -> float:
    pe, ps = PRECIOS_LLM.get(modelo, PRECIOS_LLM["claude-opus-5-5"])
    return (entrada * pe + salida * ps) / 1_000_000


def usd_jev(tokens: int) -> float:
    return tokens * PRECIO_USD_POR_MTOK / 1_000_000


def muestrear(filas: list[dict], ficha: Ficha, n: int, semilla: int) -> list[int]:
    """Índices de una muestra estratificada por resultado (mantiene la tasa del dataset)."""
    rng = random.Random(semilla)
    indices = list(range(len(filas)))
    if n >= len(filas):
        return indices
    if not ficha.resultado:
        return sorted(rng.sample(indices, n))
    pos = [i for i in indices if ficha.positivo(filas[i])]
    neg = [i for i in indices if not ficha.positivo(filas[i])]
    n_pos = round(n * len(pos) / len(filas))
    return sorted(rng.sample(pos, min(n_pos, len(pos))) + rng.sample(neg, min(n - n_pos, len(neg))))


def _es_llm_real(llm) -> bool:
    return llm is not None and hasattr(llm, "json") and llm.__class__.__name__ == "LLMLive"


def descubrir(filas: list[dict], dataset: str, cliente, llm=None, cfg: dict | None = None, riesgo: str | None = None,
              vetos: dict | None = None, semilla: int = 30, padre: dict | None = None, nuevas_desde: int | None = None) -> dict:
    """`nuevas_desde`: en un redescubrimiento por deriva, índice desde el cual las filas son las recién llegadas."""
    cfg = cfg or cargar_config()
    riesgo = riesgo or cfg["riesgo"]
    inicio = time.perf_counter()
    usos_llm, tokens = [], 0
    proponente = "llm" if _es_llm_real(llm) else "estadistico"

    # Fase 1 · Ficha
    ficha = perfilar(filas, cliente, dataset)
    tokens += ficha.tokens_jev
    campos = [c.nombre for c in ficha.por_rol("rasgo", ("texto",))]

    # Muestra (con tope de gasto si JEV es real). Al redescubrir, la mitad son personas recién llegadas.
    n = min(cfg["muestra_max"], len(filas))
    if nuevas_desde is not None:
        nuevas_idx = list(range(nuevas_desde, len(filas)))
        rng = random.Random(semilla)
        recientes = sorted(rng.sample(nuevas_idx, min(len(nuevas_idx), n // 2)))
        previas = muestrear(filas[:nuevas_desde], ficha, n - len(recientes), semilla)
        idx = previas + recientes
    else:
        idx = muestrear(filas, ficha, n, semilla)
    muestra = [filas[i] for i in idx]
    y = [ficha.positivo(f) for f in muestra] if ficha.resultado else None
    y_acc = [f.get(ficha.accion) or None for f in muestra] if ficha.accion else None

    # Fase 2 · Propuesta, ronda 1
    if proponente == "llm":
        retro = None
        if nuevas_desde is not None:
            retro = {"novedad": "Llegaron personas nuevas y la segmentación anterior dejó de describirlas bien. "
                                "Busca también temas que antes no aparecían.",
                     "ejemplos_nuevos": [{c: f.get(c, "")[:200] for c in campos if f.get(c)} for f in filas[nuevas_desde:][:20]]}
        variables, uso = proponer_llm(llm, ficha, muestra, y, y_acc, cfg["modelo_llm"], 1, retro, cfg["max_candidatas"])
        usos_llm.append({**uso, "para": "propuesta ronda 1"})
    else:
        # Sin LLM: la mitad son temas (grupos de palabras que van juntas) y la otra mitad términos que distinguen el resultado.
        variables = []
        if nuevas_desde is not None:
            variables = proponer_novedad(ficha, filas[nuevas_desde:], filas[:nuevas_desde], max_variables=8)
        variables += proponer_temas(ficha, muestra, max_variables=cfg["max_candidatas"] // 2, inicio_id=len(variables) + 1,
                                    semilla=semilla)
        variables += proponer_estadistico(ficha, muestra, y, y_acc, max_variables=cfg["max_candidatas"] - len(variables),
                                          inicio_id=len(variables) + 1)
    tokens += revisar(variables, muestra, cliente, semilla)
    vivas = [v for v in variables if v.estado != "descartada"]

    estimado = estimar(muestra, vivas, campos, cfg)
    if cliente.modo == "live" and estimado["usd"] > cfg["presupuesto_usd"]:
        cabe = int(len(muestra) * cfg["presupuesto_usd"] / estimado["usd"])
        if cabe < cfg["muestra_min"]:
            raise PresupuestoExcedido(f"Medir costaría ~USD {estimado['usd']:.3f} con la muestra mínima; tope USD {cfg['presupuesto_usd']}.")
        idx = idx[:cabe]
        muestra, y = muestra[:cabe], (y[:cabe] if y else None)
        y_acc = y_acc[:cabe] if y_acc else None

    # Fase 3 · Medición (una llamada por fila, guardrail incluido) + consistencia en una submuestra
    rasgos, genuino, t = medir_jev(muestra, vivas, campos, cliente)
    tokens += t
    genuinas = [i for i, g in enumerate(genuino) if g >= cfg["reglas_fijas"]["genuino_min"]]
    sub = [i for i in genuinas if estado_fila(muestra[i], campos)][: cfg["repeticiones_consistencia"]]
    repetidos, _, t = medir_jev([muestra[i] for i in sub], vivas, campos, cliente, con_guardrail=False, uid="repeticion-1")
    tokens += t
    inestables = inestabilidad([rasgos[i] for i in sub], repetidos)
    spec = ajustar_codificador(ficha, filas)
    estructuradas = [codificar(spec, f) for f in muestra]

    materia = {"ficha": ficha.a_dict(), "variables": [v.a_dict() for v in variables], "estructuradas": spec,
               "muestra": {"ids": [_id_fila(ficha, f, i) for f, i in zip(muestra, idx)], "rasgos_jev": rasgos,
                           "estructuradas": estructuradas, "genuino": genuino, "y": y, "y_accion": y_acc},
               "inestables": inestables}

    # Fase 2 y 3, ronda 2: variables nuevas para explicar los errores de la ronda 1
    if cfg["rondas"] >= 2 and y is not None and len(set(y)) > 1:
        provisional = construir_modelo(materia, cfg, riesgo, vetos, semilla=semilla, solo_seleccion=True)
        claves, X, y_g, _ = _matriz(materia, cfg)
        usadas = [claves.index(k) for k in provisional["seleccion"]["usadas"]]
        oof = predicciones_fuera_de_muestra(X[:, usadas], y_g, semilla)
        g_idx = _genuinas(materia, cfg)
        residuos = [0.0] * len(muestra)
        for j, i in enumerate(g_idx):
            residuos[i] = float(y_g[j] - oof[j])
        inicio_id = len(variables) + 1
        if proponente == "llm":
            retro = _retro(variables, provisional, muestra, residuos, campos, y)
            nuevas, uso = proponer_llm(llm, ficha, muestra, y, y_acc, cfg["modelo_llm"], 2, retro, cfg["max_nuevas_ronda2"], inicio_id)
            usos_llm.append({**uso, "para": "propuesta ronda 2"})
        else:
            ya = {p for v in variables for p in (v.pistas or [])}
            nuevas = proponer_estadistico(ficha, muestra, y, y_acc, ronda=2, residuos=residuos, ya_usados=ya,
                                          max_variables=cfg["max_nuevas_ronda2"], inicio_id=inicio_id)
        tokens += revisar(nuevas, muestra, cliente, semilla)
        vivas2 = [v for v in nuevas if v.estado != "descartada"]
        if vivas2:
            r2, _, t = medir_jev(muestra, vivas2, campos, cliente, con_guardrail=False)
            tokens += t
            for a, b in zip(materia["muestra"]["rasgos_jev"], r2):
                a.update(b)
        materia["variables"] += [v.a_dict() for v in nuevas]

    version = construir_modelo(materia, cfg, riesgo, vetos, llm=llm if proponente == "llm" else None, semilla=semilla)
    usos_llm += version.pop("_usos_llm", [])
    version.update(materia_publica(materia))
    # Línea base del encaje: cuánta gente "no se parece a ningún segmento" es normal (60 personas de la muestra).
    from app.descubrimiento.asignar import Segmentador
    base_idx = _genuinas(materia, cfg)[:60]
    asignadas = Segmentador(version, cliente).asignar_lote([muestra[i] for i in base_idx])
    tokens += sum(a["tokens"] for a in asignadas)
    version["linea_base"]["ninguno"] = round(sum(a["ninguno"] >= 0.6 for a in asignadas) / max(1, len(asignadas)), 3)
    version["padre"] = padre.get("version") if padre else None
    version["fecha"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    version["modo"] = cliente.modo
    version["modelo_jev"] = getattr(cliente, "modelo", "mock")
    version["proponente"] = proponente
    version["semilla"] = semilla
    llm_usd = sum(costo_llm(u["modelo"], u["tokens_entrada"], u["tokens_salida"]) for u in usos_llm)
    version["costo"] = {"jev_tokens": tokens, "jev_usd": round(usd_jev(tokens), 5), "llm": usos_llm, "llm_usd": round(llm_usd, 5),
                        "total_usd": round(usd_jev(tokens) + llm_usd, 5),
                        "estimado_live": estimar_live(ficha, muestra, y, y_acc, tokens, cfg)}
    version["segundos"] = round(time.perf_counter() - inicio, 1)
    return version


def _id_fila(ficha: Ficha, fila: dict, i: int) -> str:
    ids = [c.nombre for c in ficha.columnas if c.tipo == "identificador"]
    return str(fila.get(ids[0])) if ids else str(i)


def materia_publica(materia: dict) -> dict:
    return {"ficha": materia["ficha"], "variables": materia["variables"], "estructuradas": materia["estructuradas"],
            "muestra": materia["muestra"], "inestables": materia["inestables"]}


def _genuinas(materia: dict, cfg: dict) -> list[int]:
    return [i for i, g in enumerate(materia["muestra"]["genuino"]) if g >= cfg["reglas_fijas"]["genuino_min"]]


def _matriz(materia: dict, cfg: dict, vetadas: set | None = None):
    """Matriz de rasgos (filas genuinas de la muestra) con todas las variables medidas y las columnas estructuradas."""
    vetadas = vetadas or set()
    m = materia["muestra"]
    g = _genuinas(materia, cfg)
    vivas = [Variable.desde_dict(v) for v in materia["variables"] if v["estado"] != "descartada"]
    claves = [k for v in vivas for k in claves_variable(v) if v.id not in vetadas and k in m["rasgos_jev"][0]]
    claves += [k for k in (m["estructuradas"][0] if m["estructuradas"] else {}) if k.split("=", 1)[0].split(" (")[0] not in vetadas]
    X = np.array([[(m["rasgos_jev"][i] | m["estructuradas"][i]).get(k, 0.0) for k in claves] for i in g], dtype=float)
    y = np.array([m["y"][i] for i in g]) if m["y"] is not None else None
    y_acc = [m["y_accion"][i] for i in g] if m["y_accion"] is not None else None
    return claves, X, y, y_acc


def construir_modelo(materia: dict, cfg: dict, riesgo: str, vetos: dict | None = None, llm=None, semilla: int = 30,
                     solo_seleccion: bool = False) -> dict:
    """Fases 4 a 6 sobre lo ya medido. Sin llamadas a JEV."""
    vetos = vetos or {"variables": [], "segmentos": []}
    ficha = Ficha.desde_dict(materia["ficha"])
    variables = {v["id"]: Variable.desde_dict(v) for v in materia["variables"]}
    claves, X, y, y_acc = _matriz(materia, cfg, set(vetos.get("variables", [])))
    cfg_sel = cfg["seleccion"]
    novedad = {v.id for v in variables.values() if v.origen == "novedad"}
    sel = seleccionar(X, claves, y, y_acc, materia["inestables"], cfg_sel, semilla, prioritarias=novedad)
    if solo_seleccion:
        return {"seleccion": sel}
    usadas = sel["usadas"]
    j = [claves.index(k) for k in usadas]
    Xs = X[:, j]
    hay_resultado = y is not None and len(set(y.tolist())) > 1
    Z, esp = espacio(Xs, [sel["relevancia"][k] for k in usadas], hay_resultado)
    k, puntajes, fusionadas = elegir_k(Z, y if hay_resultado else None, y_acc, cfg["segmentos"], semilla)
    if fusionadas is not None:
        etiquetas = fusionadas.copy()
        centros = np.array([Z[etiquetas == c].mean(axis=0) if (etiquetas == c).any() else np.zeros(Z.shape[1])
                            for c in range(int(etiquetas.max()) + 1)])
    else:
        km = ajustar(Z, k, semilla)
        etiquetas, centros = km.labels_.copy(), km.cluster_centers_.copy()
    # Veto de un segmento: sus personas pasan al segmento más cercano.
    for sid in vetos.get("segmentos", []):
        c = int(sid[1:]) - 1
        if 0 <= c < len(centros) and len(set(etiquetas.tolist())) > 2:
            otros = [i for i in range(len(centros)) if i != c and (etiquetas == i).any()]
            for fila in np.where(etiquetas == c)[0]:
                etiquetas[fila] = min(otros, key=lambda o: ((Z[fila] - centros[o]) ** 2).sum())
    presentes = sorted(set(etiquetas.tolist()))
    remap = {old: new for new, old in enumerate(presentes)}
    etiquetas = np.array([remap[e] for e in etiquetas])
    centros = np.array([Z[etiquetas == c].mean(axis=0) for c in range(len(presentes))])
    k = len(presentes)

    descripciones = {kk: describir_rasgo(kk, variables) for kk in usadas}
    segmentos = describir(Xs, usadas, descripciones, etiquetas, y if hay_resultado else None, y_acc)
    uso = nombrar(segmentos, ficha.tipo_resultado, llm, cfg["modelo_llm"]) if llm else nombrar(segmentos, ficha.tipo_resultado)
    nivel = cfg["niveles_riesgo"][riesgo]
    base = float(y.mean()) if hay_resultado else None
    acciones_por_segmento(segmentos, base, nivel, ficha.tipo_resultado, bool(ficha.accion))
    tau = escala(Z, centros, etiquetas)
    asignacion = umbral_asignacion(Z, k, etiquetas, centros, nivel["precision_asignacion"], semilla,
                                   objetivo_asesor=min(0.98, nivel["precision_asignacion"] + 0.05))
    asesor = asignacion.pop("asesor", None)
    propension = modelo_propension(Xs, y, base, nivel["lift_asesor"], semilla) if hay_resultado else None
    for s, centro in zip(segmentos, centros):
        s["centro"] = centro.round(5).tolist()
        s["pistas"] = sorted({p for r in s["rasgos"] if r["fuente"] == "jev"
                              for p in (variables[r["clave"].split("=", 1)[0]].pistas or [])}) or ["__sin_pistas__"]
    p = probabilidades(Z, centros, tau)
    conf = p.max(axis=1)
    t_asig = (asignacion["elegido"] or {}).get("umbral", 0.5)
    ids_g = [materia["muestra"]["ids"][i] for i in _genuinas(materia, cfg)]
    return {
        "dataset": ficha.dataset, "riesgo": riesgo, "vetos": vetos,
        "seleccion": sel, "espacio": {"claves": usadas, **esp},
        "segmentos": segmentos, "k_puntajes": puntajes,
        "umbrales": {"asignacion": asignacion, "asesor": asesor, "tau": tau, "propension": propension,
                     "genuino_min": cfg["reglas_fijas"]["genuino_min"], "nivel": nivel},
        "linea_base": {"proporciones": {s["id"]: s["proporcion"] for s in segmentos},
                       "baja_confianza": round(float((conf < t_asig).mean()), 3), "n": int(len(Z))},
        "asignaciones_muestra": dict(zip(ids_g, [f"s{e + 1}" for e in etiquetas.tolist()])),
        "_usos_llm": [{**uso, "para": "nombres de segmentos"}] if uso else [],
    }


def recalcular(version: dict, cfg: dict | None = None, riesgo: str | None = None, vetos: dict | None = None) -> dict:
    """Nuevo modelo desde lo ya medido (vetos o riesgo). Cero llamadas a JEV; nombres con plantilla."""
    cfg = cfg or cargar_config()
    nuevo = construir_modelo(version, cfg, riesgo or version["riesgo"], vetos if vetos is not None else version.get("vetos"),
                             semilla=version.get("semilla", 30))
    nuevo.pop("_usos_llm", None)
    resultado = {**version, **nuevo}
    resultado["padre"] = version.get("version")
    resultado["fecha"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    resultado["costo"] = {**version["costo"], "jev_tokens_recalculo": 0}
    return resultado


def estimar(muestra: list[dict], variables: list[Variable], campos: list[str], cfg: dict) -> dict:
    """Tokens y USD de medir la muestra (más la repetición de consistencia) con JEV real."""
    preguntas = [v.pregunta() for v in variables] + [pregunta_genuina(campos)]
    con_texto = [f for f in muestra if estado_fila(f, campos)]
    if not con_texto:
        return {"tokens": 0, "usd": 0.0}
    prueba = con_texto[:25]
    por_fila = sum(estimar_tokens(estado_fila(f, campos), preguntas) for f in prueba) / len(prueba)
    tokens = int(por_fila * (len(con_texto) + min(cfg["repeticiones_consistencia"], len(con_texto))))
    return {"tokens": tokens, "usd": round(usd_jev(tokens), 5)}


def estimar_live(ficha: Ficha, muestra: list[dict], y, y_acc, tokens_jev: int, cfg: dict) -> dict:
    """Lo que costaría este mismo descubrimiento con JEV real y el LLM proponiendo las variables."""
    prompt = prompt_propuesta(ficha, muestra, y, y_acc, cfg["max_candidatas"])
    entrada = len(prompt) // 4 + 600
    rondas = cfg["rondas"] if ficha.resultado else 1
    llm_usd = rondas * costo_llm(cfg["modelo_llm"], entrada, 3500) + costo_llm(cfg["modelo_llm"], 1500, 900)
    return {"jev_usd": round(usd_jev(tokens_jev), 4), "llm_usd": round(llm_usd, 4), "total_usd": round(usd_jev(tokens_jev) + llm_usd, 4),
            "modelo_llm": cfg["modelo_llm"], "con_haiku_usd": round(usd_jev(tokens_jev) + rondas * costo_llm("claude-haiku-5-5", entrada, 3500)
                                                                   + costo_llm("claude-haiku-5-5", 1500, 900), 4)}


def _retro(variables, provisional, muestra, residuos, campos, y) -> dict:
    sel = provisional["seleccion"]
    actuales = [{"id": v.id, "descripcion": v.descripcion, "estado": "usada" if any(k.split("=", 1)[0] == v.id for k in sel["usadas"]) else v.estado,
                 "relevancia": round(max([r for k, r in sel["relevancia"].items() if k.split("=", 1)[0] == v.id], default=0), 2)}
                for v in variables]
    peores = sorted(range(len(muestra)), key=lambda i: -abs(residuos[i]))[:15]
    errores = [{**{c: muestra[i].get(c, "")[:200] for c in campos if muestra[i].get(c)}, "resultado_real": "sí" if y[i] else "no",
                "el_modelo_esperaba": "no" if y[i] else "sí"} for i in peores]
    return {"variables": actuales, "errores": errores}
