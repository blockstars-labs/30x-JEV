"""Política de decisión: lo que JEV juzga se combina aquí, en código, con reglas explícitas.

JEV no decide el programa ni la acción: responde preguntas simples (rol, dolor, objetivo,
intención, validez del perfil) y esta capa aplica reglas, pesos y umbrales. Así cada decisión
se puede explicar y los umbrales se pueden cambiar sin volver a llamar al modelo.
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from app.catalogo import DOLORES, OBJETIVOS, PROGRAMAS, ROLES, por_id

RUTA_POLITICA = Path(__file__).resolve().parent.parent / "config" / "politica.json"

ROLES_DECISORES = {"fundador", "c_level"}
OBJETIVOS_EJECUTIVOS = {"expandirse", "levantar_capital", "red_pares", "delegar", "liderazgo", "transformar_modelo"}
DOLORES_EJECUTIVOS = {"dueno_cuello_botella", "claridad_estrategica", "capital", "equipo", "expansion_sin_metodo"}
DOLORES_COMERCIALES = {"sin_proceso_comercial", "referidos", "ventas_estancadas"}

ACCIONES = {
    "pasar_a_ventas": "Pasar a un asesor comercial",
    "nutrir_programa": "Enviar contenido relacionado con el programa sugerido",
    "nutrir_general": "Enviar contenido general (sin programa sugerido)",
    "revision_humana": "Revisión humana antes de cualquier acción",
}


def cargar_politica(ruta: Path = RUTA_POLITICA) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


@dataclass
class Juicio:
    """Respuesta de una pregunta Choice (o su equivalente exacto en los datos etiquetados)."""
    valor: str
    confianza: float = 1.0
    probabilidades: dict[str, float] = field(default_factory=dict)

    def segunda_opcion(self) -> str | None:
        ordenadas = sorted(self.probabilidades.items(), key=lambda kv: kv[1], reverse=True)
        return ordenadas[1][0] if len(ordenadas) > 1 else None


@dataclass
class Juicios:
    rol: Juicio
    dolor: Juicio
    objetivo: Juicio
    intencion_esperada: float            # posición 0..3 en la escala de intención (Score)
    intencion_probabilidades: dict[int, float]
    perfil_valido: float                 # probabilidad (Noul) de que sea una inscripción genuina

    @property
    def p_listo(self) -> float:
        return self.intencion_probabilidades.get(3, 0.0)


@dataclass
class Resultado:
    programa: str
    regla_programa: str
    banda: str
    afinidad: float
    accion: str


@dataclass
class Decision:
    programa: str
    regla_programa: str
    banda: str
    afinidad: float
    accion: str                # acción final (revision_humana si no actúa solo)
    accion_propuesta: str      # lo que haría si actuara solo
    ruta: str                  # "automatico", "llm" (resuelto por el LLM) o "revision_humana"
    razones: list[str]
    compromiso: str = "medio"  # señal observada (código), no inferida por JEV
    dudas: list[str] = field(default_factory=list)  # campos cuya duda cambia la decisión
    # Por qué no actúa solo: perfil_no_genuino, duda, intencion_no_concluyente o rol_incierto_ventas.
    motivo: str = ""


def banda_afinidad(rol: str, dolor: str, objetivo: str, intencion_esperada: float, politica: dict,
                   compromiso: str = "medio") -> tuple[str, float]:
    """Afinidad compuesta: intención y claridad (JEV), poder de decisión (por rol) y compromiso
    observado (calculado en código a partir de la actividad), con pesos en config."""
    cfg = politica["afinidad"]
    pesos = cfg["pesos"]
    claridad = 0.5 * (dolor != "ninguno") + 0.5 * (objetivo != "otro")
    valor = (pesos["intencion"] * intencion_esperada / 3
             + pesos["poder_decision"] * cfg["poder_decision_por_rol"][rol]
             + pesos["claridad"] * claridad
             + pesos["compromiso"] * cfg["valor_compromiso"][compromiso])
    banda = cfg["bandas"][0]["id"]
    for b in cfg["bandas"]:
        if valor >= b["desde"]:
            banda = b["id"]
    return banda, round(valor, 3)


def asignar_programa(rol: str, dolor: str, objetivo: str, temas: list[str], banda: str) -> tuple[str, str]:
    """Reglas de ejemplo para sugerir programa. Son configurables y deben validarse con 30X.

    Achievers no tiene regla todavía: con los datos de demo no se distingue un patrón claro.
    """
    if banda == "baja":
        return "ninguno", "Afinidad baja: no se sugiere programa todavía"
    if rol in ROLES_DECISORES and (objetivo in OBJETIVOS_EJECUTIVOS or dolor in DOLORES_EJECUTIVOS):
        return "inmersion_ejecutiva", "Decisor con objetivo o dolor de dirección del negocio"
    if objetivo == "maquina_ventas" or dolor in DOLORES_COMERCIALES:
        return "sales_machine", "Necesita estructurar su proceso comercial"
    if rol == "tecnico" or (objetivo == "automatizar_ia" and dolor == "procesos_manuales"):
        return "hardcore_ai", "Perfil técnico o automatización de procesos manuales"
    if objetivo in {"automatizar_ia", "formarse_ia", "vender_mas"} and "sales" in temas:
        return "ai_sales", "Quiere IA o más ventas y le interesa el tema ventas"
    if objetivo == "vender_mas":
        return "sales_machine", "Su objetivo es vender más"
    if objetivo in {"automatizar_ia", "formarse_ia"} and "ai" in temas:
        return "ai_sales", "Interés en IA aplicada"
    if rol in ROLES_DECISORES:
        return "inmersion_ejecutiva", "Decisor sin otra señal más específica"
    return "ninguno", "Ninguna regla aplica"


def programa_aprendido(rol: str, dolor: str, objetivo: str, temas: list[str], politica: dict) -> tuple[str, float] | None:
    """Programa que sugiere el modelo entrenado con los deals del CRM (scripts/entrenar_programas.py).

    Devuelve (programa del catálogo, probabilidad) solo si la sección está activa, el modelo supera
    su umbral de confianza y el programa tiene equivalente en el catálogo. Si no, None: manda la regla.
    """
    sec = politica.get("perfiles_por_programa")
    if not sec or not sec.get("activo") or sec.get("umbral_confianza") is None:
        return None
    pesos = sec["pesos"]
    activos = {f"rol={rol}", f"dolor={dolor}", f"objetivo={objetivo}"} | {f"tema={t}" for t in temas}
    x = [1.0 if v in activos else 0.0 for v in pesos["variables"]]
    logits = [b + sum(w * xi for w, xi in zip(fila, x)) for fila, b in zip(pesos["coeficientes"], pesos["intercepto"])]
    tope = max(logits)
    exps = [math.exp(z - tope) for z in logits]
    i = max(range(len(exps)), key=exps.__getitem__)
    p = exps[i] / sum(exps)
    programa = sec["programa_catalogo"].get(pesos["clases"][i])
    if programa is None or p < sec["umbral_confianza"]:
        return None
    return programa, p


def evaluar_combinacion(rol: str, dolor: str, objetivo: str, intencion_esperada: float, p_listo: float,
                        temas: list[str], politica: dict, compromiso: str = "medio") -> Resultado:
    banda, afinidad = banda_afinidad(rol, dolor, objetivo, intencion_esperada, politica, compromiso)
    programa, regla = asignar_programa(rol, dolor, objetivo, temas, banda)
    # Con afinidad baja no se sugiere programa, lo diga quien lo diga.
    aprendido = programa_aprendido(rol, dolor, objetivo, temas, politica) if banda != "baja" else None
    if aprendido and aprendido[0] != programa:
        programa = aprendido[0]
        regla = f"Perfil típico de {PROGRAMAS[programa]} en los deals del CRM (confianza {aprendido[1]:.2f})"
    poder = politica["afinidad"]["poder_decision_por_rol"][rol]
    if (programa != "ninguno" and poder >= politica["afinidad"]["poder_decision_min_ventas"]
            and p_listo >= politica["umbrales"]["listo_ventas_revision"]):
        accion = "pasar_a_ventas"
    elif programa != "ninguno":
        accion = "nutrir_programa"
    else:
        accion = "nutrir_general"
    return Resultado(programa, regla, banda, afinidad, accion)


def decidir(j: Juicios, temas: list[str], politica: dict | None = None, compromiso: str = "medio") -> Decision:
    politica = politica or cargar_politica()
    u = politica["umbrales"]
    base = evaluar_combinacion(j.rol.valor, j.dolor.valor, j.objetivo.valor,
                               j.intencion_esperada, j.p_listo, temas, politica, compromiso)
    razones: list[str] = []
    dudas: list[str] = []

    def decision(ruta: str, motivo: str = "") -> Decision:
        accion = base.accion if ruta == "automatico" else "revision_humana"
        return Decision(base.programa, base.regla_programa, base.banda, base.afinidad,
                        accion, base.accion, ruta, razones, compromiso, dudas, motivo)

    if j.perfil_valido < u["perfil_valido_min"]:
        razones.append(f"El perfil no parece una inscripción genuina (p={j.perfil_valido:.2f}): "
                       "posible spam, prueba o texto con instrucciones al sistema.")
        return decision("revision_humana", "perfil_no_genuino")

    # Solo importa la duda que cambiaría la decisión: si la segunda opción lleva al mismo
    # programa y acción, la baja confianza de ese campo no frena nada.
    for campo in ("rol", "dolor", "objetivo"):
        juicio: Juicio = getattr(j, campo)
        if juicio.confianza >= u["confianza_choice_min"]:
            continue
        alternativa = juicio.segunda_opcion()
        if alternativa is None:
            continue
        valores = {"rol": j.rol.valor, "dolor": j.dolor.valor, "objetivo": j.objetivo.valor, campo: alternativa}
        otro = evaluar_combinacion(valores["rol"], valores["dolor"], valores["objetivo"],
                                   j.intencion_esperada, j.p_listo, temas, politica, compromiso)
        if (otro.programa, otro.accion) != (base.programa, base.accion):
            dudas.append(campo)
            razones.append(f"Duda en {campo} (confianza {juicio.confianza:.2f}) entre "
                           f"'{etiqueta(campo, juicio.valor)}' y '{etiqueta(campo, alternativa)}', "
                           "y eso cambia la decisión.")
    if razones:
        return decision("revision_humana", "duda")

    if base.accion == "pasar_a_ventas" and j.p_listo < u["listo_ventas_auto"]:
        razones.append(f"La intención de compra no es concluyente (p={j.p_listo:.2f}): "
                       "confirmar antes de pasar a ventas.")
        return decision("revision_humana", "intencion_no_concluyente")

    # Pasar a ventas es la acción con más consecuencias: exige más certeza sobre quién decide.
    if base.accion == "pasar_a_ventas" and j.rol.confianza < u["confianza_rol_ventas"]:
        razones.append(f"El rol no es seguro (confianza {j.rol.confianza:.2f}) y define si la persona "
                       "puede decidir la compra: confirmar antes de pasar a ventas.")
        return decision("revision_humana", "rol_incierto_ventas")

    return decision("automatico")


ETIQUETAS = {"rol": por_id(ROLES), "dolor": por_id(DOLORES), "objetivo": por_id(OBJETIVOS)}


def etiqueta(campo: str, valor: str) -> str:
    return ETIQUETAS[campo][valor].etiqueta


def explicar(j: Juicios, d: Decision) -> str:
    """Explicación legible por cualquier persona, construida solo con datos de la decisión."""
    partes = [
        f"Rol: {etiqueta('rol', j.rol.valor)} ({j.rol.confianza:.2f})",
        f"Dolor: {etiqueta('dolor', j.dolor.valor)} ({j.dolor.confianza:.2f})",
        f"Objetivo: {etiqueta('objetivo', j.objetivo.valor)} ({j.objetivo.confianza:.2f})",
        f"Compromiso observado: {d.compromiso}",
        f"Afinidad {d.banda} ({d.afinidad:.2f}), probabilidad de estar listo para ventas {j.p_listo:.2f}",
        f"Programa: {PROGRAMAS[d.programa]} — {d.regla_programa}",
    ]
    if d.ruta == "automatico":
        partes.append(f"Acción automática: {ACCIONES[d.accion]}")
    elif d.ruta == "llm":
        partes.append(f"Acción automática tras revisión del LLM: {ACCIONES[d.accion]}. " + " ".join(d.razones))
    else:
        partes.append(f"Va a revisión humana (propuesta: {ACCIONES[d.accion_propuesta]}). " + " ".join(d.razones))
    return ". ".join(partes).rstrip(".") + "."
