"""Flujo completo para una inscripción: estado → JEV → política → decisión registrada."""

import json
from datetime import datetime, timezone
from pathlib import Path

from app.jev import RespuestaJEV
from app.politica import Decision, Juicio, Juicios, cargar_politica, decidir, explicar
from app.preguntas import construir_estado

REGISTRO = Path(__file__).resolve().parent.parent / "data" / "decisiones.jsonl"


def juicios_desde_jev(r: RespuestaJEV) -> Juicios:
    def choice(id_: str) -> Juicio:
        c = r.choices[id_]
        return Juicio(c.valor, c.confianza, c.probabilidades)

    intencion = r.scores["intencion"]
    return Juicios(rol=choice("rol"), dolor=choice("dolor"), objetivo=choice("objetivo"),
                   intencion_esperada=intencion.score, intencion_probabilidades=intencion.probabilidades,
                   perfil_valido=r.nouls["perfil_valido"])


def juicios_desde_etiquetas(e: dict) -> Juicios:
    """La verdad conocida de un perfil sintético, con certeza total, para calcular la decisión esperada."""
    return Juicios(rol=Juicio(e["rol"]), dolor=Juicio(e["dolor"]), objetivo=Juicio(e["objetivo"]),
                   intencion_esperada=float(e["intencion"]),
                   intencion_probabilidades={i: float(i == e["intencion"]) for i in range(4)},
                   perfil_valido=1.0 if e["perfil_valido"] else 0.0)


def procesar(perfil: dict, cliente, politica: dict | None = None, registrar: bool = True) -> dict:
    politica = politica or cargar_politica()
    estado = construir_estado(perfil)
    respuesta = cliente.evaluar(estado)
    juicios = juicios_desde_jev(respuesta)
    decision: Decision = decidir(juicios, perfil["temas"], politica)
    registro = {
        "perfil_id": perfil["id"],
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "modelo": respuesta.modelo,
        "estado_enviado": estado,
        "temas": perfil["temas"],
        "respuestas_jev": {
            "choices": {k: vars(v) for k, v in respuesta.choices.items()},
            "scores": {k: vars(v) for k, v in respuesta.scores.items()},
            "nouls": respuesta.nouls,
        },
        "decision": vars(decision),
        "explicacion": explicar(juicios, decision),
        "tokens_entrada": respuesta.tokens_entrada,
        "costo_usd": respuesta.costo_usd,
        "latencia_ms": round(respuesta.latencia_ms, 1),
    }
    if registrar:
        REGISTRO.parent.mkdir(exist_ok=True)
        with REGISTRO.open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro
