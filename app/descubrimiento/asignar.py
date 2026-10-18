"""Fase 7 · Asignación en línea: cada persona nueva, a su segmento y a su siguiente paso, en milisegundos.

Una llamada a JEV por persona con solo las variables que se quedaron, el guardrail de perfil genuino y una
pregunta de encaje ("¿a cuál de estos segmentos se parece?", con la opción "ninguno"): si mucha gente no
encaja en ninguno, está apareciendo un segmento nuevo (fase 8). El resto es aritmética con los pesos
exportados de la versión, sin scikit-learn, igual que el modelo de programa de app/politica.py.

Reglas fijas (no las cambia el riesgo): perfil no genuino → una persona; duda de segmento → primero el LLM y,
si sigue la duda, una persona; pasar a un asesor exige más certeza que mandar contenido.
"""

import math

from app.descubrimiento.esquema import Ficha
from app.descubrimiento.jev_dinamico import PreguntaDinamica
from app.descubrimiento.medir import claves_variable, codificar, estado_fila, pregunta_genuina, rasgos_de_respuesta
from app.descubrimiento.proponer import Variable

ENCAJE_NINGUNO = 0.6


def _softmax(xs: list[float]) -> list[float]:
    m = max(xs)
    e = [math.exp(x - m) for x in xs]
    s = sum(e)
    return [v / s for v in e]


class Segmentador:
    def __init__(self, version: dict, cliente):
        self.version = version
        self.cliente = cliente
        self.ficha = Ficha.desde_dict(version["ficha"])
        self.variables = {d["id"]: Variable.desde_dict(d) for d in version["variables"]}
        esp = version["espacio"]
        self.claves, self.media, self.desv, self.pesos = esp["claves"], esp["media"], esp["desv"], esp["pesos"]
        self.segmentos = version["segmentos"]
        self.centros = [s["centro"] for s in self.segmentos]
        u = version["umbrales"]
        self.tau = u["tau"]
        self.t_asignacion = (u["asignacion"]["elegido"] or {}).get("umbral", 0.5)
        self.t_asesor = (u.get("asesor") or {}).get("umbral", self.t_asignacion)
        self.propension = u.get("propension")
        self.genuino_min = u["genuino_min"]
        self.abandono = self.ficha.tipo_resultado == "abandono"
        self.campos = [c.nombre for c in self.ficha.por_rol("rasgo", ("texto",))]
        bases = list(dict.fromkeys(k.split("=", 1)[0] for k in self.claves))
        self.usadas = [self.variables[b] for b in bases if b in self.variables]
        self.spec = version["estructuradas"]
        self.nombre = {s["id"]: s["nombre"] for s in self.segmentos}

    # ---------- Preguntas ----------
    def pregunta_encaje(self) -> PreguntaDinamica:
        opciones = {s["id"]: {"grupo": s["nombre"], "como_es": s["descripcion"]} for s in self.segmentos}
        opciones["ninguno"] = "The person fits none of these groups."
        return PreguntaDinamica("_encaje", "choice",
                                "Which of these groups of people does this person belong to, judging only by what they wrote?",
                                opciones, pistas={s["id"]: s.get("pistas", []) for s in self.segmentos}, foco=self.campos)

    def preguntas(self, con_encaje: bool = True) -> list[PreguntaDinamica]:
        return ([v.pregunta() for v in self.usadas] + [pregunta_genuina(self.campos)]
                + ([self.pregunta_encaje()] if con_encaje else []))

    # ---------- Asignación ----------
    def asignar(self, fila: dict, con_encaje: bool = True) -> dict:
        return self.asignar_lote([fila], con_encaje)[0]

    def asignar_lote(self, filas: list[dict], con_encaje: bool = True) -> list[dict]:
        estados = [estado_fila(f, self.campos) for f in filas]
        con_texto = [i for i, e in enumerate(estados) if e]
        respuestas = self.cliente.evaluar_lote([estados[i] for i in con_texto], self.preguntas(con_encaje)) if con_texto else []
        por_fila = dict(zip(con_texto, respuestas))
        return [self._decidir(f, por_fila.get(i)) for i, f in enumerate(filas)]

    def vector(self, fila: dict, r) -> list[float]:
        rasgos = {}
        for v in self.usadas:
            rasgos.update(rasgos_de_respuesta(v, r) if r is not None else {k: 0.0 for k in claves_variable(v)})
        rasgos.update(codificar(self.spec, fila))
        return [rasgos.get(k, 0.0) for k in self.claves]

    def _probabilidades(self, x: list[float]) -> list[float]:
        z = [(xi - m) / d * w for xi, m, d, w in zip(x, self.media, self.desv, self.pesos)]
        d2 = [sum((zi - ci) ** 2 for zi, ci in zip(z, c)) for c in self.centros]
        return _softmax([-d / self.tau for d in d2])

    def _propension(self, x: list[float]) -> float | None:
        p = self.propension
        if not p:
            return None
        logit = p["intercepto"] + sum(c * (xi - m) / d for c, xi, m, d in zip(p["coeficientes"], x, p["media"], p["desv"]))
        return 1 / (1 + math.exp(-logit))

    def _decidir(self, fila: dict, r) -> dict:
        x = self.vector(fila, r)
        probs = self._probabilidades(x)
        orden = sorted(range(len(probs)), key=lambda i: -probs[i])
        seg = self.segmentos[orden[0]]
        conf = probs[orden[0]]
        genuino = r.nouls.get("_genuino", 1.0) if r is not None else 1.0
        encaje = r.choices.get("_encaje") if r is not None else None
        ninguno = (encaje or {}).get("probabilidades", {}).get("ninguno", 0.0)
        p_prop = self._propension(x)
        alto = "contactar" if self.abandono else "asesor"
        accion = dict(seg["accion"])
        motivos, ruta = [], "automatico"

        if genuino < self.genuino_min:
            ruta, accion = "revision_humana", {"tipo": "revision", "programa": None, "porque": ""}
            motivos.append(f"No parece una inscripción genuina (p={genuino:.2f}): spam, prueba o texto con instrucciones al sistema.")
        elif conf < self.t_asignacion:
            otro = self.segmentos[orden[1]] if len(orden) > 1 else seg
            ruta = "revision"
            motivos.append(f"No encaja con claridad: duda entre «{seg['nombre']}» ({conf:.2f}) y «{otro['nombre']}» "
                           f"({probs[orden[1]] if len(orden) > 1 else 0:.2f}).")
        elif ninguno >= ENCAJE_NINGUNO:
            ruta = "revision"
            motivos.append(f"No se parece a ningún segmento conocido (p={ninguno:.2f}): puede estar apareciendo uno nuevo.")
        else:
            umbral_p = (self.propension or {}).get("umbral")
            if accion["tipo"] != alto and p_prop is not None and umbral_p is not None and p_prop >= umbral_p:
                verbo = "abandonar" if self.abandono else "convertir"
                accion = {"tipo": alto, "programa": accion.get("programa"),
                          "porque": f"Sus propias señales dan {p_prop:.0%} de probabilidad de {verbo} (umbral aprendido: {umbral_p:.0%})."}
            if accion["tipo"] == alto and conf < self.t_asesor:
                ruta = "revision"
                motivos.append(f"Pasar a {'contacto' if self.abandono else 'un asesor'} exige más certeza ({conf:.2f} < {self.t_asesor:.2f}).")

        return {
            "segmento": seg["id"], "nombre": seg["nombre"], "confianza": round(conf, 3),
            "probabilidades": {self.segmentos[i]["id"]: round(probs[i], 3) for i in orden},
            "propension": None if p_prop is None else round(p_prop, 3), "accion": accion, "ruta": ruta, "motivos": motivos,
            "genuino": round(genuino, 3), "ninguno": round(ninguno, 3),
            "explicacion": self._explicar(seg, conf, x, accion, ruta, motivos),
            "tokens": r.tokens_entrada if r is not None else 0, "costo_usd": r.costo_usd if r is not None else 0.0,
            "latencia_ms": round(r.latencia_ms, 1) if r is not None else 0.0,
        }

    def _explicar(self, seg: dict, conf: float, x: list[float], accion: dict, ruta: str, motivos: list[str]) -> str:
        valores = dict(zip(self.claves, x))
        comparte = [r["descripcion"] for r in seg["rasgos"] if valores.get(r["clave"], 0) >= (0.5 if r["proporcion"] else r["total"])][:2]
        partes = [f"Se parece al segmento «{seg['nombre']}» (confianza {conf:.2f})"]
        if comparte:
            partes[0] += ": " + "; ".join(c[0].lower() + c[1:] for c in comparte)
        if ruta == "automatico":
            partes.append(f"Siguiente paso: {TEXTO_ACCION.get(accion['tipo'], accion['tipo'])}"
                          + (f" ({accion['programa']})" if accion.get("programa") else "") + ". " + accion.get("porque", ""))
        else:
            partes.append(" ".join(motivos))
        return ". ".join(p.strip().rstrip(".") for p in partes if p) + "."


TEXTO_ACCION = {"asesor": "pasar a un asesor", "contenido_programa": "enviar contenido del programa",
                "contenido_general": "enviar contenido general", "contenido_tema": "enviar contenido sobre su tema",
                "contactar": "contactarlo a tiempo", "seguimiento": "seguimiento normal", "revision": "revisión"}


class Seguimiento:
    """Historial de segmento por persona: la clusterización dinámica vista desde cada persona."""

    def __init__(self):
        self.personas: dict[str, list[dict]] = {}

    def registrar(self, pid: str, fecha: str, asignacion: dict, evento: str = "") -> dict | None:
        historia = self.personas.setdefault(pid, [])
        anterior = historia[-1] if historia else None
        historia.append({"fecha": fecha, "evento": evento, "segmento": asignacion["segmento"], "nombre": asignacion["nombre"],
                         "accion": asignacion["accion"]["tipo"], "confianza": asignacion["confianza"]})
        if anterior and anterior["segmento"] != asignacion["segmento"]:
            return {"persona": pid, "fecha": fecha, "evento": evento, "de": anterior["nombre"], "a": asignacion["nombre"],
                    "accion_antes": anterior["accion"], "accion_ahora": asignacion["accion"]["tipo"]}
        return None
