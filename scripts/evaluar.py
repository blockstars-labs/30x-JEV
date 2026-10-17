"""Corre todos los perfiles sintéticos por JEV + política y mide contra la verdad conocida.

Mide lo que pide el playbook: precisión por pregunta (vs. la clasificación actual de 30X),
automatización, errores al actuar solo, calibración, costo y latencia.

Uso:
    python scripts/evaluar.py            # usa JEV_MODO de .env (mock por defecto)
    python scripts/evaluar.py live       # fuerza JEV real
"""

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.jev import crear_cliente  # noqa: E402
from app.motor import juicios_desde_etiquetas, procesar  # noqa: E402
from app.llm import costo_llm, crear_llm  # noqa: E402
from app.politica import cargar_politica, decidir  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PERFILES = RAIZ / "data" / "perfiles_sinteticos.json"
REPORTES = RAIZ / "reportes"

# Clasificación actual de 30X medida contra 220 perfiles revisados a mano (hoja "Notas" de la demo).
LINEA_BASE_30X = {"rol": 0.81, "dolor": 0.55, "objetivo": 0.55}
# Supuesto para comparar: hacer la misma clasificación con un LLM leería el mismo texto que JEV
# y generaría ~300 tokens de salida por perfil.
SALIDA_LLM_SUPUESTA = 300


def pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def main(modo: str | None) -> None:
    perfiles = json.loads(PERFILES.read_text(encoding="utf-8"))
    cliente = crear_cliente(modo)
    llm = crear_llm()
    politica = cargar_politica()
    filas = []
    for p in perfiles:
        reg = procesar(p, cliente, politica, registrar=False, llm=llm)
        esperado = decidir(juicios_desde_etiquetas(p["etiquetas"]), p["temas"], politica)
        filas.append((p, reg, esperado))

    modelo = filas[0][1]["modelo"]
    nombre = "mock" if modelo == "mock" else "live"  # nombre de archivo estable, igual que evaluar_dinamica
    n = len(filas)
    aciertos = Counter()
    calibracion = [[0, 0] for _ in range(5)]  # buckets de confianza 0-0.2, ..., 0.8-1
    for p, reg, _ in filas:
        e, r = p["etiquetas"], reg["respuestas_jev"]
        for campo in ("rol", "dolor", "objetivo"):
            c = r["choices"][campo]
            ok = c["valor"] == e[campo]
            aciertos[campo] += ok
            b = calibracion[min(int(c["confianza"] * 5), 4)]
            b[0] += 1
            b[1] += ok
        probs = r["scores"]["intencion"]["probabilidades"]
        aciertos["intencion"] += max(probs, key=probs.get) == e["intencion"]
        aciertos["perfil_valido"] += (r["nouls"]["perfil_valido"] >= 0.5) == e["perfil_valido"]

    auto = [(p, reg, esp) for p, reg, esp in filas if reg["decision"]["ruta"] in ("automatico", "llm")]
    por_llm = [x for x in auto if x[1]["decision"]["ruta"] == "llm"]
    auto_ok = [x for x in auto if (x[1]["decision"]["accion"], x[1]["decision"]["programa"])
               == (x[2].accion, x[2].programa)]
    ventas_indebidas = [x for x in auto if x[1]["decision"]["accion"] == "pasar_a_ventas"
                        and x[2].accion != "pasar_a_ventas"]
    invalidos_auto = [x for x in auto if not x[0]["etiquetas"]["perfil_valido"]]
    latencias = sorted(reg["latencia_ms"] for _, reg, _ in filas)
    tokens = sum(reg["tokens_entrada"] for _, reg, _ in filas)
    costo = sum(reg["costo_usd"] for _, reg, _ in filas)
    costo_llm_total = sum(reg["costo_llm_usd"] for _, reg, _ in filas)
    revisiones = sum(len(reg["revisiones_llm"]) for _, reg, _ in filas)
    costo_todo_llm = sum(costo_llm(reg["tokens_entrada"], SALIDA_LLM_SUPUESTA) for _, reg, _ in filas)

    metricas = {
        "modelo": modelo,
        "perfiles": n,
        "precision_por_pregunta": {k: aciertos[k] / n for k in ("rol", "dolor", "objetivo", "intencion", "perfil_valido")},
        "linea_base_30x": LINEA_BASE_30X,
        "tasa_automatizacion": len(auto) / n,
        "rutas": dict(Counter(reg["decision"]["ruta"] for _, reg, _ in filas)),
        "precision_al_actuar_solo": len(auto_ok) / len(auto) if auto else None,
        "precision_resueltos_por_llm": (sum(x in auto_ok for x in por_llm) / len(por_llm)) if por_llm else None,
        "revisiones_llm": revisiones,
        "errores_automaticos": len(auto) - len(auto_ok),
        "pases_a_ventas_indebidos": len(ventas_indebidas),
        "perfiles_invalidos_procesados_solos": len(invalidos_auto),
        "acciones": dict(Counter(reg["decision"]["accion"] for _, reg, _ in filas)),
        "programas": dict(Counter(reg["decision"]["programa"] for _, reg, _ in filas)),
        "calibracion_choice": [{"confianza": f"{i / 5:.1f}-{(i + 1) / 5:.1f}", "n": b[0],
                                "precision": b[1] / b[0] if b[0] else None} for i, b in enumerate(calibracion)],
        "latencia_ms": {"p50": statistics.median(latencias), "p95": latencias[int(0.95 * (n - 1))]},
        "tokens_entrada_total": tokens,
        "costo_usd_total": costo,
        "costo_usd_por_1000_decisiones": 1000 * costo / n,
        "costo_llm_usd_total": costo_llm_total,
        "costo_usd_si_todo_fuera_llm": costo_todo_llm,
    }

    REPORTES.mkdir(exist_ok=True)
    (REPORTES / f"metricas_{nombre}.json").write_text(json.dumps(metricas, ensure_ascii=False, indent=1), encoding="utf-8")
    with (REPORTES / f"decisiones_{nombre}.jsonl").open("w", encoding="utf-8") as f:
        for p, reg, esp in filas:
            f.write(json.dumps({**reg, "esperado": {"accion": esp.accion, "programa": esp.programa},
                                "etiquetas": p["etiquetas"]}, ensure_ascii=False) + "\n")

    print(f"\nModelo: {modelo}  ·  {n} perfiles")
    if modelo == "mock":
        print("AVISO: JEV simulado. Estas cifras prueban el flujo, no miden a JEV.")
    print("\nPrecisión por pregunta (línea base 30X entre paréntesis)")
    for k, v in metricas["precision_por_pregunta"].items():
        base = f"  ({pct(LINEA_BASE_30X[k])})" if k in LINEA_BASE_30X else ""
        print(f"  {k:<14}{pct(v)}{base}")
    print(f"\nAutomatización:            {pct(metricas['tasa_automatizacion'])}  rutas: {metricas['rutas']}")
    if auto:
        print(f"Precisión al actuar solo:  {pct(metricas['precision_al_actuar_solo'])}")
    if por_llm:
        print(f"Precisión de los resueltos por el LLM: {pct(metricas['precision_resueltos_por_llm'])} ({len(por_llm)} casos)")
    print(f"Errores automáticos:       {metricas['errores_automaticos']}")
    print(f"Pases a ventas indebidos:  {metricas['pases_a_ventas_indebidos']}")
    print(f"Inválidos procesados solos: {metricas['perfiles_invalidos_procesados_solos']}")
    print(f"Acciones: {metricas['acciones']}")
    print(f"Latencia p50/p95: {metricas['latencia_ms']['p50']:.0f} / {metricas['latencia_ms']['p95']:.0f} ms")
    print(f"Costo JEV: USD {costo:.5f} total · USD {metricas['costo_usd_por_1000_decisiones']:.4f} por 1.000 decisiones")
    print(f"Costo LLM ({revisiones} revisiones): USD {costo_llm_total:.4f}")
    print(f"Si todo se clasificara con el LLM (supuesto: misma entrada, {SALIDA_LLM_SUPUESTA} tokens de salida): "
          f"USD {costo_todo_llm:.4f}")
    print(f"\nReporte: {REPORTES / f'metricas_{nombre}.json'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
