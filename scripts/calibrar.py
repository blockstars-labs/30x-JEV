"""Calibra los umbrales de la política con los perfiles etiquetados, sin volver a llamar a JEV.

1. Pide a JEV las respuestas de todos los perfiles una sola vez y las guarda en reportes/.
2. Prueba muchas combinaciones de umbrales sobre esas mismas respuestas (solo código, costo cero).
3. Descarta las que pasan a ventas a alguien indebidamente o dejan pasar perfiles no genuinos,
   y entre las demás recomienda la que más automatiza con la precisión pedida.

No modifica config/politica.json: escribe la sugerencia en config/politica_calibrada.json para
que una persona la revise y decida.

Uso:
    python scripts/calibrar.py [modo] [precision_objetivo]     # p. ej. live 0.9
"""

import copy
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.jev import RespuestaChoice, RespuestaJEV, RespuestaScore, crear_cliente  # noqa: E402
from app.motor import juicios_desde_jev  # noqa: E402
from app.politica import cargar_politica  # noqa: E402
from app.preguntas import construir_estado  # noqa: E402
from app.simulacion import medir  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
REPORTES = RAIZ / "reportes"

REJILLA = {
    "perfil_valido_min": [0.5, 0.7, 0.8, 0.9],
    "confianza_choice_min": [0.2, 0.3, 0.45, 0.6, 0.75],
    "listo_ventas_auto": [0.7, 0.8, 0.9],
    "confianza_rol_ventas": [0.5, 0.7, 0.85],
}


def respuesta_a_dict(r: RespuestaJEV) -> dict:
    return {"modelo": r.modelo, "tokens_entrada": r.tokens_entrada, "latencia_ms": r.latencia_ms,
            "choices": {k: vars(v) for k, v in r.choices.items()},
            "scores": {k: {**vars(v), "probabilidades": {str(i): p for i, p in v.probabilidades.items()}}
                       for k, v in r.scores.items()},
            "nouls": r.nouls}


def respuesta_desde_dict(d: dict) -> RespuestaJEV:
    return RespuestaJEV(
        modelo=d["modelo"], tokens_entrada=d["tokens_entrada"], latencia_ms=d["latencia_ms"],
        choices={k: RespuestaChoice(**v) for k, v in d["choices"].items()},
        scores={k: RespuestaScore(v["score"], v["confianza"], {int(i): p for i, p in v["probabilidades"].items()})
                for k, v in d["scores"].items()},
        nouls=d["nouls"])


def obtener_respuestas(perfiles: list[dict], modo: str | None) -> tuple[str, dict[str, RespuestaJEV]]:
    cliente = crear_cliente(modo)
    nombre = "mock" if cliente.__class__.__name__ == "JEVMock" else "live"
    cache = REPORTES / f"respuestas_jev_{nombre}.json"
    if cache.exists():
        datos = json.loads(cache.read_text(encoding="utf-8"))
        if set(datos) == {p["id"] for p in perfiles}:
            print(f"Usando respuestas guardadas: {cache}")
            return nombre, {k: respuesta_desde_dict(v) for k, v in datos.items()}
    respuestas = {p["id"]: cliente.evaluar(construir_estado(p)) for p in perfiles}
    REPORTES.mkdir(exist_ok=True)
    cache.write_text(json.dumps({k: respuesta_a_dict(v) for k, v in respuestas.items()}, ensure_ascii=False),
                     encoding="utf-8")
    return nombre, respuestas


def main(modo: str | None, objetivo: float) -> None:
    perfiles = json.loads((RAIZ / "data" / "perfiles_sinteticos.json").read_text(encoding="utf-8"))
    nombre, respuestas = obtener_respuestas(perfiles, modo)
    base = cargar_politica()
    juicios = {k: juicios_desde_jev(r) for k, r in respuestas.items()}

    resultados = []
    claves = list(REJILLA)
    for valores in itertools.product(*REJILLA.values()):
        politica = copy.deepcopy(base)
        politica["umbrales"].update(dict(zip(claves, valores)))
        resultados.append({"umbrales": dict(zip(claves, valores)), **medir(perfiles, juicios, politica)})

    seguros = [r for r in resultados if r["pases_a_ventas_indebidos"] == 0 and r["invalidos_automaticos"] == 0]
    cumplen = [r for r in seguros if r["precision"] >= objetivo]
    if cumplen:
        recomendado = max(cumplen, key=lambda r: (r["automatizacion"], r["precision"]))
        criterio = f"máxima automatización con precisión ≥ {objetivo:.0%} y cero errores de seguridad"
    elif seguros:
        recomendado = max(seguros, key=lambda r: (r["precision"], r["automatizacion"]))
        criterio = f"ninguna llega a {objetivo:.0%} de precisión: se recomienda la más precisa sin errores de seguridad"
    else:
        recomendado, criterio = None, "ninguna combinación evita todos los errores de seguridad"

    # Frontera: la mejor precisión posible para cada nivel de automatización (solo combinaciones seguras).
    frontera, mejor = [], -1.0
    for r in sorted(seguros, key=lambda r: -r["automatizacion"]):
        if r["precision"] > mejor:
            frontera.append(r)
            mejor = r["precision"]

    REPORTES.mkdir(exist_ok=True)
    salida = {"modelo": nombre, "objetivo_precision": objetivo, "criterio": criterio, "recomendado": recomendado,
              "frontera": frontera, "combinaciones_probadas": len(resultados), "combinaciones_seguras": len(seguros)}
    (REPORTES / f"calibracion_{nombre}.json").write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    if recomendado:
        sugerida = copy.deepcopy(base)
        sugerida["umbrales"].update(recomendado["umbrales"])
        sugerida["_nota"] = (f"Sugerencia de scripts/calibrar.py con JEV {nombre} ({criterio}). "
                             "Revisar antes de copiarla a politica.json.")
        (RAIZ / "config" / "politica_calibrada.json").write_text(json.dumps(sugerida, ensure_ascii=False, indent=2),
                                                                 encoding="utf-8")

    print(f"\nJEV {nombre} · {len(perfiles)} perfiles · {len(resultados)} combinaciones de umbrales "
          f"({len(seguros)} sin errores de seguridad)")
    if nombre == "mock":
        print("AVISO: JEV simulado. Sirve para probar el método, no para elegir umbrales reales.")
    print("\nFrontera automatización ↔ precisión (combinaciones seguras):")
    print(f"  {'automatiza':>10} {'precisión':>10}  umbrales")
    for r in frontera:
        print(f"  {r['automatizacion']:>10.1%} {r['precision']:>10.1%}  {r['umbrales']}")
    print(f"\nRecomendado ({criterio}):")
    print(f"  {recomendado}" if recomendado else "  ninguno")
    if recomendado:
        print("Sugerencia escrita en config/politica_calibrada.json (no se aplicó a politica.json).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None, float(sys.argv[2]) if len(sys.argv) > 2 else 0.9)
