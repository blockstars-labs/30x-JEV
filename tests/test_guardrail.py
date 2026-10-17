from app.guardrail import revisar_mensaje
from app.jev import RespuestaJEV
from app.politica import cargar_politica

POL = cargar_politica()
CONTEXTO = {"programa": "Sales Machine", "lo_que_dijo_la_persona": "Quiero vender más"}
SEGURO = {"promesas": 0.05, "tono": 0.95, "coherencia": 0.9, "instrucciones": 0.03}


class JEVFijo:
    def __init__(self, **nouls):
        self.nouls = {**SEGURO, **nouls}
        self.estados = []

    def evaluar(self, estado, preguntas):
        self.estados.append(estado)
        return RespuestaJEV(modelo="fijo", nouls=dict(self.nouls), latencia_ms=100.0)


def test_mensaje_correcto_se_aprueba():
    r = revisar_mensaje("Hola, ¿te gustaría conocer Sales Machine?", CONTEXTO, JEVFijo(), POL)
    assert r["estado"] == "aprobado" and r["razones"] == []


def test_promesa_sin_respaldo_se_bloquea():
    r = revisar_mensaje("40% de descuento hasta el viernes", CONTEXTO, JEVFijo(promesas=0.9), POL)
    assert r["estado"] == "bloqueado"


def test_datos_de_contacto_se_bloquean_en_codigo():
    r = revisar_mensaje("Escríbeme a ana@example.com", CONTEXTO, JEVFijo(), POL)
    assert r["estado"] == "bloqueado"
    assert any("código" in x for x in r["razones"])


def test_tono_dudoso_va_a_revision():
    r = revisar_mensaje("¡Decide ya!", CONTEXTO, JEVFijo(tono=0.3), POL)
    assert r["estado"] == "revision"


def test_jev_recibe_el_mensaje_y_el_contexto():
    cliente = JEVFijo()
    revisar_mensaje("Hola", CONTEXTO, cliente, POL)
    assert cliente.estados == [{"mensaje": "Hola", "contexto": CONTEXTO}]
