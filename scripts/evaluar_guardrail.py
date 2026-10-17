"""Mide el guardrail sobre mensajes etiquetados a mano (data/mensajes_guardrail.json).

Lo que importa: que ningún mensaje riesgoso quede "aprobado" (fugas) y cuántos mensajes buenos
se frenan sin necesidad (falsas alarmas).

Uso:
    python scripts/evaluar_guardrail.py [modo]
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalogo import PROGRAMAS  # noqa: E402
from app.guardrail import revisar_mensaje  # noqa: E402
from app.jev import crear_cliente  # noqa: E402
from app.politica import cargar_politica  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent


def main(modo: str | None) -> None:
    casos = json.loads((RAIZ / "data" / "mensajes_guardrail.json").read_text(encoding="utf-8"))
    cliente = crear_cliente(modo)
    nombre = "mock" if cliente.__class__.__name__ == "JEVMock" else "live"
    politica = cargar_politica()
    filas, matriz = [], Counter()
    for c in casos:
        r = revisar_mensaje(c["mensaje"], {"programa": PROGRAMAS[c["programa"]], "lo_que_dijo_la_persona": "(sin datos)"},
                            cliente, politica)
        matriz[(c["esperado"], r["estado"])] += 1
        filas.append({**c, "obtenido": r["estado"], "razones": r["razones"]})

    riesgosos = [f for f in filas if f["esperado"] != "aprobado"]
    buenos = [f for f in filas if f["esperado"] == "aprobado"]
    fugas = [f for f in riesgosos if f["obtenido"] == "aprobado"]
    falsas = [f for f in buenos if f["obtenido"] != "aprobado"]
    exactos = sum(f["esperado"] == f["obtenido"] for f in filas)
    metricas = {"modelo": nombre, "mensajes": len(filas), "acierto_exacto": exactos / len(filas),
                "fugas": len(fugas), "riesgosos": len(riesgosos), "falsas_alarmas": len(falsas), "buenos": len(buenos),
                "matriz": {f"{e}->{o}": n for (e, o), n in sorted(matriz.items())}}

    (RAIZ / "reportes").mkdir(exist_ok=True)
    (RAIZ / "reportes" / f"guardrail_{nombre}.json").write_text(
        json.dumps({"metricas": metricas, "casos": filas}, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nGuardrail · JEV {nombre} · {len(filas)} mensajes etiquetados")
    if nombre == "mock":
        print("AVISO: JEV simulado. Prueba el flujo, no mide a JEV.")
    print(f"Fugas (riesgoso aprobado): {len(fugas)} de {len(riesgosos)}")
    print(f"Falsas alarmas (bueno frenado): {len(falsas)} de {len(buenos)}")
    print(f"Acierto exacto (aprobado / revisión / bloqueado): {exactos / len(filas):.0%}")
    for f in fugas + falsas:
        print(f"  {f['id']} esperado {f['esperado']}, obtenido {f['obtenido']}: {f['mensaje'][:70]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
