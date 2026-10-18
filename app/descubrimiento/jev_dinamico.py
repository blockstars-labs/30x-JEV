"""Cliente de JEV para preguntas que se crean en tiempo de ejecución (no las 6 fijas del catálogo).

- live: SDK oficial de TypeSafe, con el modelo fijado (los umbrales se aprenden contra una versión
  concreta; un alias como jev-latest puede moverse sin aviso) y caché en disco: lo que ya se preguntó
  no se vuelve a pagar.
- mock: simulación determinista por palabras clave (`pistas`). Sirve para construir y probar el flujo
  sin llave ni costo; sus métricas NO miden a JEV.

El costo se estima con la forma que muestran los ejemplos de la documentación de TypeSafe: cada
llamada trae una base fija (~270 tokens), el estado se cobra una vez y cada pregunta suma lo suyo.
"""

import hashlib
import json
import math
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from app.descubrimiento.datos import normalizar, sin_tildes
from app.jev import PRECIO_USD_POR_MTOK, cargar_env

RAIZ = Path(__file__).resolve().parents[2]
CACHE = RAIZ / "reportes" / "cache_jev"
BASE_TOKENS = 270      # base fija por llamada (docs.typesafe.ai: 1 Noul corta ≈ 296 tokens de entrada)
TOKENS_POR_PREGUNTA = 25


@dataclass
class PreguntaDinamica:
    id: str
    tipo: str                                  # noul | score | choice
    instrucciones: str | dict
    criterios: dict | list | None = None       # noul: {"true", "false"}; score: [niveles]; choice: {opción: descripción}
    # Solo para el JEV simulado; el JEV real nunca las ve.
    pistas: list | dict | None = None          # noul: [términos]; score: [[términos] por nivel]; choice: {opción: [términos]}
    pistas_no: list | None = None              # noul: si aparece alguno, la respuesta es "no"
    invertida: bool = False                    # noul: "sí" cuando NO aparece ninguna pista (p. ej. perfil genuino)
    foco: list[str] | None = None              # claves del estado donde mira el simulador
    mock_texto: str | None = None              # texto fijo donde mira el simulador (p. ej. una columna)

    def carga(self) -> dict:
        """La pregunta tal como viaja a la API (sin campos del simulador)."""
        p = {"type": self.tipo, "instructions": self.instrucciones}
        if self.criterios is not None:
            p["criteria"] = self.criterios
        return p


@dataclass
class RespuestaDinamica:
    modelo: str
    nouls: dict[str, float] = field(default_factory=dict)
    scores: dict[str, dict] = field(default_factory=dict)    # {score, confianza, probabilidades{nivel: p}}
    choices: dict[str, dict] = field(default_factory=dict)   # {valor, confianza, probabilidades{opción: p}}
    tokens_entrada: int = 0
    latencia_ms: float = 0.0
    desde_cache: bool = False

    @property
    def costo_usd(self) -> float:
        return self.tokens_entrada * PRECIO_USD_POR_MTOK / 1_000_000

    def a_dict(self) -> dict:
        return {"modelo": self.modelo, "nouls": self.nouls, "scores": self.scores, "choices": self.choices,
                "tokens_entrada": self.tokens_entrada, "latencia_ms": self.latencia_ms}

    @classmethod
    def desde_dict(cls, d: dict, desde_cache: bool = False) -> "RespuestaDinamica":
        scores = {k: {**v, "probabilidades": {int(i): p for i, p in v["probabilidades"].items()}} for k, v in d["scores"].items()}
        return cls(d["modelo"], d["nouls"], scores, d["choices"], d["tokens_entrada"], d["latencia_ms"], desde_cache)


def estimar_tokens(estado, preguntas: list[PreguntaDinamica]) -> int:
    """Estimación de tokens de entrada de una llamada (≈ 4 caracteres por token)."""
    texto_estado = len(json.dumps(estado, ensure_ascii=False)) / 4
    texto_preguntas = sum(len(json.dumps(p.carga(), ensure_ascii=False)) / 4 + TOKENS_POR_PREGUNTA for p in preguntas)
    return int(BASE_TOKENS + texto_estado + texto_preguntas)


def confianza_choice(probs: list[float]) -> float:
    n = len(probs)
    return (max(probs) - 1 / n) / (1 - 1 / n) if n > 1 else 1.0


def confianza_score(probs: list[float]) -> float:
    n = len(probs)
    m = probs.index(max(probs))
    dispersion = sum(p * abs(i - m) for i, p in enumerate(probs))
    uniforme = sum(abs(i - (n - 1) / 2) for i in range(n)) / n
    return max(0.0, 1 - dispersion / uniforme) if uniforme else 1.0


def _softmax(xs: list[float]) -> list[float]:
    m = max(xs)
    ex = [math.exp(x - m) for x in xs]
    s = sum(ex)
    return [e / s for e in ex]


def coincide(pista: str, texto: str) -> bool:
    """Pista del simulador: '=valor' exige el texto completo; varias palabras deben aparecer todas (en
    cualquier orden); una sola palabra basta con que aparezca."""
    if pista.startswith("="):
        return texto.strip() == normalizar(pista[1:])
    crudo = sin_tildes(pista).lower()          # sin strip: " and " no debe coincidir dentro de "buscando"
    if crudo.strip() != crudo:
        return crudo in texto
    if " " in crudo:
        return all(p in texto for p in crudo.split())
    return crudo in texto


def _aciertos(pistas, texto: str) -> int:
    return sum(coincide(t, texto) for t in pistas or [])


_NINGUNO = ("ninguno", "ninguna", "none", "other", "otro")


class _Base:
    modo = "mock"
    modelo = "mock"

    def evaluar(self, estado, preguntas: list[PreguntaDinamica]) -> RespuestaDinamica:
        raise NotImplementedError

    def evaluar_lote(self, estados: list, preguntas: list[PreguntaDinamica] | list[list[PreguntaDinamica]]) -> list[RespuestaDinamica]:
        """Una llamada por estado. `preguntas` puede ser la misma lista para todos o una lista por estado."""
        por_estado = preguntas if preguntas and isinstance(preguntas[0], list) else [preguntas] * len(estados)
        return [self.evaluar(e, q) for e, q in zip(estados, por_estado)]


class JEVDinamicoMock(_Base):
    """Simulación determinista: busca las pistas de cada pregunta en el texto del estado."""

    def evaluar(self, estado, preguntas: list[PreguntaDinamica]) -> RespuestaDinamica:
        crudo = json.dumps(estado, ensure_ascii=False, sort_keys=True)
        resp = RespuestaDinamica(modelo="mock")
        for p in preguntas:
            rng = random.Random(int(hashlib.sha256(f"{crudo}|{p.id}".encode()).hexdigest()[:12], 16))
            texto = self._texto(estado, p)
            if p.tipo == "noul":
                resp.nouls[p.id] = self._noul(p, texto, rng)
            elif p.tipo == "score":
                niveles = p.pistas or [[] for _ in (p.criterios or [0, 1])]
                puntajes = [2.2 * _aciertos(nivel, texto) + (0.8 if not nivel else 0.0) + rng.gauss(0, 0.4)
                            for nivel in niveles]
                probs = _softmax(puntajes)
                resp.scores[p.id] = {"score": sum(i * x for i, x in enumerate(probs)), "confianza": confianza_score(probs),
                                     "probabilidades": dict(enumerate(probs))}
            else:
                opciones = list((p.criterios or {}).keys())
                pistas = p.pistas or {}
                puntajes = []
                # "Ninguno" gana con fuerza solo cuando ninguna otra opción tiene pistas en el texto (como el JEV real).
                hay_aciertos = any(_aciertos(pistas.get(o, []), texto) for o in opciones if o not in _NINGUNO)
                for o in opciones:
                    if o in _NINGUNO and p.mock_texto != "opciones" and not pistas.get(o):
                        puntajes.append((0.0 if hay_aciertos else 3.0) + rng.gauss(0, 0.4))
                        continue
                    terminos = pistas.get(o, [])
                    if p.mock_texto == "opciones":
                        # Elegir entre columnas o grupos: se compara la descripción de cada opción con las pistas globales;
                        # "ninguna" gana cuando ninguna opción coincide.
                        desc = normalizar(json.dumps(p.criterios[o], ensure_ascii=False))
                        aciertos = _aciertos(pistas.get("*"), desc) - _aciertos(pistas.get("-"), desc)
                        base = 1.0 if o in ("ninguna", "ninguno", "otro") else 0.0
                    else:
                        aciertos = _aciertos(terminos, texto)
                        base = 0.8 if not terminos else 0.0
                    puntajes.append(2.2 * aciertos + base + rng.gauss(0, 0.4))
                probs = _softmax(puntajes) if opciones else []
                if opciones:
                    top = max(range(len(probs)), key=probs.__getitem__)
                    resp.choices[p.id] = {"valor": opciones[top], "confianza": confianza_choice(probs),
                                          "probabilidades": dict(zip(opciones, probs))}
        rng = random.Random(len(crudo))
        resp.tokens_entrada = estimar_tokens(estado, preguntas)
        resp.latencia_ms = 70 + rng.random() * 230
        return resp

    @staticmethod
    def _texto(estado, p: PreguntaDinamica) -> str:
        if p.mock_texto and p.mock_texto != "opciones":
            return normalizar(p.mock_texto)
        if p.foco and isinstance(estado, dict):
            return normalizar(" ".join(json.dumps(estado.get(k, ""), ensure_ascii=False) for k in p.foco))
        return normalizar(json.dumps(estado, ensure_ascii=False))

    @staticmethod
    def _noul(p: PreguntaDinamica, texto: str, rng: random.Random) -> float:
        if p.pistas_no and _aciertos(p.pistas_no, texto):
            base = 0.07
        elif p.pistas:
            aciertos = _aciertos(p.pistas, texto)
            si = (aciertos == 0) if p.invertida else aciertos > 0
            base = (0.86 + 0.04 * min(aciertos, 2)) if si and not p.invertida else (0.9 if si else 0.08)
        else:
            base = 0.5
        # La repetición con otro `uid` (prueba de consistencia) mueve la respuesta un poco, como el JEV real.
        return min(max(base + rng.gauss(0, 0.05), 0.0), 1.0)


class JEVDinamicoLive(_Base):
    modo = "live"

    def __init__(self, modelo: str, trabajadores: int = 4, cache: Path = CACHE) -> None:
        from typesafe_sdk import TypeSafeClient  # noqa: F401  (falla aquí si el SDK no está instalado)
        self.modelo = modelo
        self.trabajadores = trabajadores
        self.cache = cache
        self._local = threading.local()

    def _cliente(self):
        if not hasattr(self._local, "c"):
            from typesafe_sdk import TypeSafeClient
            self._local.c = TypeSafeClient(model=self.modelo)
        return self._local.c

    @staticmethod
    def _a_sdk(p: PreguntaDinamica):
        from typesafe_sdk import Choice, Noul, NoulCriteria, Score
        if p.tipo == "choice":
            return Choice(instructions=p.instrucciones, criteria=p.criterios)
        if p.tipo == "score":
            return Score(instructions=p.instrucciones, criteria=p.criterios)
        criterios = NoulCriteria(true=p.criterios["true"], false=p.criterios["false"]) if p.criterios else None
        return Noul(instructions=p.instrucciones, criteria=criterios)

    def _clave(self, estado, preguntas) -> str:
        cuerpo = json.dumps([self.modelo, estado, [(p.id, p.carga()) for p in preguntas]], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(cuerpo.encode()).hexdigest()

    def evaluar(self, estado, preguntas: list[PreguntaDinamica]) -> RespuestaDinamica:
        clave = self._clave(estado, preguntas)
        ruta = self.cache / clave[:2] / f"{clave}.json"
        if ruta.exists():
            return RespuestaDinamica.desde_dict(json.loads(ruta.read_text(encoding="utf-8")), desde_cache=True)
        inicio = time.perf_counter()
        r = self._cliente().system_one(state=estado, questions={p.id: self._a_sdk(p) for p in preguntas}, model=self.modelo)
        resp = RespuestaDinamica(
            modelo=r.model,
            nouls={k: a.noul for k, a in r.nouls.items()},
            scores={k: {"score": a.score, "confianza": a.confidence,
                        "probabilidades": {int(n): v for n, v in a.probabilities.items()}}
                    for k, a in r.scores.items()},
            choices={k: {"valor": a.choice, "confianza": a.confidence, "probabilidades": dict(a.probabilities)}
                     for k, a in r.choices.items()},
            tokens_entrada=r.usage.input_tokens or 0,
            latencia_ms=(time.perf_counter() - inicio) * 1000,
        )
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(resp.a_dict(), ensure_ascii=False), encoding="utf-8")
        return resp

    def evaluar_lote(self, estados, preguntas):
        por_estado = preguntas if preguntas and isinstance(preguntas[0], list) else [preguntas] * len(estados)
        with ThreadPoolExecutor(max_workers=self.trabajadores) as pool:
            return list(pool.map(lambda par: self.evaluar(*par), zip(estados, por_estado)))


def crear_cliente_dinamico(modo: str | None = None, modelo: str = "jev-1.13.0", trabajadores: int = 4):
    cargar_env()
    modo = modo or os.environ.get("JEV_MODO", "mock")
    if modo == "live":
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise RuntimeError("JEV_MODO=live necesita TYPESAFE_API_KEY en .env")
        return JEVDinamicoLive(modelo, trabajadores)
    return JEVDinamicoMock()
