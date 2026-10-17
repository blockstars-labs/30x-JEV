"""Clusterización dinámica: cada persona tiene un estado que se recalcula cuando su situación cambia.

Separa lo observado de lo inferido, como recomienda TypeSafe:
- Observado (hechos, en código): inscripción, mensajes, cambios de cargo, asistencia a eventos, fechas.
- Inferido (JEV): rol, dolor, objetivo, intención, validez. Cada inferencia guarda su fecha y caduca.

Un evento con texto nuevo (correo, encuesta, cargo) vuelve a llamar a JEV. Un evento sin texto
(asistió a un evento) solo cambia el compromiso observado: la decisión se recalcula en código con
los juicios anteriores, sin costo de inferencia, salvo que esos juicios ya estén vencidos.
"""

from dataclasses import dataclass, field
from datetime import date

from app.catalogo import INTENCION, PROGRAMAS
from app.motor import juicios_desde_jev, resolver_con_llm
from app.politica import ACCIONES, Decision, Juicios, cargar_politica, decidir, explicar, etiqueta
from app.preguntas import construir_estado

EVENTOS_CON_TEXTO = {"respondio_correo", "encuesta_post_evento", "cambio_cargo"}


@dataclass
class Persona:
    id: str
    perfil: dict                         # inscripción original (canal, entrada, temas)
    fecha_registro: date
    cargo_actual: str | None = None
    mensajes: list[dict] = field(default_factory=list)       # {fecha, origen, texto}
    asistencias: list[dict] = field(default_factory=list)    # {fecha, evento}
    juicios: Juicios | None = None
    fecha_inferencia: date | None = None
    decision: Decision | None = None
    historial: list[dict] = field(default_factory=list)

    @property
    def segmento(self) -> tuple[str, str] | None:
        """Segmento = programa sugerido + acción. Un cambio solo de banda se registra pero no cuenta como cambio."""
        if not self.decision:
            return None
        return self.decision.programa, self.decision.accion_propuesta


def compromiso(p: Persona, hoy: date, politica: dict) -> tuple[str, str]:
    """Compromiso observado, calculado con fechas reales. Devuelve el nivel y un resumen legible."""
    cfg = politica["dinamica"]
    recientes = [a for a in p.asistencias if (hoy - a["fecha"]).days <= cfg["ventana_eventos_dias"]]
    interacciones = [p.fecha_registro] + [m["fecha"] for m in p.mensajes] + [a["fecha"] for a in p.asistencias]
    dias = (hoy - max(interacciones)).days
    resumen = (f"{len(recientes)} evento(s) asistido(s) en {cfg['ventana_eventos_dias']} días, "
               f"última interacción hace {dias} día(s)")
    if len(recientes) >= cfg["compromiso_alto"]["eventos_min"] and dias <= cfg["compromiso_alto"]["ultima_interaccion_max_dias"]:
        return "alto", resumen
    if dias <= cfg["compromiso_medio"]["ultima_interaccion_max_dias"]:
        return "medio", resumen
    return "bajo", resumen


def crear_persona(perfil: dict, fecha_registro: date) -> Persona:
    return Persona(id=perfil["id"], perfil=perfil, fecha_registro=fecha_registro)


def aplicar_evento(p: Persona, evento: dict) -> None:
    """Registra el hecho observado. No infiere nada."""
    tipo, fecha = evento["tipo"], evento["fecha"]
    if tipo == "asistio_evento":
        p.asistencias.append({"fecha": fecha, "evento": evento["evento"]})
    elif tipo == "cambio_cargo":
        p.cargo_actual = evento["cargo"]
    elif tipo in ("respondio_correo", "encuesta_post_evento"):
        origen = "correo" if tipo == "respondio_correo" else "encuesta_post_evento"
        p.mensajes.append({"fecha": fecha, "origen": origen, "texto": evento["texto"]})
    else:
        raise ValueError(f"Tipo de evento desconocido: {tipo}")


def describir_evento(evento: dict) -> str:
    tipo = evento["tipo"]
    if tipo == "asistio_evento":
        return f"Asistió a «{evento['evento']}»"
    if tipo == "cambio_cargo":
        return f"Actualizó su cargo a «{evento['cargo']}»"
    if tipo == "respondio_correo":
        return f"Respondió un correo: «{evento['texto']}»"
    if tipo == "encuesta_post_evento":
        return f"Respondió la encuesta post-evento: «{evento['texto']}»"
    if tipo == "inscripcion":
        return "Se inscribió"
    return tipo


def reevaluar(p: Persona, hoy: date, cliente, motivo: dict, politica: dict | None = None, llm=None) -> dict:
    """Recalcula el segmento de la persona y registra si cambió y por qué."""
    politica = politica or cargar_politica()
    vigencia = politica["dinamica"]["vigencia_inferencia_dias"]
    vencida = p.fecha_inferencia is None or (hoy - p.fecha_inferencia).days > vigencia
    llamo_jev = vencida or motivo["tipo"] in EVENTOS_CON_TEXTO or motivo["tipo"] == "inscripcion"

    tokens, costo, latencia = 0, 0.0, 0.0
    juicios_previos = p.juicios
    if llamo_jev:
        estado = construir_estado(p.perfil, p.cargo_actual, p.mensajes)
        r = cliente.evaluar(estado)
        p.juicios, p.fecha_inferencia = juicios_desde_jev(r), hoy
        tokens, costo, latencia = r.tokens_entrada, r.costo_usd, r.latencia_ms

    nivel, resumen = compromiso(p, hoy, politica)
    anterior = p.decision
    p.decision = decidir(p.juicios, p.perfil["temas"], politica, nivel)
    # Si el LLM resuelve una duda, el juicio resuelto se guarda: el siguiente evento no la vuelve a revisar.
    estado = construir_estado(p.perfil, p.cargo_actual, p.mensajes)
    p.juicios, p.decision, revisiones = resolver_con_llm(estado, p.juicios, p.decision, p.perfil["temas"],
                                                         politica, llm, nivel)

    cambios = _diferencias(juicios_previos, p.juicios, anterior, p.decision)
    entrada = {
        "fecha": hoy.isoformat(),
        "evento": describir_evento(motivo),
        "tipo_evento": motivo["tipo"],
        "llamo_jev": llamo_jev,
        "inferencia_vencida": vencida and motivo["tipo"] != "inscripcion",
        "compromiso": nivel,
        "actividad": resumen,
        "segmento": {"programa": p.decision.programa, "banda": p.decision.banda,
                     "accion": p.decision.accion, "accion_propuesta": p.decision.accion_propuesta,
                     "ruta": p.decision.ruta},
        "cambio_segmento": anterior is not None and p.segmento != (anterior.programa, anterior.accion_propuesta),
        "cambios": cambios,
        "explicacion": explicar(p.juicios, p.decision),
        "revisiones_llm": [vars(r) for r in revisiones],
        "tokens_entrada": tokens,
        "costo_usd": costo,
        "costo_llm_usd": sum(r.costo_usd for r in revisiones),
        "latencia_ms": round(latencia, 1),
    }
    p.historial.append(entrada)
    return entrada


def _diferencias(j0: Juicios | None, j1: Juicios, d0: Decision | None, d1: Decision) -> list[str]:
    """Lista legible de qué cambió entre la evaluación anterior y la nueva."""
    if d0 is None or j0 is None:
        return []
    cambios = []
    for campo in ("rol", "dolor", "objetivo"):
        a, b = getattr(j0, campo).valor, getattr(j1, campo).valor
        if a != b:
            cambios.append(f"{campo}: {etiqueta(campo, a)} → {etiqueta(campo, b)}")
    nivel0 = max(j0.intencion_probabilidades, key=j0.intencion_probabilidades.get)
    nivel1 = max(j1.intencion_probabilidades, key=j1.intencion_probabilidades.get)
    if nivel0 != nivel1:
        cambios.append(f"intención: {INTENCION[nivel0].etiqueta} → {INTENCION[nivel1].etiqueta}")
    if d0.compromiso != d1.compromiso:
        cambios.append(f"compromiso: {d0.compromiso} → {d1.compromiso}")
    if d0.banda != d1.banda:
        cambios.append(f"afinidad: {d0.banda} → {d1.banda}")
    if d0.programa != d1.programa:
        cambios.append(f"programa: {PROGRAMAS[d0.programa]} → {PROGRAMAS[d1.programa]}")
    if d0.accion_propuesta != d1.accion_propuesta:
        cambios.append(f"acción: {ACCIONES[d0.accion_propuesta]} → {ACCIONES[d1.accion_propuesta]}")
    return cambios
