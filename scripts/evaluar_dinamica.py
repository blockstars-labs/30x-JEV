"""Evalúa la reclasificación dinámica sobre las líneas de tiempo sintéticas.

Para cada persona: se inscribe, luego ocurren eventos (asiste, responde un correo, contesta una
encuesta, cambia de cargo). Después de cada evento se compara la decisión del sistema con la que
corresponde según la verdad conocida, y se mide si detecta los cambios de segmento reales.

Uso:
    python scripts/evaluar_dinamica.py            # usa JEV_MODO de .env (mock por defecto)
    python scripts/evaluar_dinamica.py live
"""

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.jev import crear_cliente  # noqa: E402
from app.llm import crear_llm  # noqa: E402
from app.motor import juicios_desde_etiquetas  # noqa: E402
from app.personas import aplicar_evento, compromiso, crear_persona, reevaluar  # noqa: E402
from app.politica import cargar_politica, decidir  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
REPORTES = RAIZ / "reportes"


def pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def main(modo: str | None) -> None:
    perfiles = {p["id"]: p for p in json.loads((RAIZ / "data" / "perfiles_sinteticos.json").read_text(encoding="utf-8"))}
    lineas = json.loads((RAIZ / "data" / "eventos_sinteticos.json").read_text(encoding="utf-8"))
    cliente = crear_cliente(modo)
    llm = crear_llm()
    politica = cargar_politica()

    pasos, historiales = [], []
    for linea in lineas:
        perfil = perfiles[linea["perfil_id"]]
        hoy = date.fromisoformat(linea["fecha_registro"])
        persona = crear_persona(perfil, hoy)
        secuencia = [({"tipo": "inscripcion", "fecha": hoy}, perfil["etiquetas"])]
        secuencia += [({**e, "fecha": date.fromisoformat(e["fecha"])}, e["etiquetas_despues"]) for e in linea["eventos"]]

        esperado_previo = None
        for evento, etiquetas in secuencia:
            if evento["tipo"] != "inscripcion":
                aplicar_evento(persona, evento)
            r = reevaluar(persona, evento["fecha"], cliente, evento, politica, llm)
            nivel, _ = compromiso(persona, evento["fecha"], politica)
            esperado = decidir(juicios_desde_etiquetas(etiquetas), perfil["temas"], politica, nivel)
            seg_esperado = (esperado.programa, esperado.accion_propuesta)
            d = persona.decision
            pasos.append({
                "evento": evento["tipo"],
                "ruta": d.ruta,
                "correcto": (d.programa, d.accion) == (esperado.programa, esperado.accion),
                "venta_indebida": d.ruta == "automatico" and d.accion == "pasar_a_ventas" and esperado.accion != "pasar_a_ventas",
                "cambio_real": esperado_previo is not None and seg_esperado != esperado_previo,
                "cambio_detectado": r["cambio_segmento"],
                "llamo_jev": r["llamo_jev"],
                "costo_usd": r["costo_usd"] + r["costo_llm_usd"],
                "revisiones_llm": len(r["revisiones_llm"]),
            })
            esperado_previo = seg_esperado
        historiales.append({"perfil_id": persona.id, "historial": persona.historial})

    modelo = getattr(cliente, "__class__").__name__.replace("JEV", "").lower()
    eventos = [p for p in pasos if p["evento"] != "inscripcion"]
    auto = [p for p in pasos if p["ruta"] in ("automatico", "llm")]
    reales = [p for p in eventos if p["cambio_real"]]
    detectados = [p for p in eventos if p["cambio_detectado"]]
    acierto_cambio = [p for p in detectados if p["cambio_real"]]
    costo = sum(p["costo_usd"] for p in pasos)

    metricas = {
        "modelo": modelo,
        "personas": len(lineas),
        "eventos": len(eventos),
        "eventos_por_tipo": dict(Counter(p["evento"] for p in eventos)),
        "tasa_automatizacion": len(auto) / len(pasos),
        "precision_al_actuar_solo": sum(p["correcto"] for p in auto) / len(auto) if auto else None,
        "pases_a_ventas_indebidos": sum(p["venta_indebida"] for p in pasos),
        "cambios_de_segmento_reales": len(reales),
        "cambios_detectados": len(detectados),
        "recall_cambios": len(acierto_cambio) / len(reales) if reales else None,
        "precision_cambios": len(acierto_cambio) / len(detectados) if detectados else None,
        "eventos_sin_llamar_a_jev": sum(not p["llamo_jev"] for p in eventos),
        "rutas": dict(Counter(p["ruta"] for p in pasos)),
        "revisiones_llm": sum(p["revisiones_llm"] for p in pasos),
        "costo_usd_total": costo,
    }

    REPORTES.mkdir(exist_ok=True)
    (REPORTES / f"dinamica_{modelo}.json").write_text(json.dumps(metricas, ensure_ascii=False, indent=1), encoding="utf-8")
    (REPORTES / f"historiales_{modelo}.json").write_text(json.dumps(historiales, ensure_ascii=False, indent=1, default=str),
                                                         encoding="utf-8")

    print(f"\nModelo: {modelo}  ·  {metricas['personas']} personas · {metricas['eventos']} eventos")
    if modelo == "mock":
        print("AVISO: JEV simulado. Estas cifras prueban el flujo, no miden a JEV.")
    print(f"Eventos por tipo: {metricas['eventos_por_tipo']}")
    print(f"\nAutomatización:            {pct(metricas['tasa_automatizacion'])}  rutas: {metricas['rutas']}")
    if auto:
        print(f"Precisión al actuar solo:  {pct(metricas['precision_al_actuar_solo'])}")
    print(f"Pases a ventas indebidos:  {metricas['pases_a_ventas_indebidos']}")
    print(f"Cambios de segmento reales: {len(reales)} · detectados: {len(detectados)}")
    if reales and detectados:
        print(f"  recall {pct(metricas['recall_cambios'])} · precisión {pct(metricas['precision_cambios'])}")
    print(f"Eventos resueltos sin llamar a JEV: {metricas['eventos_sin_llamar_a_jev']} de {len(eventos)}")
    print(f"Costo total: USD {costo:.5f}")

    ejemplos = [(h["perfil_id"], e) for h in historiales for e in h["historial"] if e["cambio_segmento"]][:3]
    if ejemplos:
        print("\nEjemplos de cambios de segmento:")
    for pid, e in ejemplos:
        print(f"  {pid} · {e['fecha']} · {e['evento']}")
        print(f"     {'; '.join(e['cambios'])}")
    print(f"\nReporte: {REPORTES / f'dinamica_{modelo}.json'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
