"""Análisis en lenguaje natural de una configuración de reglas, para el panel «Reglas» de la vista.

Traduce lo que mide app/simulacion.py a frases que 30X puede leer sin conocer los umbrales:
qué pasa con cada persona, quién llega a un asesor, qué contenido sale y qué tan confiable es.

Se arma con plantillas a partir de los números de la simulación, no con un LLM: se actualiza al
instante cada vez que se mueve un control, no cuesta nada y no puede inventar cifras.
"""

from app.catalogo import PROGRAMAS

# Cómo se nombra cada rol en una frase (el catálogo trae la etiqueta formal de 30X).
ROLES_EN_FRASE = {
    "fundador": "fundadores o CEO",
    "c_level": "directivos C-level",
    "lider_comercial": "líderes comerciales",
    "gerente": "gerentes de área",
    "tecnico": "perfiles técnicos",
    "otro": "personas con otros roles",
    "sin_dato": "personas sin rol conocido",
}

PESOS_EN_FRASE = {
    "intencion": "la intención de compra",
    "poder_decision": "el poder de decisión",
    "claridad": "la claridad de la necesidad",
    "compromiso": "el compromiso observado",
}

CAMPOS_EN_FRASE = {"rol": "el rol", "dolor": "el dolor", "objetivo": "el objetivo"}

# Nombres de los controles tal como los ve 30X en la página (web/app.js, CONTROLES).
CONTROL = {
    "perfil_valido_min": "Perfil genuino",
    "listo_ventas_auto": "Asesor sin confirmar",
    "confianza_rol_ventas": "Certeza del rol para ventas",
    "listo_ventas_revision": "Proponer un asesor",
}


def _cada_100(n: int, total: int) -> str:
    v = n * 100 / total
    return "menos de 1 de cada 100" if 0 < v < 0.5 else f"{int(v + 0.5)} de cada 100"


def _por_mil(n: int, total: int) -> int:
    return int(n * 1000 / total + 0.5)


def _pct(x: float, decimales: int = 0) -> str:
    return f"{x * 100:.{decimales}f}".replace(".", ",") + " %"


def _lista(partes: list[str]) -> str:
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]


def _personas(n: int) -> str:
    return "1 persona" if n == 1 else f"{n} personas"


def _que_pasa(s: dict) -> dict:
    total, det = s["perfiles"], s["detalle"]
    auto = s["rutas"].get("automatico", 0)
    ayuda = total - auto
    frases = []
    if auto:
        frases.append(f"{_cada_100(auto, total).capitalize()} personas reciben su siguiente paso sin que intervenga "
                      "nadie del equipo: un asesor, contenido de su programa o contenido general.")
    if ayuda:
        frases.append(f"{_cada_100(ayuda, total).capitalize()} piden ayuda antes de cualquier acción: primero el LLM "
                      "y, si tampoco está seguro, una persona del equipo.")
        m = det["motivos"]
        motivos = []
        if n := m.get("perfil_no_genuino"):
            motivos.append(f"{n} {'no parece una inscripción real' if n == 1 else 'no parecen inscripciones reales'}")
        if n := m.get("duda"):
            campo = max(det["dudas"], key=det["dudas"].get) if det["dudas"] else None
            sobre = f" (sobre todo en {CAMPOS_EN_FRASE[campo]})" if campo else ""
            motivos.append(f"{n} {'tiene' if n == 1 else 'tienen'} una duda de JEV que cambiaría la decisión{sobre}")
        if n := m.get("intencion_no_concluyente"):
            motivos.append(f"{n} {'muestra' if n == 1 else 'muestran'} un interés de compra que no es concluyente")
        if n := m.get("rol_incierto_ventas"):
            motivos.append(f"{n} {'iría' if n == 1 else 'irían'} a ventas sin certeza de que "
                           f"{'pueda' if n == 1 else 'puedan'} decidir la compra")
        if motivos:
            frases.append(f"En la muestra de {total}: {_lista(motivos)}.")
    return {"titulo": "Qué pasa con cada persona", "frases": frases}


def _ventas(s: dict, politica: dict) -> tuple[dict, list[dict]]:
    total, det, u = s["perfiles"], s["detalle"], politica["umbrales"]
    af = politica["afinidad"]
    alertas = []
    decisores = [r for r, v in af["poder_decision_por_rol"].items() if v >= af["poder_decision_min_ventas"]]
    roles = _lista([ROLES_EN_FRASE.get(r, r) for r in decisores]) if decisores else "nadie"
    frases = [
        f"Solo se propone un asesor a {roles} que tengan un programa sugerido y al menos "
        f"{_pct(u['listo_ventas_revision'])} de probabilidad de estar listos para conversar.",
    ]
    if u["listo_ventas_auto"] <= u["listo_ventas_revision"]:
        alertas.append({"tono": "aviso", "texto": f"«{CONTROL['listo_ventas_auto']}» está igual o por debajo de "
                        f"«{CONTROL['listo_ventas_revision']}»: todo lo que se proponga a ventas pasará sin que "
                        "una persona confirme."})
    else:
        frases.append(f"Desde {_pct(u['listo_ventas_auto'])} pasan directo, siempre que JEV esté al menos "
                      f"{_pct(u['confianza_rol_ventas'])} seguro de su rol; por debajo, una persona confirma antes.")
    directo, confirmar = det["ventas_directo"], det["ventas_por_confirmar"]
    if directo or confirmar:
        partes = []
        if directo:
            partes.append(f"{_cada_100(directo, total)} personas llegarían directo a un asesor")
        if confirmar:
            partes.append(f"{_cada_100(confirmar, total)} esperarían confirmación para ir a ventas")
        frases.append(f"Con estos valores, {_lista(partes)}.")
    else:
        frases.append("Con estos valores, nadie llegaría a un asesor.")
    ayuda = total - s["rutas"].get("automatico", 0)
    asesores = (f"los asesores recibirían unas {_por_mil(directo, total)} personas de forma directa"
                if _por_mil(directo, total) else "los asesores no recibirían a nadie de forma directa")
    revision = (f"el equipo revisaría unas {_por_mil(ayuda, total)} inscripciones antes de actuar"
                if _por_mil(ayuda, total) else "el equipo no tendría nada que revisar")
    frases.append(f"En una semana con 1.000 inscripciones, {asesores} y {revision}.")
    perdidas = det["errores"].get("ventas_no_detectadas", 0)
    if perdidas:
        frases.append(f"Ojo: {_personas(perdidas)} de la muestra que sí estaban listas recibirían contenido "
                      "en lugar de un asesor.")
    return {"titulo": "Quién llega a un asesor", "frases": frases}, alertas


def _contenido(s: dict, politica: dict) -> tuple[dict, list[dict]]:
    total, det = s["perfiles"], s["detalle"]
    alertas, frases = [], []
    por_programa = sorted(det["contenido_programa"].items(), key=lambda kv: -kv[1])
    n_programa = sum(n for _, n in por_programa)
    if n_programa:
        detalle = ", ".join(f"{PROGRAMAS.get(p, p)} {n}" for p, n in por_programa)
        frases.append(f"{_cada_100(n_programa, total).capitalize()} personas reciben contenido de su programa "
                      f"(en la muestra: {detalle}).")
    if det["contenido_general"]:
        frases.append(f"{_cada_100(det['contenido_general'], total).capitalize()} reciben contenido general, porque "
                      "su afinidad es baja o ningún programa encaja con lo que contaron.")
    pesos = politica["afinidad"]["pesos"]
    suma = sum(pesos.values())
    if suma <= 0:
        alertas.append({"tono": "mal", "texto": "Todos los pesos de afinidad están en cero: nadie tendría un "
                        "programa sugerido y todos recibirían contenido general."})
    else:
        partes = [f"{_pct(v / suma)} {PESOS_EN_FRASE[k]}" for k, v in pesos.items()]
        mayor = max(pesos, key=pesos.get)
        frases.append(f"Para decidir si un programa encaja, la afinidad pesa {_lista(partes)}. "
                      f"Así, manda sobre todo {PESOS_EN_FRASE[mayor]}.")
    frases.append("Todo mensaje que redacte el LLM pasa antes por el guardrail de JEV, que frena promesas de "
                  "precios, descuentos o fechas sin respaldo, datos de contacto e instrucciones coladas.")
    return {"titulo": "Qué contenido sale", "frases": frases}, alertas


def _confianza(s: dict) -> tuple[dict, list[dict]]:
    det, alertas, frases = s["detalle"], [], []
    if s["rutas"].get("automatico"):
        frases.append(f"De lo que decide solo, {_pct(s['precision'], 1)} coincide con la respuesta correcta.")
        distintos = det["errores"].get("contenido_distinto", 0)
        if distintos:
            frases.append(f"Los errores de contenido son de bajo riesgo: {_personas(distintos)} de la muestra "
                          "recibirían el contenido de otro programa, o el general en lugar del suyo.")
    indebidos, trampas = s["pases_a_ventas_indebidos"], s["invalidos_automaticos"]
    if indebidos:
        alertas.append({"tono": "mal", "texto": f"{_personas(indebidos)} de la muestra llegarían a un asesor sin "
                        f"estar listas. Sube «{CONTROL['listo_ventas_auto']}» o «{CONTROL['confianza_rol_ventas']}»."})
    if trampas:
        alertas.append({"tono": "mal", "texto": f"{_personas(trampas)} con perfil trampa (spam o textos que intentan "
                        f"manipular al sistema) se procesarían sin revisión. Sube «{CONTROL['perfil_valido_min']}»."})
    if not indebidos and not trampas:
        frases.append("Ninguna persona llega a un asesor sin estar lista y ningún perfil trampa se procesa "
                      "sin revisión.")
    return {"titulo": "Qué tan confiable es", "frases": frases}, alertas


def _cambios(s: dict, a: dict, politica: dict, politica_actual: dict) -> list[str]:
    iguales = (politica["umbrales"] == politica_actual["umbrales"]
               and politica["afinidad"]["pesos"] == politica_actual["afinidad"]["pesos"])
    if iguales:
        return []
    total = s["perfiles"]
    cambios = []

    def comparar(nuevo: int, viejo: int, mas: str, menos: str) -> None:
        d = _por_mil(nuevo, total) - _por_mil(viejo, total)
        if d:
            cambios.append((mas if d > 0 else menos).format(n=abs(d)))

    auto_s, auto_a = s["rutas"].get("automatico", 0), a["rutas"].get("automatico", 0)
    comparar(auto_s, auto_a, "Pálpito decidiría por su cuenta en unos {n} casos más por cada 1.000 inscripciones.",
             "Pálpito decidiría por su cuenta en unos {n} casos menos por cada 1.000 inscripciones.")
    comparar(total - auto_s, total - auto_a, "El equipo revisaría unas {n} más por cada 1.000.",
             "El equipo revisaría unas {n} menos por cada 1.000.")
    comparar(s["detalle"]["ventas_directo"], a["detalle"]["ventas_directo"],
             "Los asesores recibirían unas {n} más de forma directa.",
             "Los asesores recibirían unas {n} menos de forma directa.")
    d = (s["precision"] - a["precision"]) * 100
    if abs(d) >= 0.05:
        puntos = f"{abs(d):.1f}".replace(".", ",")
        cambios.append(f"La precisión {'sube' if d > 0 else 'baja'} {puntos} puntos.")
    return cambios or ["Los resultados son los mismos que con la configuración actual."]


def analizar(simulada: dict, actual: dict, politica: dict, politica_actual: dict, modo: str) -> dict:
    """Devuelve el titular, las secciones, las alertas y los cambios frente a la configuración actual."""
    total = simulada["perfiles"]
    auto = simulada["rutas"].get("automatico", 0)
    ventas, alertas_ventas = _ventas(simulada, politica)
    contenido, alertas_contenido = _contenido(simulada, politica)
    confianza, alertas_confianza = _confianza(simulada)
    alertas = alertas_confianza + alertas_ventas + alertas_contenido

    titular = f"Con esta configuración, Pálpito decide por su cuenta en {_cada_100(auto, total)} casos"
    if auto < total:
        titular += f" y pide ayuda en {_cada_100(total - auto, total)}"
    seguro = not simulada["pases_a_ventas_indebidos"] and not simulada["invalidos_automaticos"]
    titular += ", sin dejar pasar ningún caso riesgoso." if seguro else ", pero dejaría pasar casos riesgosos."

    return {
        "titular": titular,
        "seguro": seguro,
        "alertas": alertas,
        "cambios": _cambios(simulada, actual, politica, politica_actual),
        "secciones": [_que_pasa(simulada), ventas, contenido, confianza],
        "nota": (f"Calculado sobre {total} inscripciones con las respuestas de JEV ya guardadas. "
                 "Mover los controles no vuelve a llamar a JEV."),
    }
