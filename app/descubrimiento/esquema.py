"""Fase 1 · Ficha del dataset: qué trae cada columna y para qué sirve, sin que nadie lo diga antes.

El código detecta el tipo de cada columna (texto, categoría, número, fecha…). JEV juzga lo semántico:
si una columna trae datos personales, si es la salida de una clasificación anterior (usarla copiaría
esa regla) o si registra el resultado. JEV también elige cuál es la columna de resultado, qué valores
cuentan como positivos y cuál registra el programa. El código, por último, busca fugas: columnas que
delatan el resultado casi siempre porque se llenan después de él.
"""

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from app.descubrimiento.datos import normalizar
from app.descubrimiento.jev_dinamico import PreguntaDinamica

_CORREO = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.I)
_TELEFONO = re.compile(r"^\+?[\d\s\-().]{7,}$")
_BOOLEANOS = {"si", "no", "true", "false", "1", "0", "yes", "verdadero", "falso", "x"}
_SEPARADORES = (",", "|", ";")

# Pistas solo para el JEV simulado (el JEV real juzga el nombre y los ejemplos de cada columna).
_MOCK_PERSONAL = ["nombre", "name", "apellido", "correo", "email", "mail", "telefono", "celular", "phone",
                  "whatsapp", "documento", "cedula", "direccion", "@", "+57", "+52", "+51"]
_MOCK_DERIVADA = ["sugerido", "afinidad", "banda", "score", "puntaje", "nivel de info", "informacion disponible",
                  "segmento", "clasificacion", "prediccion", "propension"]
_MOCK_RESULTADO = ["resultado", "estado", "etapa", "relacion con", "convirt", "agendo", "ganad", "deal", "pipeline",
                   "status", "abandon", "desert", "termino"]
_MOCK_CONVERSION_SI = ["compr", "pag", "ganad", "agend", "demo", "deal en", "cliente", "en proceso", "oportunidad perdida",
                       "negociac", "=si", "=yes", "=true", "=1"]
_MOCK_CONVERSION_NO = ["sin oportunidad", "sin deal", "lead (sin", "no le interesa", "sin respuesta", "descart", "nutric",
                       "=no", "=false", "=0"]
_MOCK_ABANDONO_SI = ["abandon", "desert", "retir", "dejo el", "=si", "=yes", "=true", "=1"]
_MOCK_ABANDONO_NO = ["termin", "complet", "graduad", "activo", "=no", "=false", "=0"]


@dataclass
class Columna:
    nombre: str
    tipo: str = "texto"         # identificador | personal | texto | categoria | multicategoria | numero | fecha | booleano | vacia
    rol: str = "rasgo"          # rasgo | resultado | accion | excluida
    motivo: str = ""
    valores_distintos: int = 0
    faltantes: float = 0.0
    ejemplos: list = field(default_factory=list)
    categorias: list = field(default_factory=list)   # valores frecuentes (categoría y multicategoría)
    jev: dict = field(default_factory=dict)          # probabilidades de los juicios semánticos


@dataclass
class Ficha:
    dataset: str
    filas: int
    columnas: list[Columna]
    resultado: str | None = None
    tipo_resultado: str | None = None        # conversion | abandono | otro
    valores_positivos: list = field(default_factory=list)
    tasa_positiva: float | None = None
    accion: str | None = None
    acciones: list = field(default_factory=list)   # catálogo: todos los valores de la columna de acción
    tokens_jev: int = 0

    def col(self, nombre: str) -> Columna:
        return next(c for c in self.columnas if c.nombre == nombre)

    def por_rol(self, rol: str, tipos: tuple = ()) -> list[Columna]:
        return [c for c in self.columnas if c.rol == rol and (not tipos or c.tipo in tipos)]

    def positivo(self, fila: dict) -> int | None:
        """1 si la fila tiene el resultado de interés, 0 si no, None si no hay columna de resultado."""
        if not self.resultado:
            return None
        return int(fila.get(self.resultado, "") in self.valores_positivos)

    def a_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def desde_dict(cls, d: dict) -> "Ficha":
        d = dict(d)
        d["columnas"] = [Columna(**c) for c in d["columnas"]]
        return cls(**d)


# ---------- Tipos (código) ----------
def _es_numero(v: str) -> bool:
    try:
        _a_numero(v)
        return True
    except ValueError:
        return False


def _a_numero(v: str) -> float:
    v = v.strip().replace("%", "")
    if "," in v and "." not in v:
        v = v.replace(",", ".")
    return float(v)


def a_fecha(v: str) -> date | None:
    v = v.strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v[:10], formato).date()
        except ValueError:
            continue
    return None


def partes(v: str) -> list[str]:
    for sep in _SEPARADORES:
        if sep in v:
            return [p.strip() for p in v.split(sep) if p.strip() and p.strip() != "—"]
    return [v.strip()] if v.strip() and v.strip() != "—" else []


def detectar_tipo(nombre: str, valores: list[str]) -> tuple[str, dict]:
    llenos = [v for v in valores if v not in ("", "—")]
    n = len(valores)
    info = {"faltantes": 1 - len(llenos) / n if n else 1.0, "distintos": len(set(llenos))}
    if not llenos or len(llenos) / n < 0.05:
        return "vacia", info
    distintos = set(llenos)
    largo = sum(len(v) for v in llenos) / len(llenos)
    if sum(bool(_CORREO.search(v)) for v in llenos) / len(llenos) >= 0.5:
        return "personal", info
    if {normalizar(v) for v in distintos} <= _BOOLEANOS:
        return "booleano", info
    if sum(a_fecha(v) is not None for v in llenos) / len(llenos) >= 0.9:
        return "fecha", info
    if sum(_es_numero(v) for v in llenos) / len(llenos) >= 0.9:
        return "numero", info
    if sum(bool(_TELEFONO.match(v)) and sum(ch.isdigit() for ch in v) >= 7 for v in llenos) / len(llenos) >= 0.6:
        return "personal", info
    nombre_n = normalizar(nombre)
    if (nombre_n in ("id", "codigo", "uuid") or nombre_n.startswith("id ") or nombre_n.startswith("id_")
            or nombre_n.endswith("_id") or nombre_n.endswith(" id")) and len(distintos) / len(llenos) > 0.9:
        return "identificador", info
    if len(distintos) / len(llenos) >= 0.98 and largo <= 20 and not any(" " in v for v in list(distintos)[:50]):
        return "identificador", info
    con_sep = [v for v in llenos if any(s in v for s in _SEPARADORES)]
    if len(con_sep) / len(llenos) >= 0.2:
        vocab = Counter(p for v in llenos for p in partes(v))
        largo_parte = sum(len(p) for p in vocab) / max(1, len(vocab))
        if len(vocab) <= 40 and largo_parte <= 25:
            return "multicategoria", info
    palabras = sum(len(v.split()) for v in llenos) / len(llenos)
    frases = palabras >= 4 and len(distintos) / len(llenos) > 0.02   # frases variadas: es texto aunque se repitan
    if len(distintos) <= max(20, 0.05 * len(llenos)) and largo <= 40 and not frases:
        return "categoria", info
    return "texto", info


# ---------- Juicios semánticos (JEV) ----------
def preguntas_columna(col: Columna) -> list[PreguntaDinamica]:
    mock_nombre = col.nombre
    # El simulador mira el nombre de la columna y, en los ejemplos, solo patrones de contacto (no palabras sueltas).
    marcas = " ".join(m for m in ("@", "+57", "+52", "+51") if any(m in str(e) for e in col.ejemplos))
    mock_todo = f"{col.nombre} {marcas}"
    return [
        PreguntaDinamica(
            "personal", "noul",
            "Does `columna` contain personal data that identifies a specific person, such as full names, email "
            "addresses, phone numbers, ID numbers or street addresses? Judge `columna.nombre` and `columna.ejemplos`.",
            {"true": "The values identify or contact a specific person.",
             "false": "The values describe roles, opinions, goals, categories or numbers that do not identify anyone."},
            pistas=_MOCK_PERSONAL, mock_texto=mock_todo),
        PreguntaDinamica(
            "derivada", "noul",
            "Is `columna` the output of a previous classification, score or segmentation made by the company (for "
            "example a suggested product, an affinity score, a band or a level of information), rather than "
            "something the person said, did or chose?",
            {"true": "It was computed by the company or a previous model.",
             "false": "It records something the person said, did or chose, or a fact about them."},
            pistas=_MOCK_DERIVADA, mock_texto=mock_nombre),
        PreguntaDinamica(
            "resultado", "noul",
            "Does `columna` record the result of a sales or retention process, for example a sales stage, a won or "
            "lost deal, whether the person bought or booked a demo, or whether a student dropped out or finished?",
            {"true": "It records an outcome or a stage of the process.",
             "false": "It describes the person before the outcome."},
            pistas=_MOCK_RESULTADO, mock_texto=mock_nombre),
    ]


def _estado_columna(col: Columna) -> dict:
    return {"columna": {"nombre": col.nombre, "tipo_detectado": col.tipo, "valores_distintos": col.valores_distintos,
                        "ejemplos": [str(e)[:80] for e in col.ejemplos]}}


def _opciones_columnas(cols: list[Columna], valores: dict[str, list]) -> dict:
    opciones = {f"c{i}": {"nombre": c.nombre, "valores": [str(v)[:60] for v in valores[c.nombre][:8]]} for i, c in enumerate(cols)}
    opciones["ninguna"] = "None of these columns."
    return opciones


def perfilar(filas: list[dict], cliente, dataset: str, resultado: str | None = None, accion: str | None = None,
             valores_positivos: list | None = None) -> Ficha:
    nombres = list(filas[0].keys()) if filas else []
    columnas, tokens = [], 0
    for nombre in nombres:
        valores = [str(f.get(nombre, "") or "") for f in filas]
        tipo, info = detectar_tipo(nombre, valores)
        llenos = [v for v in valores if v not in ("", "—")]
        frec = Counter(p for v in llenos for p in partes(v)) if tipo == "multicategoria" else Counter(llenos)
        ejemplos = list(dict.fromkeys(v[:120] for v in llenos))[:5]
        columnas.append(Columna(nombre, tipo, valores_distintos=info["distintos"], faltantes=round(info["faltantes"], 3),
                                ejemplos=ejemplos, categorias=[k for k, _ in frec.most_common(25)]))

    # Juicios semánticos: una llamada corta por columna (3 preguntas sobre su nombre y ejemplos).
    revisables = [c for c in columnas if c.tipo != "vacia"]
    respuestas = cliente.evaluar_lote([_estado_columna(c) for c in revisables], [preguntas_columna(c) for c in revisables])
    for c, r in zip(revisables, respuestas):
        c.jev = {k: round(v, 3) for k, v in r.nouls.items()}
        tokens += r.tokens_entrada

    for c in columnas:
        if c.tipo == "vacia":
            c.rol, c.motivo = "excluida", "Casi vacía: no aporta."
        elif c.tipo == "personal" or c.jev.get("personal", 0) >= 0.5:
            c.tipo = "personal" if c.tipo in ("texto", "categoria", "identificador") else c.tipo
            c.rol, c.motivo = "excluida", "Datos personales: no aportan a la decisión y nunca se envían a JEV."
        elif c.tipo == "identificador":
            c.rol, c.motivo = "excluida", "Identifica la fila; no describe a la persona."
        elif c.jev.get("derivada", 0) >= 0.5:
            c.rol, c.motivo = "excluida", "Es la salida de una clasificación anterior: usarla copiaría esa regla."

    ficha = Ficha(dataset, len(filas), columnas)
    valores_por_col = {c.nombre: c.categorias or c.ejemplos for c in columnas}

    # Columna de resultado: la elige JEV entre las candidatas (salvo que venga indicada).
    candidatas = [c for c in columnas if c.rol != "excluida" and c.tipo in ("categoria", "booleano") and c.valores_distintos <= 12]
    if resultado is None and candidatas:
        q = PreguntaDinamica(
            "resultado", "choice",
            "Which column records the main outcome of the process: whether the person converted (bought, paid, opened a "
            "sales opportunity or booked a demo) or, in a program, whether the student dropped out? Prefer the column "
            "that states the final result over intermediate stages.",
            _opciones_columnas(candidatas, valores_por_col),
            pistas={"*": _MOCK_RESULTADO + ["compr", "agend", "abandon"], "-": ["etapa", "pipeline"]}, mock_texto="opciones")
        r = cliente.evaluar({"objetivo": "Find the outcome column of this dataset."}, [q])
        tokens += r.tokens_entrada
        elegida = r.choices["resultado"]["valor"]
        if elegida != "ninguna" and r.choices["resultado"]["confianza"] >= 0.2:
            resultado = candidatas[int(elegida[1:])].nombre
    if resultado:
        ficha.resultado = resultado
        col = ficha.col(resultado)
        col.rol, col.motivo = "resultado", "Es el resultado que se quiere predecir."
        valores = col.categorias
        tipo_q = PreguntaDinamica(
            "tipo", "choice", "What does the column `columna` measure?",
            {"conversion": "Whether a person became a customer, opened a sales opportunity, paid or booked a demo.",
             "abandono": "Whether a student dropped out of, paused or finished a program.",
             "otro": "Something else."},
            pistas={"conversion": _MOCK_CONVERSION_SI, "abandono": _MOCK_ABANDONO_SI})
        r = cliente.evaluar({"columna": {"nombre": resultado, "valores": valores}}, [tipo_q])
        tokens += r.tokens_entrada
        ficha.tipo_resultado = r.choices["tipo"]["valor"]
        if valores_positivos is None:
            si, no = ((_MOCK_ABANDONO_SI, _MOCK_ABANDONO_NO) if ficha.tipo_resultado == "abandono"
                      else (_MOCK_CONVERSION_SI, _MOCK_CONVERSION_NO))
            hecho = ("the student dropped out or stopped the program" if ficha.tipo_resultado == "abandono"
                     else "the person converted: bought, paid, opened a sales opportunity or booked a call or demo")
            qs = [PreguntaDinamica(f"v{i}", "noul", f"Does the value `valores[{i}]` of the column `columna` mean that {hecho}?",
                                   pistas=si, pistas_no=no, mock_texto=v) for i, v in enumerate(valores)]
            r = cliente.evaluar({"columna": resultado, "valores": valores}, qs)
            tokens += r.tokens_entrada
            valores_positivos = [v for i, v in enumerate(valores) if r.nouls[f"v{i}"] >= 0.5]
        ficha.valores_positivos = list(valores_positivos)
        ficha.tasa_positiva = round(sum(ficha.positivo(f) for f in filas) / len(filas), 4) if filas else None
        # Otras columnas que registran el resultado (etapas, estados): usarlas sería hacer trampa.
        for c in columnas:
            if c.rol == "rasgo" and c.jev.get("resultado", 0) >= 0.5:
                c.rol, c.motivo = "excluida", "Registra el resultado o una etapa del proceso: usarla sería hacer trampa."

    # Columna de acción (el programa o producto): la elige JEV; su catálogo son todos sus valores.
    candidatas = [c for c in columnas if c.rol == "rasgo" and c.tipo == "categoria"]
    if accion is None and candidatas and ficha.resultado:
        q = PreguntaDinamica(
            "accion", "choice",
            "Which column records the program or product the person bought, enrolled in or was offered in a sales "
            "opportunity?", _opciones_columnas(candidatas, valores_por_col),
            pistas={"*": ["programa", "producto", "plan", "curso"], "-": ["sugerido"]}, mock_texto="opciones")
        r = cliente.evaluar({"objetivo": "Find the column with the program or product."}, [q])
        tokens += r.tokens_entrada
        elegida = r.choices["accion"]["valor"]
        if elegida != "ninguna" and r.choices["accion"]["confianza"] >= 0.2:
            accion = candidatas[int(elegida[1:])].nombre
    if accion:
        ficha.accion = accion
        col = ficha.col(accion)
        col.rol, col.motivo = "accion", "Registra el programa: de aquí se aprende qué ofrecer a cada segmento."
        ficha.acciones = [v for v in col.categorias if v not in ("", "—")]

    if ficha.resultado:
        _marcar_fugas(ficha, filas)
    ficha.tokens_jev = tokens
    return ficha


def _marcar_fugas(ficha: Ficha, filas: list[dict]) -> None:
    """Una columna cuyo valor frecuente implica el resultado casi siempre se llena después de él: es una fuga."""
    y = [ficha.positivo(f) for f in filas]
    base = sum(y) / len(y)
    if not 0.03 < base < 0.97:
        return
    minimo = max(10, 0.05 * len(filas))
    for c in ficha.columnas:
        if c.rol != "rasgo" or c.tipo not in ("categoria", "booleano", "multicategoria"):
            continue
        grupos: dict[str, list[int]] = {}
        for f, yi in zip(filas, y):
            for v in (partes(f.get(c.nombre, "")) if c.tipo == "multicategoria" else [f.get(c.nombre, "")]):
                grupos.setdefault(v, []).append(yi)
        for v, ys in grupos.items():
            if len(ys) >= minimo and v not in ("", "—"):
                tasa = sum(ys) / len(ys)
                if tasa >= 0.995 or tasa <= 0.005:
                    c.rol = "excluida"
                    c.motivo = (f"Fuga: cuando vale «{v}», el resultado es {'sí' if tasa >= 0.995 else 'no'} en el 100 % de "
                                f"{len(ys)} filas. Probablemente se llena después del resultado.")
                    break
