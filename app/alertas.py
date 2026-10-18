"""Alertas de riesgo en programas: quién puede abandonar, por qué y qué hacer antes de que pase.

Mismo motor que segmenta inscripciones (app/descubrimiento), con otro resultado:
1. El código calcula de los registros crudos lo que es conteo o fecha: asistencia, faltas seguidas,
   entregas pendientes o tarde, días sin actividad (nunca se le pide a JEV que cuente).
2. JEV lee los mensajes recientes de cada alumno con las variables que el propio sistema propuso.
3. El motor aprende de las cohortes terminadas quién abandonó: perfiles de riesgo (segmentos), un modelo de
   riesgo individual y el umbral desde el cual conviene contactar, todo medido fuera de muestra.
4. Cada alerta dice por qué (los rasgos que más empujan el riesgo de esa persona) y qué hacer, y el mensaje
   sugerido pasa por el guardrail de JEV antes de enviarse: la última decisión antes de enviar.
"""

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from app.descubrimiento.asignar import Segmentador
from app.descubrimiento.datos import leer_dataset, normalizar
from app.descubrimiento.pipeline import cargar_config, descubrir

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "data" / "alumnos"
SEMANA_CORTE = 5   # las señales se miden al cierre de la semana 5 (igual en las cohortes terminadas y en la actual)

SENALES = {
    "asistencia_hasta_hoy": lambda x: f"asistió al {x:.0%} de las sesiones",
    "asistencia_ultimas_2": lambda x: f"asistió a {round(x * 2)} de las últimas 2 sesiones",
    "faltas_seguidas": lambda x: f"lleva {int(x)} sesiones seguidas sin asistir",
    "entregas_pendientes": lambda x: f"tiene {int(x)} entregas pendientes",
    "entregas_tarde": lambda x: f"entregó {int(x)} tareas tarde",
    "dias_sin_actividad": lambda x: f"lleva {int(x)} días sin actividad",
}


def cargar_registros(carpeta: Path = DATOS) -> dict:
    return {t: leer_dataset(carpeta / f"{t}.csv") for t in ("alumnos", "asistencias", "entregas", "actividad")}


def construir_filas(registros: dict) -> list[dict]:
    """Una fila por alumno con señales al corte de la semana 5. Conteos y fechas, en código."""
    asist, entregas, mensajes = defaultdict(list), defaultdict(list), defaultdict(list)
    for a in registros["asistencias"]:
        asist[a["alumno"]].append(a)
    for e in registros["entregas"]:
        entregas[e["alumno"]].append(e)
    for m in registros["actividad"]:
        mensajes[m["alumno"]].append(m)
    filas = []
    for al in registros["alumnos"]:
        inicio = date.fromisoformat(al["fecha_inicio"])
        corte = inicio + timedelta(weeks=SEMANA_CORTE, days=-1)
        sesiones = sorted((a for a in asist[al["alumno"]] if date.fromisoformat(a["fecha"]) <= corte), key=lambda a: int(a["sesion"]))
        vino = [a["asistio"] == "Sí" for a in sesiones]
        seguidas = 0
        for v in reversed(vino):
            if v:
                break
            seguidas += 1
        vencidas = [e for e in entregas[al["alumno"]] if date.fromisoformat(e["fecha_limite"]) <= corte]
        pendientes = sum(1 for e in vencidas if not e["fecha_entrega"] or date.fromisoformat(e["fecha_entrega"]) > corte)
        tarde = sum(1 for e in vencidas if e["fecha_entrega"] and e["fecha_limite"] < e["fecha_entrega"] <= corte.isoformat())
        recientes = sorted((m for m in mensajes[al["alumno"]] if date.fromisoformat(m["fecha"]) <= corte), key=lambda m: m["fecha"])
        ultima = date.fromisoformat(recientes[-1]["fecha"]) if recientes else inicio
        filas.append({
            "alumno": al["alumno"], "programa": al["programa"], "cargo": al["cargo"],
            "asistencia_hasta_hoy": f"{sum(vino) / len(vino):.2f}" if vino else "0",
            "asistencia_ultimas_2": f"{sum(vino[-2:]) / max(1, len(vino[-2:])):.2f}" if vino else "0",
            "faltas_seguidas": str(seguidas), "entregas_pendientes": str(pendientes), "entregas_tarde": str(tarde),
            "dias_sin_actividad": str((corte - ultima).days),
            "mensajes_recientes": " | ".join(m["texto"] for m in recientes[-3:]),
            "estado_final": al["estado_final"],
        })
    return filas


def entrenar(filas: list[dict], cliente, llm=None, cfg: dict | None = None) -> dict:
    """Aprende quién abandona con las cohortes terminadas (las que ya tienen estado final)."""
    historicas = [f for f in filas if f["estado_final"]]
    return descubrir(historicas, "alumnos", cliente, llm, cfg or cargar_config())


def umbrales_alerta(prop: dict, tasa_base: float, cfg: dict) -> dict:
    """Umbrales de riesgo aprendidos fuera de muestra: desde qué riesgo predicho la tasa REAL de abandono entre los
    alertados llega a la meta (alto: tasa_alto; medio: lift_medio veces la base). El equipo no puede llamar a medio
    curso, así que el umbral se fija por precisión, no por cobertura."""
    curva = sorted(prop.get("curva", []), key=lambda c: c["umbral"])
    alto = next((c for c in curva if c["tasa"] >= cfg["tasa_alto"]), None)
    medio = next((c for c in curva if c["tasa"] >= min(0.9, tasa_base * cfg["lift_medio"])), None)
    return {"alto": alto, "medio": medio}


def _nivel(p: float | None, umbrales: dict) -> str | None:
    if p is None:
        return None
    if umbrales["alto"] and p >= umbrales["alto"]["umbral"]:
        return "alto"
    if umbrales["medio"] and p >= umbrales["medio"]["umbral"]:
        return "medio"
    return None


def _razones(seg: Segmentador, x: list[float], fila: dict) -> list[dict]:
    """Los rasgos que más empujan el riesgo de esta persona (contribución en el modelo de riesgo), en palabras.

    Solo se muestran razones accionables y verdaderas: una señal de actividad, o algo que la persona escribió de
    verdad (se cita el mensaje). Que alguien "no hable" de un tema, o su cargo, pueden mover el modelo, pero no le
    dicen al equipo qué hacer: solo se usan si no hay nada más."""
    p = seg.propension
    contribuciones = sorted(((c * (xi - m) / d, k, xi) for k, xi, c, m, d in zip(seg.claves, x, p["coeficientes"], p["media"], p["desv"])),
                            reverse=True)
    mensajes = [t for t in fila.get("mensajes_recientes", "").split(" | ") if t.strip()]
    accionables, otras = [], []
    for aporte, k, xi in contribuciones:
        if aporte <= 0.15:
            break
        base = k.split("=", 1)[0]
        if base in SENALES:
            accionables.append({"texto": SENALES[base](xi), "tipo": "actividad", "peso": round(aporte, 2)})
        elif base in seg.variables and xi >= 0.5 and mensajes:
            pistas = seg.variables[base].pistas or []
            if isinstance(pistas, dict):   # pregunta de opciones: las pistas de la opción marcada
                pistas = pistas.get(k.split("=", 1)[-1], [])
            cita = next((t for t in reversed(mensajes) if any(normalizar(pz) in normalizar(t) for pz in pistas)), mensajes[-1])
            accionables.append({"texto": f"escribió «{cita[:90]}»", "tipo": "mensajes", "peso": round(aporte, 2)})
        elif base not in seg.variables:
            otras.append({"texto": k.replace("=", ": ").replace("_", " "), "tipo": "perfil", "peso": round(aporte, 2)})
    razones = []
    for r in accionables + (otras if not accionables else []):
        if r["texto"] not in [x["texto"] for x in razones]:
            razones.append(r)
    return razones[:3]


ACCIONES = {
    "actividad": ("Llamar esta semana para reengancharlo", "Hola {nombre}, te extrañamos en las últimas sesiones de {programa}. "
                  "¿Te ayudamos a ponerte al día? Te compartimos las grabaciones y podemos agendar 15 minutos con tu mentor."),
    "mensajes": ("Llamada del mentor para entender qué necesita", "Hola {nombre}, leímos tu comentario sobre {programa} y queremos "
                 "ayudarte a sacarle provecho. ¿Agendamos una llamada corta con tu mentor esta semana?"),
    "perfil": ("Mensaje de acompañamiento", "Hola {nombre}, ¿cómo vas con {programa}? Si algo no está funcionando para ti, "
               "cuéntanos y lo ajustamos con tu mentor."),
}


def generar_alertas(version: dict, filas_actuales: list[dict], cliente, cliente_guardrail=None, politica: dict | None = None) -> dict:
    """Alertas de la cohorte en curso: riesgo, razones, siguiente paso y mensaje revisado antes de enviar."""
    seg = Segmentador(version, cliente)
    asignaciones = seg.asignar_lote(filas_actuales, con_encaje=False)
    umbrales = umbrales_alerta(seg.propension or {}, version["ficha"]["tasa_positiva"], cargar_config()["alertas"])
    alertas, tokens, costo_guardrail = [], sum(a["tokens"] for a in asignaciones), 0.0
    for fila, a in zip(filas_actuales, asignaciones):
        nivel = _nivel(a["propension"], umbrales)
        if nivel is None:
            continue
        razones = _razones(seg, a["vector"], fila)
        tipo = razones[0]["tipo"] if razones else "perfil"
        accion, plantilla = ACCIONES[tipo]
        mensaje = plantilla.format(nombre="{nombre}", programa=fila["programa"])
        revision = None
        if cliente_guardrail is not None and politica is not None:
            from app.guardrail import revisar_mensaje
            revision = revisar_mensaje(mensaje, {"programa": fila["programa"], "accion": "acompañar a un alumno del programa"},
                                       cliente_guardrail, politica)
            costo_guardrail += revision.get("costo_usd", 0.0)
        alertas.append({"alumno": fila["alumno"], "programa": fila["programa"], "nivel": nivel, "riesgo": a["propension"],
                        "perfil": a["nombre"], "razones": razones, "accion": accion, "mensaje": mensaje,
                        "guardrail": revision, "senales": {k: fila[k] for k in SENALES}})
    alertas.sort(key=lambda al: (al["nivel"] != "alto", -(al["riesgo"] or 0)))
    return {"alertas": alertas, "total": len(filas_actuales),
            "altas": sum(a["nivel"] == "alto" for a in alertas), "medias": sum(a["nivel"] == "medio" for a in alertas),
            "costo_jev_usd": round(tokens * 0.042 / 1_000_000 + costo_guardrail, 5),
            "modelo": {"auc_fuera_de_muestra": (seg.propension or {}).get("auc_fuera_de_muestra"),
                       "tasa_base": version["ficha"]["tasa_positiva"], "umbrales": umbrales,
                       "perfiles": [{"nombre": s["nombre"], "tasa": s.get("tasa"), "proporcion": s["proporcion"],
                                     "accion": s["accion"]["tipo"]} for s in version["segmentos"]]}}
