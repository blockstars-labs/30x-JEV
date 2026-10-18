"""Fase 8 · Versiones, deriva y redescubrimiento: los segmentos también cambian, no solo las personas.

- Cada descubrimiento se guarda como una versión (reportes/descubrimiento/<dataset>/v001.json, ...).
- El monitor de deriva mira las asignaciones recientes y avisa cuando sube la gente que no se parece a ningún
  segmento, la que llega con baja confianza o cuando cambia el tamaño de un segmento. Los márgenes salen de la
  variación esperada de la línea base (no se fijan a mano), con un mínimo configurable.
- Al redescubrir, la comparación entre versiones dice en palabras qué cambió: segmentos que aparecen, que se
  unen, que se dividen o que desaparecen, y cuántas personas cambiaron de segmento.
"""

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

RAIZ = Path(__file__).resolve().parents[2]
CARPETA = RAIZ / "reportes" / "descubrimiento"


def _carpeta(dataset: str, base: Path = CARPETA) -> Path:
    return base / dataset


def guardar(version: dict, base: Path = CARPETA) -> dict:
    carpeta = _carpeta(version["dataset"], base)
    carpeta.mkdir(parents=True, exist_ok=True)
    existentes = sorted(carpeta.glob("v*.json"))
    version["version"] = int(existentes[-1].stem[1:]) + 1 if existentes else 1
    (carpeta / f"v{version['version']:03d}.json").write_text(json.dumps(version, ensure_ascii=False, default=float), encoding="utf-8")
    return version


def cargar(dataset: str, numero: int | None = None, base: Path = CARPETA) -> dict | None:
    carpeta = _carpeta(dataset, base)
    archivos = sorted(carpeta.glob("v*.json"))
    if not archivos:
        return None
    ruta = carpeta / f"v{numero:03d}.json" if numero else archivos[-1]
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def listar(dataset: str, base: Path = CARPETA) -> list[dict]:
    salida = []
    for ruta in sorted(_carpeta(dataset, base).glob("v*.json")):
        v = json.loads(ruta.read_text(encoding="utf-8"))
        salida.append({"version": v["version"], "fecha": v["fecha"], "padre": v.get("padre"), "segmentos": len(v["segmentos"]),
                       "riesgo": v["riesgo"], "vetos": v.get("vetos"), "modo": v.get("modo"), "motivo": v.get("motivo", "")})
    return salida


# ---------- Comparación entre versiones ----------
def comparar(anterior: dict, nueva: dict, asig_anterior: dict[str, str], asig_nueva: dict[str, str],
             recientes: set[str] | None = None) -> dict:
    """Qué cambió entre dos segmentaciones, medido sobre las personas que ambas asignaron.

    `recientes`: personas que llegaron después de la versión anterior. Un segmento formado sobre todo por
    ellas es un segmento que apareció, aunque la versión anterior las hubiera metido en otro.
    """
    recientes = recientes or set()
    comunes = [i for i in asig_nueva if i in asig_anterior]
    nombres_a = {s["id"]: s["nombre"] for s in anterior["segmentos"]}
    nombres_n = {s["id"]: s["nombre"] for s in nueva["segmentos"]}
    ids_a, ids_n = list(nombres_a), list(nombres_n)
    tabla = np.zeros((len(ids_a), len(ids_n)))
    for i in comunes:
        tabla[ids_a.index(asig_anterior[i]), ids_n.index(asig_nueva[i])] += 1
    cambios, flujos = [], []
    if not comunes:
        return {"comunes": 0, "cambios": ["No hay personas en común para comparar."], "flujos": [], "movidas": 0}
    filas, cols = linear_sum_assignment(-tabla)
    pareja = {ids_a[a]: ids_n[b] for a, b in zip(filas, cols) if tabla[a, b] > 0}
    for a, sa in enumerate(ids_a):
        for b, sb in enumerate(ids_n):
            if tabla[a, b]:
                flujos.append({"de": sa, "de_nombre": nombres_a[sa], "a": sb, "a_nombre": nombres_n[sb], "n": int(tabla[a, b])})
    total = tabla.sum()
    por_nuevo = tabla.sum(axis=0)
    por_anterior = tabla.sum(axis=1)
    seg_n = {s["id"]: s for s in nueva["segmentos"]}
    seg_a = {s["id"]: s for s in anterior["segmentos"]}
    aparecidos = set()
    for b, sb in enumerate(ids_n):
        if por_nuevo[b] == 0:
            continue
        origen = tabla[:, b] / por_nuevo[b]
        fuentes = [ids_a[a] for a in np.argsort(-origen) if origen[a] >= 0.3]
        miembros = [i for i in comunes if asig_nueva[i] == sb]
        cuota_reciente = sum(i in recientes for i in miembros) / len(miembros) if miembros else 0.0
        tasa = f", que convierte el {seg_n[sb]['tasa']:.0%}" if seg_n[sb].get("tasa") is not None else ""
        if recientes and cuota_reciente >= 0.6:
            de_donde = " y ".join(f"«{nombres_a[f]}»" for f in fuentes) or "otros segmentos"
            cambios.append({"tipo": "aparecio", "segmento": sb,
                            "texto": f"Apareció «{nombres_n[sb]}» ({seg_n[sb]['proporcion']:.0%} de las personas{tasa}): el "
                                     f"{cuota_reciente:.0%} llegó en el último lote. Antes los habría puesto en {de_donde}."})
            aparecidos.add(sb)
        elif origen.max() < 0.5 and len(fuentes) <= 1:
            cambios.append({"tipo": "aparecio", "segmento": sb,
                            "texto": f"Apareció «{nombres_n[sb]}» ({seg_n[sb]['proporcion']:.0%} de las personas{tasa}): "
                                     "antes estas personas estaban repartidas en otros segmentos."})
            aparecidos.add(sb)
        elif len(fuentes) >= 2 and sb not in aparecidos:
            cambios.append({"tipo": "se_unieron", "segmento": sb,
                            "texto": " y ".join(f"«{nombres_a[f]}»" for f in fuentes) + f" ahora son un solo segmento: «{nombres_n[sb]}»."})
    for a, sa in enumerate(ids_a):
        if por_anterior[a] == 0:
            continue
        destino = tabla[a] / por_anterior[a]
        grandes = [ids_n[b] for b in np.argsort(-destino) if destino[b] >= 0.3]
        if len(grandes) >= 2:
            cambios.append({"tipo": "se_dividio", "segmento": sa,
                            "texto": f"«{nombres_a[sa]}» se dividió en " + " y ".join(f"«{nombres_n[g]}»" for g in grandes) + "."})
        elif destino.max() < 0.3:
            cambios.append({"tipo": "desaparecio", "segmento": sa, "texto": f"«{nombres_a[sa]}» ya no existe: sus personas se repartieron."})
    for sa, sb in pareja.items():
        antes, ahora = seg_a[sa]["proporcion"], seg_n[sb]["proporcion"]
        if abs(ahora - antes) >= 0.05:
            cambios.append({"tipo": "tamano", "segmento": sb,
                            "texto": f"«{nombres_n[sb]}» pasó del {antes:.0%} al {ahora:.0%} de las personas."})
    movidas = sum(1 for i in comunes if pareja.get(asig_anterior[i]) != asig_nueva[i])
    cambios.append({"tipo": "movidas", "segmento": None,
                    "texto": f"{movidas} de {len(comunes)} personas ({movidas / len(comunes):.0%}) cambiaron de segmento."})
    return {"comunes": len(comunes), "cambios": cambios, "flujos": flujos, "movidas": movidas, "pareja": pareja}


# ---------- Deriva ----------
class MonitorDeDeriva:
    def __init__(self, version: dict, cfg: dict):
        self.version = version
        self.cfg = cfg["deriva"]
        base = version["linea_base"]
        self.base_baja = base.get("baja_confianza", 0.0)
        self.base_ninguno = base.get("ninguno", 0.0)
        self.base_proporciones = base["proporciones"]
        self.nombres = {s["id"]: s["nombre"] for s in version["segmentos"]}
        self.recientes: list[dict] = []

    def registrar(self, asignacion: dict) -> None:
        if asignacion["ruta"] == "revision_humana":   # el spam no cuenta como deriva
            return
        self.recientes.append(asignacion)
        self.recientes = self.recientes[-self.cfg["ventana"]:]

    def _margen(self, p0: float, n: int) -> float:
        return max(self.cfg["margen_min"], 3 * math.sqrt(max(p0 * (1 - p0), 1e-4) / max(n, 1)))

    def estado(self) -> dict:
        n = len(self.recientes)
        if n < 30:
            return {"n": n, "redescubrir": False, "alertas": [], "senales": {}}
        ninguno = sum(a["ninguno"] >= 0.6 for a in self.recientes) / n
        baja = sum(a["confianza"] < self.version["umbrales"]["asignacion"]["elegido"]["umbral"] for a in self.recientes) / n
        proporciones = {sid: c / n for sid, c in Counter(a["segmento"] for a in self.recientes).items()}
        alertas = []
        m_ninguno = self._margen(self.base_ninguno, n)
        if ninguno - self.base_ninguno >= m_ninguno:
            alertas.append(f"El {ninguno:.0%} de las personas recientes no se parece a ningún segmento (antes, el {self.base_ninguno:.0%}).")
        m_baja = self._margen(self.base_baja, n)
        if baja - self.base_baja >= m_baja:
            alertas.append(f"El {baja:.0%} llega con baja confianza de segmento (antes, el {self.base_baja:.0%}).")
        for sid, p0 in self.base_proporciones.items():
            p = proporciones.get(sid, 0.0)
            if abs(p - p0) >= self.cfg["cambio_proporcion"]:
                alertas.append(f"«{self.nombres[sid]}» pasó del {p0:.0%} al {p:.0%} de las personas recientes.")
        return {"n": n, "redescubrir": bool(alertas), "alertas": alertas,
                "senales": {"ninguno": round(ninguno, 3), "base_ninguno": self.base_ninguno, "margen_ninguno": round(m_ninguno, 3),
                            "baja_confianza": round(baja, 3), "base_baja_confianza": self.base_baja, "margen_baja": round(m_baja, 3),
                            "proporciones": {k: round(v, 3) for k, v in proporciones.items()}}}
