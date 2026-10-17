import copy

from app.politica import Juicio, Juicios, cargar_politica
from app.simulacion import medir

POL = cargar_politica()
PERFIL = {"id": "T-1", "temas": ["sales"],
          "etiquetas": {"rol": "fundador", "dolor": "ninguno", "objetivo": "vender_mas", "intencion": 1, "perfil_valido": True}}


def juicios(conf_objetivo):
    return {"T-1": Juicios(
        rol=Juicio("fundador", 0.95, {"fundador": 0.96, "sin_dato": 0.04}),
        dolor=Juicio("ninguno", 0.95, {"ninguno": 0.96, "capital": 0.04}),
        objetivo=Juicio("vender_mas", conf_objetivo, {"vender_mas": 0.5, "expandirse": 0.5}),
        intencion_esperada=1.0, intencion_probabilidades={0: 0.0, 1: 1.0, 2: 0.0, 3: 0.0}, perfil_valido=0.95)}


def test_bajar_el_umbral_de_confianza_aumenta_la_automatizacion():
    estricta = medir([PERFIL], juicios(0.3), POL)
    laxa_pol = copy.deepcopy(POL)
    laxa_pol["umbrales"]["confianza_choice_min"] = 0.2
    laxa = medir([PERFIL], juicios(0.3), laxa_pol)
    assert estricta["automatizacion"] == 0.0
    assert laxa["automatizacion"] == 1.0
    assert laxa["precision"] == 1.0


def test_medir_no_modifica_la_politica():
    antes = copy.deepcopy(POL)
    medir([PERFIL], juicios(0.9), POL)
    assert POL == antes
