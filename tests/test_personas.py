from datetime import date, timedelta

from app.jev import RespuestaChoice, RespuestaJEV, RespuestaScore
from app.personas import aplicar_evento, compromiso, crear_persona, reevaluar
from app.politica import cargar_politica

POL = cargar_politica()
HOY = date(2026, 8, 1)
PERFIL = {"id": "T-1", "canal": "formulario_luma", "temas": ["sales"],
          "entrada": {"cargo": "CEO", "que_te_gustaria_lograr": "Vender más"}}


class JEVFijo:
    """Cliente de prueba: devuelve la intención que se le indique y cuenta las llamadas."""

    def __init__(self):
        self.llamadas = 0
        self.nivel_intencion = 1

    def evaluar(self, estado):
        self.llamadas += 1
        probs = {i: 0.02 for i in range(4)}
        probs[self.nivel_intencion] = 0.94
        choice = lambda v: RespuestaChoice(v, 0.95, {v: 0.96, "otro": 0.04})  # noqa: E731
        return RespuestaJEV(
            modelo="fijo",
            choices={"rol": choice("fundador"), "dolor": choice("ninguno"), "objetivo": choice("vender_mas")},
            scores={"intencion": RespuestaScore(float(self.nivel_intencion), 0.9, probs)},
            nouls={"perfil_valido": 0.97},
            tokens_entrada=100,
        )


def test_compromiso_sube_con_asistencias_recientes():
    p = crear_persona(PERFIL, HOY)
    assert compromiso(p, HOY, POL)[0] == "medio"
    aplicar_evento(p, {"tipo": "asistio_evento", "fecha": HOY + timedelta(days=5), "evento": "Webinar"})
    aplicar_evento(p, {"tipo": "asistio_evento", "fecha": HOY + timedelta(days=10), "evento": "Taller"})
    assert compromiso(p, HOY + timedelta(days=12), POL)[0] == "alto"
    assert compromiso(p, HOY + timedelta(days=200), POL)[0] == "bajo"


def test_asistencia_recalcula_sin_llamar_a_jev():
    cliente = JEVFijo()
    p = crear_persona(PERFIL, HOY)
    reevaluar(p, HOY, cliente, {"tipo": "inscripcion"}, POL)
    evento = {"tipo": "asistio_evento", "fecha": HOY + timedelta(days=3), "evento": "Webinar"}
    aplicar_evento(p, evento)
    r = reevaluar(p, evento["fecha"], cliente, evento, POL)
    assert cliente.llamadas == 1
    assert r["llamo_jev"] is False


def test_inferencia_vencida_vuelve_a_llamar_a_jev():
    cliente = JEVFijo()
    p = crear_persona(PERFIL, HOY)
    reevaluar(p, HOY, cliente, {"tipo": "inscripcion"}, POL)
    evento = {"tipo": "asistio_evento", "fecha": HOY + timedelta(days=45), "evento": "Webinar"}
    aplicar_evento(p, evento)
    r = reevaluar(p, evento["fecha"], cliente, evento, POL)
    assert cliente.llamadas == 2
    assert r["inferencia_vencida"] is True


def test_correo_con_intencion_de_compra_cambia_el_segmento():
    cliente = JEVFijo()
    p = crear_persona(PERFIL, HOY)
    reevaluar(p, HOY, cliente, {"tipo": "inscripcion"}, POL)
    assert p.decision.accion == "nutrir_programa"

    cliente.nivel_intencion = 3
    evento = {"tipo": "respondio_correo", "fecha": HOY + timedelta(days=7), "texto": "¿Cuánto cuesta?"}
    aplicar_evento(p, evento)
    r = reevaluar(p, evento["fecha"], cliente, evento, POL)
    assert r["cambio_segmento"] is True
    assert p.decision.accion == "pasar_a_ventas"
    assert any(c.startswith("intención") for c in r["cambios"])
    assert len(p.historial) == 2
