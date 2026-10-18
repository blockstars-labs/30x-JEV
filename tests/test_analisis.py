import copy

from app.analisis import analizar
from app.politica import Juicio, Juicios, cargar_politica, decidir
from app.simulacion import medir

POL = cargar_politica()


def perfil(id_, intencion=1, valido=True):
    return {"id": id_, "temas": ["sales"],
            "etiquetas": {"rol": "fundador", "dolor": "ninguno", "objetivo": "vender_mas",
                          "intencion": intencion, "perfil_valido": valido}}


def juicio(p_listo=0.0, p_valido=0.95):
    resto = 1.0 - p_listo
    return Juicios(
        rol=Juicio("fundador", 0.95, {"fundador": 0.96, "sin_dato": 0.04}),
        dolor=Juicio("ninguno", 0.95, {"ninguno": 0.96, "capital": 0.04}),
        objetivo=Juicio("vender_mas", 0.95, {"vender_mas": 0.96, "expandirse": 0.04}),
        intencion_esperada=3 * p_listo + 1 * resto,
        intencion_probabilidades={0: 0.0, 1: resto, 2: 0.0, 3: p_listo}, perfil_valido=p_valido)


def analisis(perfiles, juicios, politica=POL):
    actual = medir(perfiles, juicios, POL)
    return analizar(medir(perfiles, juicios, politica), actual, politica, POL, "mock")


def test_misma_politica_no_reporta_cambios_y_es_segura():
    an = analisis([perfil("A")], {"A": juicio()})
    assert an["cambios"] == []
    assert an["seguro"] and an["alertas"] == []
    assert "de cada 100" in an["titular"]
    assert "no vuelve a llamar a JEV" in an["nota"]
    assert [s["titulo"] for s in an["secciones"]] == [
        "Qué pasa con cada persona", "Quién llega a un asesor", "Qué contenido sale", "Qué tan confiable es"]


def test_un_lead_listo_llega_directo_a_un_asesor():
    an = analisis([perfil("A", intencion=3)], {"A": juicio(p_listo=0.95)})
    ventas = next(s for s in an["secciones"] if s["titulo"] == "Quién llega a un asesor")
    assert any("llegarían directo a un asesor" in f for f in ventas["frases"])


def test_cambiar_un_umbral_explica_el_efecto_frente_a_la_actual():
    estricta = copy.deepcopy(POL)
    estricta["umbrales"]["perfil_valido_min"] = 0.99
    an = analisis([perfil("A")], {"A": juicio()}, estricta)
    assert any("revisaría" in c for c in an["cambios"])


def test_un_perfil_trampa_procesado_solo_genera_alerta():
    an = analisis([perfil("A", valido=False)], {"A": juicio(p_valido=0.95)})
    assert not an["seguro"]
    assert "dejaría pasar casos riesgosos" in an["titular"]
    assert any(x["tono"] == "mal" and "Perfil genuino" in x["texto"] for x in an["alertas"])


def test_asesor_sin_confirmar_por_debajo_de_proponer_avisa():
    rara = copy.deepcopy(POL)
    rara["umbrales"]["listo_ventas_auto"] = 0.4
    rara["umbrales"]["listo_ventas_revision"] = 0.6
    an = analisis([perfil("A")], {"A": juicio()}, rara)
    assert any(x["tono"] == "aviso" for x in an["alertas"])


def test_pesos_en_cero_avisan_que_nadie_tendria_programa():
    sin_pesos = copy.deepcopy(POL)
    sin_pesos["afinidad"]["pesos"] = {k: 0.0 for k in sin_pesos["afinidad"]["pesos"]}
    an = analisis([perfil("A")], {"A": juicio()}, sin_pesos)
    assert any("pesos de afinidad están en cero" in x["texto"] for x in an["alertas"])


def test_la_decision_dice_por_que_pide_ayuda():
    d = decidir(juicio(p_valido=0.1), ["sales"], POL)
    assert d.ruta == "revision_humana" and d.motivo == "perfil_no_genuino"
    m = medir([perfil("A")], {"A": juicio(p_valido=0.1)}, POL)
    assert m["detalle"]["motivos"] == {"perfil_no_genuino": 1}
