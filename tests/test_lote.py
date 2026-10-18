import pytest

from app.lote import LIMITE_LOTE, clasificar_lote, clasificar_perfil
from app.politica import cargar_politica

POLITICA = cargar_politica()


def fila(**extra):
    base = {"ID": "P-1", "Rol": "Perfil técnico (ingeniería, datos, producto)", "Dolor principal": "No declaró ningún dolor",
            "Objetivo principal": "Automatizar con IA", "Temas de interés": "ai, ops", "Programa": "AI for devs",
            "Programa sugerido": "Hardcore AI"}
    return base | extra


def test_lee_las_columnas_del_archivo_de_30x():
    r = clasificar_perfil(fila(), POLITICA)
    assert r["entrada"]["rol"] == "tecnico" and r["entrada"]["objetivo"] == "automatizar_ia"
    assert r["entrada"]["temas"] == ["ai", "ops"]
    assert r["comparar"] == {"programa_crm": "AI for devs", "programa_sugerido_30x": "Hardcore AI"}
    assert r["no_reconocidos"] == []


def test_sin_intencion_declarada_nadie_pasa_a_ventas():
    r = clasificar_perfil(fila(Rol="Fundador, socio o CEO", **{"Objetivo principal": "Vender más", "Temas de interés": "sales"}), POLITICA)
    assert r["entrada"]["intencion_supuesta"] and r["accion_propuesta"] != "pasar_a_ventas"


def test_avisa_categorias_que_no_reconoce():
    r = clasificar_perfil(fila(Rol="Astronauta"), POLITICA)
    assert r["entrada"]["rol"] == "sin_dato" and r["no_reconocidos"]


def test_respeta_el_limite():
    with pytest.raises(ValueError):
        clasificar_lote([fila()] * (LIMITE_LOTE + 1), POLITICA)
    with pytest.raises(ValueError):
        clasificar_lote([], POLITICA)
