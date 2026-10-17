from app.llm import Revision
from app.motor import resolver_con_llm
from app.politica import Juicio, Juicios, cargar_politica, decidir

POL = cargar_politica()
ESTADO = {"canal": "formulario_luma", "inscripcion": {"cargo": "CEO"}}


class LLMFijo:
    """LLM de prueba: responde la elección indicada y cuenta las llamadas."""

    def __init__(self, eleccion):
        self.eleccion = eleccion
        self.llamadas = 0

    def revisar(self, estado, campo, pregunta, candidatos, probs):
        self.llamadas += 1
        return Revision(campo, self.eleccion, "porque lo dice el texto")


def juicios_con_duda_en_objetivo(p_listo=0.0, valido=0.95):
    probs_int = {0: 0.0, 1: 0.0, 2: 1 - p_listo, 3: p_listo}
    return Juicios(
        rol=Juicio("fundador", 0.95, {"fundador": 0.96, "sin_dato": 0.04}),
        dolor=Juicio("ninguno", 0.95, {"ninguno": 0.96, "capital": 0.04}),
        objetivo=Juicio("vender_mas", 0.2, {"vender_mas": 0.4, "expandirse": 0.35, "otro": 0.25}),
        intencion_esperada=2.0 + p_listo, intencion_probabilidades=probs_int, perfil_valido=valido)


def test_llm_resuelve_la_duda_y_actua_solo():
    j = juicios_con_duda_en_objetivo()
    d = decidir(j, ["sales"], POL)
    assert d.ruta == "revision_humana" and d.dudas == ["objetivo"]
    j2, d2, revs = resolver_con_llm(ESTADO, j, d, ["sales"], POL, LLMFijo("expandirse"))
    assert d2.ruta == "llm"
    assert d2.programa == "inmersion_ejecutiva"
    assert j2.objetivo.valor == "expandirse"
    assert len(revs) == 1


def test_llm_no_seguro_pasa_a_persona():
    j = juicios_con_duda_en_objetivo()
    d = decidir(j, ["sales"], POL)
    _, d2, _ = resolver_con_llm(ESTADO, j, d, ["sales"], POL, LLMFijo("no_seguro"))
    assert d2.ruta == "revision_humana"
    assert any("tampoco pudo decidir" in r for r in d2.razones)


def test_llm_nunca_autoriza_pasar_a_ventas():
    j = juicios_con_duda_en_objetivo(p_listo=0.95)
    d = decidir(j, ["sales"], POL)
    _, d2, _ = resolver_con_llm(ESTADO, j, d, ["sales"], POL, LLMFijo("expandirse"))
    assert d2.accion_propuesta == "pasar_a_ventas"
    assert d2.ruta == "revision_humana"


def test_perfil_no_genuino_nunca_llega_al_llm():
    llm = LLMFijo("expandirse")
    j = juicios_con_duda_en_objetivo(valido=0.1)
    d = decidir(j, ["sales"], POL)
    _, d2, revs = resolver_con_llm(ESTADO, j, d, ["sales"], POL, llm)
    assert llm.llamadas == 0 and revs == []
    assert d2.ruta == "revision_humana"


def test_sin_llm_todo_queda_igual():
    j = juicios_con_duda_en_objetivo()
    d = decidir(j, ["sales"], POL)
    j2, d2, revs = resolver_con_llm(ESTADO, j, d, ["sales"], POL, None)
    assert (j2, d2, revs) == (j, d, [])
