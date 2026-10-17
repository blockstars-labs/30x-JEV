"""Cliente de JEV con dos modos detrás de la misma interfaz.

- live: llama al JEV real con el SDK oficial de TypeSafe (necesita TYPESAFE_API_KEY).
- mock: simula respuestas con la misma forma (probabilidades, confianza) usando coincidencia de
  palabras clave. Sirve para construir y probar el flujo sin llave ni costo; sus métricas NO
  representan el desempeño de JEV.
"""

import hashlib
import json
import math
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.preguntas import PREGUNTAS, Pregunta

PRECIO_USD_POR_MTOK = 0.042  # docs.typesafe.ai/models: solo se cobran tokens de entrada


def cargar_env(ruta: Path = Path(__file__).resolve().parent.parent / ".env") -> None:
    """Carga .env sin dependencias extra. No pisa variables ya definidas."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip())


@dataclass
class RespuestaChoice:
    valor: str
    confianza: float
    probabilidades: dict[str, float]


@dataclass
class RespuestaScore:
    score: float
    confianza: float
    probabilidades: dict[int, float]


@dataclass
class RespuestaJEV:
    modelo: str
    choices: dict[str, RespuestaChoice] = field(default_factory=dict)
    scores: dict[str, RespuestaScore] = field(default_factory=dict)
    nouls: dict[str, float] = field(default_factory=dict)
    tokens_entrada: int = 0
    latencia_ms: float = 0.0

    @property
    def costo_usd(self) -> float:
        return self.tokens_entrada * PRECIO_USD_POR_MTOK / 1_000_000


class JEVLive:
    def __init__(self) -> None:
        from typesafe_sdk import TypeSafeClient
        self._cliente = TypeSafeClient()

    @staticmethod
    def _a_sdk(p: Pregunta):
        from typesafe_sdk import Choice, Noul, Score
        if p.tipo == "choice":
            return Choice(instructions=p.instrucciones, criteria={o.id: o.descripcion for o in p.opciones})
        if p.tipo == "score":
            return Score(instructions=p.instrucciones, criteria=[o.descripcion for o in p.opciones])
        return Noul(instructions=p.instrucciones, criteria={"true": p.criterio_si, "false": p.criterio_no})

    def evaluar(self, estado: dict, preguntas: list[Pregunta] = PREGUNTAS) -> RespuestaJEV:
        inicio = time.perf_counter()
        r = self._cliente.system_one(state=estado, questions={p.id: self._a_sdk(p) for p in preguntas})
        latencia = (time.perf_counter() - inicio) * 1000
        return RespuestaJEV(
            modelo=r.model,
            choices={k: RespuestaChoice(a.choice, a.confidence, dict(a.probabilities)) for k, a in r.choices.items()},
            scores={k: RespuestaScore(a.score, a.confidence, {int(n): v for n, v in a.probabilities.items()})
                    for k, a in r.scores.items()},
            nouls={k: a.noul for k, a in r.nouls.items()},
            tokens_entrada=r.usage.input_tokens or 0,
            latencia_ms=latencia,
        )


class JEVMock:
    """Simulación simple y determinista. No conoce las etiquetas ni las plantillas del generador."""

    SENALES_INVALIDO = ("ignora", "sistema:", "promoción", "seguidores", "asdf", "vip, asígnalo")

    def evaluar(self, estado: dict, preguntas: list[Pregunta] = PREGUNTAS) -> RespuestaJEV:
        texto = json.dumps(estado, ensure_ascii=False).lower()
        semilla = int(hashlib.sha256(texto.encode()).hexdigest()[:8], 16)
        rng = random.Random(semilla)
        resp = RespuestaJEV(modelo="mock")
        mensajes = estado.get("mensajes_posteriores") or []
        for p in preguntas:
            if p.tipo == "noul":
                invalido = any(s in texto for s in self.SENALES_INVALIDO)
                resp.nouls[p.id] = min(max((0.08 if invalido else 0.92) + rng.gauss(0, 0.06), 0.0), 1.0)
                continue
            # Atajo de la simulación para imitar lo que piden las instrucciones: cargo actual para el rol
            # y último mensaje para la intención.
            foco = texto
            if p.id == "rol" and estado.get("cargo_actual"):
                foco = estado["cargo_actual"].lower()
            elif p.tipo == "score" and mensajes:
                foco = mensajes[-1]["texto"].lower()
            puntajes = []
            for o in p.opciones:
                aciertos = sum(1 for c in o.claves_mock if c in foco)
                base = 0.8 if not o.claves_mock else 0.0   # opciones "sin dato"/"ninguno"/"otro"
                puntajes.append(2.2 * aciertos + base + rng.gauss(0, 0.5))
            probs = _softmax(puntajes)
            if p.tipo == "choice":
                ids = [o.id for o in p.opciones]
                top = max(range(len(probs)), key=probs.__getitem__)
                n = len(probs)
                confianza = (probs[top] - 1 / n) / (1 - 1 / n)   # misma fórmula que TypeSafe
                resp.choices[p.id] = RespuestaChoice(ids[top], confianza, dict(zip(ids, probs)))
            else:
                score = sum(i * pr for i, pr in enumerate(probs))
                top = max(range(len(probs)), key=probs.__getitem__)
                dispersion = sum(pr * abs(i - top) for i, pr in enumerate(probs))
                uniforme = sum(abs(i - top) for i in range(len(probs))) / len(probs)
                resp.scores[p.id] = RespuestaScore(score, max(0.0, 1 - dispersion / uniforme),
                                                   dict(enumerate(probs)))
        resp.tokens_entrada = len(preguntas) * len(texto) // 4
        resp.latencia_ms = 70 + rng.random() * 230
        return resp


def _softmax(xs: list[float]) -> list[float]:
    m = max(xs)
    ex = [math.exp(x - m) for x in xs]
    s = sum(ex)
    return [e / s for e in ex]


def crear_cliente(modo: str | None = None):
    cargar_env()
    modo = modo or os.environ.get("JEV_MODO", "mock")
    if modo == "live":
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise RuntimeError("JEV_MODO=live necesita TYPESAFE_API_KEY en .env")
        return JEVLive()
    return JEVMock()
