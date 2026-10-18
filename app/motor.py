"""Flujo completo para una inscripción: estado → JEV → política → (LLM si hace falta) → decisión registrada."""

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.catalogo import DOLORES, OBJETIVOS, PROGRAMAS, ROLES, por_id
from app.guardrail import revisar_mensaje
from app.jev import RespuestaJEV
from app.politica import ACCIONES, Decision, Juicio, Juicios, cargar_politica, decidir, explicar
from app.preguntas import PREGUNTAS, construir_estado

REGISTRO = Path(__file__).resolve().parent.parent / "data" / "decisiones.jsonl"
OPCIONES = {"rol": por_id(ROLES), "dolor": por_id(DOLORES), "objetivo": por_id(OBJETIVOS)}
INSTRUCCIONES = {p.id: p.instrucciones for p in PREGUNTAS}
CANDIDATOS_LLM = 3  # el LLM elige entre las opciones más probables según JEV


def juicios_desde_jev(r: RespuestaJEV) -> Juicios:
    def choice(id_: str) -> Juicio:
        c = r.choices[id_]
        return Juicio(c.valor, c.confianza, c.probabilidades)

    intencion = r.scores["intencion"]
    dolor = choice("dolor")
    p = r.nouls.get("dolor_declarado")
    if p is not None:
        # El código combina las dos preguntas: si la persona no declara un problema, el dolor es "ninguno".
        # La confianza de un Noul se expresa como |2p - 1| (documentación de TypeSafe).
        certeza = abs(2 * p - 1)
        if p < 0.5:
            dolor = Juicio("ninguno", certeza, {"ninguno": 1 - p, dolor.valor if dolor.valor != "ninguno" else "otro": p})
        elif dolor.valor != "ninguno":
            dolor = Juicio(dolor.valor, min(dolor.confianza, certeza), dolor.probabilidades)
    return Juicios(rol=choice("rol"), dolor=dolor, objetivo=choice("objetivo"),
                   intencion_esperada=intencion.score, intencion_probabilidades=intencion.probabilidades,
                   perfil_valido=r.nouls["perfil_valido"])


def juicios_desde_etiquetas(e: dict) -> Juicios:
    """La verdad conocida de un perfil sintético, con certeza total, para calcular la decisión esperada."""
    return Juicios(rol=Juicio(e["rol"]), dolor=Juicio(e["dolor"]), objetivo=Juicio(e["objetivo"]),
                   intencion_esperada=float(e["intencion"]),
                   intencion_probabilidades={i: float(i == e["intencion"]) for i in range(4)},
                   perfil_valido=1.0 if e["perfil_valido"] else 0.0)


def resolver_con_llm(estado: dict, juicios: Juicios, decision: Decision, temas: list[str], politica: dict,
                     llm, compromiso: str = "medio") -> tuple[Juicios, Decision, list]:
    """System Two: si JEV dudó en un campo y esa duda cambia la decisión, el LLM revisa ese campo.

    Límites: solo dudas de clasificación (nunca perfiles no genuinos), y si la decisión resultante
    es pasar a ventas, igual la confirma una persona.
    """
    if llm is None or decision.ruta != "revision_humana" or not decision.dudas:
        return juicios, decision, []
    revisiones, nuevos = [], juicios
    for campo in decision.dudas:
        j: Juicio = getattr(juicios, campo)
        top = sorted(j.probabilidades, key=j.probabilidades.get, reverse=True)[:CANDIDATOS_LLM]
        rev = llm.revisar(estado, campo, INSTRUCCIONES[campo], [OPCIONES[campo][i] for i in top], j.probabilidades)
        revisiones.append(rev)
        if rev.eleccion == "no_seguro":
            razon = f"El LLM revisó la duda en {campo} y tampoco pudo decidir: {rev.justificacion}"
            return juicios, replace(decision, razones=decision.razones + [razon]), revisiones
        nuevos = replace(nuevos, **{campo: Juicio(rev.eleccion, 1.0, {rev.eleccion: 1.0})})

    nueva = decidir(nuevos, temas, politica, compromiso)
    resueltas = [f"Duda en {r.campo} resuelta por el LLM: {r.justificacion}" for r in revisiones]
    if nueva.ruta == "automatico" and nueva.accion == "pasar_a_ventas":
        razon = "El LLM resolvió la duda, pero pasar a ventas tras una duda requiere confirmación humana."
        return nuevos, replace(nueva, accion="revision_humana", ruta="revision_humana",
                               razones=resueltas + [razon]), revisiones
    if nueva.ruta == "automatico":
        return nuevos, replace(nueva, ruta="llm", razones=resueltas), revisiones
    return nuevos, replace(nueva, razones=resueltas + nueva.razones), revisiones


def redactar_mensaje(estado: dict, decision: Decision, explicacion: str, llm, cliente=None, politica: dict | None = None):
    """Mensaje para la acción decidida (solo acciones que se ejecutan sin persona de por medio).

    Si hay cliente de JEV, el mensaje pasa por el guardrail antes de quedar listo para enviarse.
    """
    if llm is None or decision.ruta == "revision_humana" or decision.accion not in ("pasar_a_ventas", "nutrir_programa"):
        return None
    mensaje = llm.redactar(estado, decision.accion, PROGRAMAS[decision.programa], explicacion)
    if cliente is not None and mensaje.texto:
        contexto = {"programa": PROGRAMAS[decision.programa], "accion": ACCIONES[decision.accion],
                    "lo_que_dijo_la_persona": {k: v for k, v in estado.items() if k != "canal"}}
        mensaje.guardrail = revisar_mensaje(mensaje.texto, contexto, cliente, politica or cargar_politica())
    return mensaje


def procesar(perfil: dict, cliente, politica: dict | None = None, registrar: bool = True,
             llm=None, redactar: bool = False) -> dict:
    politica = politica or cargar_politica()
    estado = construir_estado(perfil)
    respuesta = cliente.evaluar(estado)
    juicios = juicios_desde_jev(respuesta)
    juicios_jev = {c: {"valor": getattr(juicios, c).valor, "confianza": getattr(juicios, c).confianza}
                   for c in ("rol", "dolor", "objetivo")}  # lo que concluyó JEV, antes de cualquier revisión del LLM
    decision: Decision = decidir(juicios, perfil["temas"], politica)
    juicios, decision, revisiones = resolver_con_llm(estado, juicios, decision, perfil["temas"], politica, llm)
    explicacion = explicar(juicios, decision)
    mensaje = redactar_mensaje(estado, decision, explicacion, llm, cliente, politica) if redactar else None
    costo_llm = sum(r.costo_usd for r in revisiones) + (mensaje.costo_usd if mensaje else 0.0)
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
        "juicios_jev": juicios_jev,
        "decision": vars(decision),
        "explicacion": explicacion,
        "revisiones_llm": [vars(r) for r in revisiones],
        "mensaje": mensaje.texto if mensaje else None,
        "guardrail": mensaje.guardrail if mensaje else None,
        "tokens_entrada": respuesta.tokens_entrada,
        "costo_usd": respuesta.costo_usd,
        "costo_llm_usd": costo_llm,
        "latencia_ms": round(respuesta.latencia_ms, 1),
    }
    if registrar:
        REGISTRO.parent.mkdir(exist_ok=True)
        with REGISTRO.open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro
