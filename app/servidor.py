"""Servidor local de la vista del prototipo. Solo usa la librería estándar de Python.

Sirve la página (web/) y una API pequeña:
- GET  /api/datos      métricas, decisiones y líneas de tiempo de las evaluaciones (reportes/)
- POST /api/inscribir  procesa una inscripción escrita en la página, en vivo
- POST /api/evento     agrega un evento a esa persona y la reclasifica
- POST /api/simular    recalcula todas las decisiones con otros umbrales y pesos, sin llamar a JEV
- POST /api/guardrail  JEV revisa un mensaje antes de enviarlo
- POST /api/perfiles   clasifica un lote (máx. 100) de perfiles con el formato del archivo de 30X

Las llaves de JEV y del LLM se quedan en el servidor (.env); el navegador nunca las ve.

Uso:
    python -m app.servidor            # http://localhost:8030
"""

import copy
import itertools
import json
import os
import runpy
import sys
import threading
from datetime import date, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.analisis import analizar
from app.catalogo import DOLORES, INTENCION, OBJETIVOS, PROGRAMAS, ROLES, TEMAS, por_id
from app.jev import crear_cliente, respuesta_desde_registro
from app.llm import crear_llm
from app.guardrail import revisar_mensaje
from app.lote import clasificar_lote
from app.motor import juicios_desde_jev, redactar_mensaje
from app.personas import aplicar_evento, crear_persona, reevaluar
from app.politica import ACCIONES, cargar_politica, explicar
from app.preguntas import construir_estado
from app.simulacion import medir

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"
REPORTES = RAIZ / "reportes"
PUERTO = int(os.environ.get("PUERTO", "8030"))
OPCIONES = {"rol": por_id(ROLES), "dolor": por_id(DOLORES), "objetivo": por_id(OBJETIVOS)}

cliente = crear_cliente()
llm = crear_llm()
NOMBRE = "mock" if cliente.__class__.__name__ == "JEVMock" else "live"
politica = cargar_politica()
personas_demo: dict = {}
contador = itertools.count(1)
candado = threading.Lock()


def asegurar_reportes() -> None:
    """Si faltan los reportes de este modo, corre las evaluaciones una vez."""
    for script, archivo in (("evaluar.py", f"metricas_{NOMBRE}.json"), ("evaluar_dinamica.py", f"dinamica_{NOMBRE}.json")):
        if not (REPORTES / archivo).exists():
            print(f"Generando reportes con scripts/{script}…")
            runpy.run_path(str(RAIZ / "scripts" / script), run_name="vista")["main"](None)


def leer_json(nombre: str):
    ruta = REPORTES / nombre
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def datos() -> dict:
    decisiones = []
    ruta = REPORTES / f"decisiones_{NOMBRE}.jsonl"
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            r = json.loads(linea)
            decisiones.append({k: r.get(k) for k in ("perfil_id", "estado_enviado", "temas", "respuestas_jev", "decision",
                                                      "explicacion", "revisiones_llm", "esperado", "etiquetas",
                                                      "latencia_ms", "costo_usd", "costo_llm_usd")})
    return {
        "modo": NOMBRE,
        "llm": "off" if llm is None else ("mock" if llm.__class__.__name__ == "LLMMock" else "live"),
        "metricas": leer_json(f"metricas_{NOMBRE}.json"),
        "dinamica": leer_json(f"dinamica_{NOMBRE}.json"),
        "historiales": leer_json(f"historiales_{NOMBRE}.json") or [],
        "decisiones": decisiones,
        "catalogo": catalogo(),
        "politica": politica,
    }


_simulacion: dict = {}


def base_simulacion() -> tuple[list[dict], dict]:
    """Perfiles y juicios de JEV guardados en la última evaluación (se leen una vez)."""
    if not _simulacion:
        perfiles, juicios = [], {}
        ruta = REPORTES / f"decisiones_{NOMBRE}.jsonl"
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            r = json.loads(linea)
            perfiles.append({"id": r["perfil_id"], "temas": r["temas"], "etiquetas": r["etiquetas"]})
            # Misma conversión que el flujo real (incluye combinar el dolor con su pregunta de presencia).
            juicios[r["perfil_id"]] = juicios_desde_jev(respuesta_desde_registro(r["respuestas_jev"]))
        _simulacion.update(perfiles=perfiles, juicios=juicios, actual=medir(perfiles, juicios, politica))
    return _simulacion["perfiles"], _simulacion["juicios"]


def simular(cuerpo: dict) -> dict:
    """Aplica los umbrales y pesos de la página sobre las respuestas ya guardadas de JEV."""
    perfiles, juicios = base_simulacion()
    nueva = copy.deepcopy(politica)
    for grupo, destino in (("umbrales", nueva["umbrales"]), ("pesos", nueva["afinidad"]["pesos"])):
        for clave, valor in (cuerpo.get(grupo) or {}).items():
            if clave not in destino:
                raise ValueError(f"Parámetro desconocido: {clave}")
            valor = float(valor)
            if not 0.0 <= valor <= 1.0:
                raise ValueError(f"{clave} debe estar entre 0 y 1")
            destino[clave] = valor
    simulada = medir(perfiles, juicios, nueva)
    return {"actual": _simulacion["actual"], "simulada": simulada, "politica": nueva,
            "analisis": analizar(simulada, _simulacion["actual"], nueva, politica, NOMBRE)}


def guardrail(cuerpo: dict) -> dict:
    mensaje = str(cuerpo.get("mensaje", "")).strip()
    programa = cuerpo.get("programa")
    if not mensaje:
        raise ValueError("Escribe el mensaje a revisar.")
    if programa not in PROGRAMAS:
        raise ValueError("Programa desconocido.")
    contexto = {"programa": PROGRAMAS[programa], "lo_que_dijo_la_persona": str(cuerpo.get("contexto", "")).strip() or "(sin datos)"}
    return revisar_mensaje(mensaje, contexto, cliente, politica)


def catalogo() -> dict:
    return {
        "programas": PROGRAMAS,
        "acciones": ACCIONES,
        "temas": TEMAS,
        "rol": {o.id: o.etiqueta for o in ROLES},
        "dolor": {o.id: o.etiqueta for o in DOLORES},
        "objetivo": {o.id: o.etiqueta for o in OBJETIVOS},
        "intencion": [o.etiqueta for o in INTENCION],
    }


def vista_persona(p, mensaje=None) -> dict:
    j, d = p.juicios, p.decision
    return {
        "id": p.id,
        "segmento": {"programa": d.programa, "banda": d.banda, "afinidad": d.afinidad, "accion": d.accion,
                     "accion_propuesta": d.accion_propuesta, "ruta": d.ruta, "razones": d.razones,
                     "compromiso": d.compromiso, "regla": d.regla_programa},
        "juicios": {campo: {"valor": getattr(j, campo).valor, "confianza": getattr(j, campo).confianza,
                            "probabilidades": getattr(j, campo).probabilidades} for campo in ("rol", "dolor", "objetivo")},
        "intencion": {str(k): v for k, v in j.intencion_probabilidades.items()},
        "perfil_valido": j.perfil_valido,
        "explicacion": explicar(j, d),
        "mensaje": mensaje.texto if mensaje else None,
        "guardrail": mensaje.guardrail if mensaje else None,
        "historial": p.historial,
    }


def mensaje_para(p):
    estado = construir_estado(p.perfil, p.cargo_actual, p.mensajes)
    return redactar_mensaje(estado, p.decision, explicar(p.juicios, p.decision), llm, cliente, politica)


def inscribir(cuerpo: dict) -> dict:
    campos = {k: str(cuerpo.get(k, "")).strip() for k in ("cargo", "que_te_gustaria_lograr", "mayor_reto_hoy", "comentario")}
    temas = [t for t in cuerpo.get("temas", []) if t in TEMAS]
    canal = cuerpo.get("canal", "formulario_luma")
    if canal == "formulario_luma":
        entrada = {k: v for k, v in campos.items() if v}
    else:
        entrada = " ".join(v for v in (campos["cargo"] and f"Soy {campos['cargo']}.", campos["mayor_reto_hoy"],
                                       campos["que_te_gustaria_lograr"], campos["comentario"]) if v)
    if not entrada:
        raise ValueError("Escribe al menos un campo de la inscripción.")
    with candado:
        pid = f"DEMO-{next(contador):03d}"
    perfil = {"id": pid, "canal": canal, "entrada": entrada, "temas": temas}
    p = crear_persona(perfil, date.today())
    reevaluar(p, date.today(), cliente, {"tipo": "inscripcion", "fecha": date.today()}, politica, llm)
    personas_demo[pid] = p
    return vista_persona(p, mensaje_para(p))


def agregar_evento(cuerpo: dict) -> dict:
    p = personas_demo.get(cuerpo.get("id"))
    if p is None:
        raise ValueError("Esa persona ya no existe en el servidor; inscríbela de nuevo.")
    ultima = max([p.fecha_registro] + [m["fecha"] for m in p.mensajes] + [a["fecha"] for a in p.asistencias])
    fecha = ultima + timedelta(days=max(0, int(cuerpo.get("dias_despues", 7))))
    tipo = cuerpo.get("tipo")
    texto = str(cuerpo.get("texto", "")).strip()
    evento = {"tipo": tipo, "fecha": fecha}
    if tipo == "asistio_evento":
        evento["evento"] = texto or "Evento de 30X"
    elif tipo == "cambio_cargo":
        evento["cargo"] = texto
    elif tipo in ("respondio_correo", "encuesta_post_evento"):
        evento["texto"] = texto
    else:
        raise ValueError("Tipo de evento desconocido.")
    if tipo != "asistio_evento" and not texto:
        raise ValueError("Este evento necesita texto.")
    aplicar_evento(p, evento)
    reevaluar(p, fecha, cliente, evento, politica, llm)
    return vista_persona(p, mensaje_para(p))


class Manejador(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def _json(self, cuerpo, codigo=200):
        datos_json = json.dumps(cuerpo, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos_json)))
        self.end_headers()
        self.wfile.write(datos_json)

    def do_GET(self):
        if self.path == "/api/datos":
            return self._json(datos())
        return super().do_GET()

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", "0"))
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
            if self.path == "/api/inscribir":
                return self._json(inscribir(cuerpo))
            if self.path == "/api/evento":
                return self._json(agregar_evento(cuerpo))
            if self.path == "/api/simular":
                return self._json(simular(cuerpo))
            if self.path == "/api/guardrail":
                return self._json(guardrail(cuerpo))
            if self.path == "/api/perfiles":
                return self._json(clasificar_lote(cuerpo.get("filas") or [], politica))
            return self._json({"error": "Ruta desconocida"}, 404)
        except ValueError as e:
            return self._json({"error": str(e)}, 400)

    def log_message(self, formato, *args):
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write(f"{self.address_string()} {formato % args}\n")


def main() -> None:
    asegurar_reportes()
    servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
    print(f"Vista del prototipo en http://localhost:{PUERTO}  (JEV: {NOMBRE}, LLM: {datos()['llm']})")
    servidor.serve_forever()


if __name__ == "__main__":
    main()
