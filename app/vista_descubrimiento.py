"""Estado del descubrimiento y de las alertas para la vista (app/servidor.py).

En modo simulado todo se calcula solo al primer pedido (unos segundos, costo cero). Con JEV real, el reporte de
clusterización dinámica se genera solo cuando alguien lo pide desde la vista, después de ver el costo estimado.
Lo calculado se guarda en reportes/descubrimiento/ y no se vuelve a pagar.
"""

import json
import shutil
import threading
from pathlib import Path

from app.alertas import cargar_registros, construir_filas, entrenar, generar_alertas
from app.descubrimiento.asignar import Segmentador
from app.descubrimiento.datos import leer_dataset
from app.descubrimiento.jev_dinamico import crear_cliente_dinamico
from app.descubrimiento.pipeline import cargar_config, descubrir, recalcular
from app.descubrimiento.reporte import ciclo_dinamico, markdown, resumen
from app.descubrimiento.versiones import cargar as cargar_version

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "data" / "descubrimiento"
REPORTES = RAIZ / "reportes" / "descubrimiento"


class EstadoDescubrimiento:
    def __init__(self, llm=None):
        self.cfg = cargar_config()
        self.cliente = crear_cliente_dinamico(modelo=self.cfg["modelo_jev"], trabajadores=self.cfg["trabajadores"])
        self.modo = self.cliente.modo
        self.llm = llm if llm is not None and llm.__class__.__name__ == "LLMLive" else None
        self.candado = threading.Lock()
        self.reporte: dict | None = None
        self.webinar: dict | None = None
        self.actual: dict | None = None        # versión vigente (la v2 del ciclo), con riesgo y vetos aplicados
        self._alertas: dict | None = None
        self._cargar_guardado()

    # ---------- Reporte de clusterización dinámica ----------
    def _ruta(self, nombre: str) -> Path:
        return REPORTES / f"{nombre}_{self.modo}.json"

    def _cargar_guardado(self) -> None:
        r = self._ruta("reporte_dinamico")
        if r.exists():
            datos = json.loads(r.read_text(encoding="utf-8"))
            self.reporte, self.webinar = datos["reporte"], datos["webinar"]
            v = self._ruta("version_actual")
            # La versión vigente (con riesgo y vetos aplicados); si no está, la v2 tal como salió del descubrimiento.
            self.actual = (json.loads(v.read_text(encoding="utf-8")) if v.exists()
                           else cargar_version("inscripciones_eventos", 2, base=REPORTES / self.modo))

    def estimar(self) -> dict:
        """Costo estimado de generar el reporte con JEV real (dos descubrimientos, el webinar y los lotes)."""
        modelo = self.cfg["modelo_llm"]
        jev = 0.06 * 3 + 0.01
        llm = 0.0 if self.llm is None else 3 * 0.19 if "opus" in modelo else 3 * 0.01
        return {"jev_usd": round(jev, 2), "llm_usd": round(llm, 2), "total_usd": round(jev + llm, 2), "modelo_llm": modelo if self.llm else None}

    def generar(self, forzar: bool = False) -> dict:
        with self.candado:
            if self.reporte and not forzar:
                return self.estado()
            carpeta = REPORTES / self.modo
            shutil.rmtree(carpeta, ignore_errors=True)
            a = leer_dataset(DATOS / "inscripciones_eventos.csv")
            lote = leer_dataset(DATOS / "inscripciones_eventos_lote2.csv")
            rep = ciclo_dinamico(a, lote, "inscripciones_eventos", self.cliente, self.cfg, self.llm, guardar_en=carpeta)
            v1, v2 = rep.pop("_versiones")
            web = descubrir(leer_dataset(DATOS / "registro_webinar.csv"), "registro_webinar", self.cliente, self.llm, self.cfg)
            self.reporte, self.webinar, self.actual = rep, resumen(web), v2
            REPORTES.mkdir(parents=True, exist_ok=True)
            self._ruta("reporte_dinamico").write_text(json.dumps({"reporte": rep, "webinar": self.webinar}, ensure_ascii=False, default=float),
                                                      encoding="utf-8")
            self._guardar_actual()
            return self.estado()

    def _guardar_actual(self) -> None:
        self._ruta("version_actual").write_text(json.dumps(self.actual, ensure_ascii=False, default=float), encoding="utf-8")

    def estado(self) -> dict:
        if not self.reporte:
            return {"modo": self.modo, "listo": False, "estimado": self.estimar()}
        return {"modo": self.modo, "listo": True, "reporte": self.reporte, "webinar": self.webinar,
                "actual": resumen(self.actual) if self.actual else self.reporte["v2"], "campos": self.campos_formulario()}

    def asegurar(self) -> dict:
        """En modo simulado genera solo; con JEV real espera a que lo pidan (cuesta dinero)."""
        if not self.reporte and self.modo == "mock":
            return self.generar()
        return self.estado()

    # ---------- Ajustes sin llamar a JEV ----------
    def ajustar(self, riesgo: str | None = None, vetar: dict | None = None, quitar_vetos: bool = False) -> dict:
        with self.candado:
            if not self.actual:
                raise ValueError("Primero hay que generar el descubrimiento.")
            vetos = {"variables": [], "segmentos": []} if quitar_vetos else json.loads(json.dumps(self.actual.get("vetos") or
                                                                                            {"variables": [], "segmentos": []}))
            if vetar:
                lista = vetos["variables" if vetar.get("tipo") == "variable" else "segmentos"]
                if vetar.get("id") and vetar["id"] not in lista:
                    lista.append(vetar["id"])
            if riesgo and riesgo not in self.cfg["niveles_riesgo"]:
                raise ValueError("Riesgo desconocido.")
            self.actual = recalcular(self.actual, self.cfg, riesgo=riesgo or self.actual["riesgo"], vetos=vetos)
            self._guardar_actual()
        return self.estado()

    # ---------- Asignación en vivo ----------
    def campos_formulario(self) -> list[dict]:
        if not self.actual:
            return []
        campos = []
        for c in self.actual["ficha"]["columnas"]:
            if c["rol"] == "rasgo" and c["tipo"] in ("texto", "categoria", "multicategoria", "numero", "booleano"):
                campos.append({"nombre": c["nombre"], "tipo": c["tipo"], "opciones": c["categorias"][:12] if c["tipo"] in ("categoria", "multicategoria") else []})
        return campos

    def asignar(self, fila: dict) -> dict:
        if not self.actual:
            raise ValueError("Primero hay que generar el descubrimiento.")
        if not any(str(v).strip() for v in fila.values()):
            raise ValueError("Escribe al menos un campo.")
        r = Segmentador(self.actual, self.cliente).asignar({k: str(v) for k, v in fila.items()})
        r.pop("vector", None)
        return r

    # ---------- Alertas de riesgo ----------
    def alertas(self, cliente_guardrail, politica) -> dict:
        with self.candado:
            if self._alertas is None:
                r = self._ruta("alertas")
                if r.exists():
                    self._alertas = json.loads(r.read_text(encoding="utf-8"))
                else:
                    filas = construir_filas(cargar_registros())
                    version = entrenar(filas, self.cliente, self.llm, self.cfg)
                    actuales = [f for f in filas if not f["estado_final"]]
                    datos = generar_alertas(version, actuales, self.cliente, cliente_guardrail, politica)
                    datos["entrenamiento"] = {"alumnos": sum(1 for f in filas if f["estado_final"]),
                                              "costo_usd": version["costo"]["total_usd"], "segundos": version.get("segundos")}
                    datos["modo"] = self.modo
                    REPORTES.mkdir(parents=True, exist_ok=True)
                    r.write_text(json.dumps(datos, ensure_ascii=False, default=float), encoding="utf-8")
                    self._alertas = datos
            return self._alertas

    def markdown(self) -> str:
        if not self.reporte:
            raise ValueError("Todavía no hay reporte.")
        return markdown(self.reporte, self.webinar)
