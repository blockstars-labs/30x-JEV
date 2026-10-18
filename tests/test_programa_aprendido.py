import copy

from app.politica import cargar_politica, programa_aprendido

# Modelo mínimo: un perfil técnico apunta con fuerza a "AI for devs" (hardcore_ai en el catálogo).
SECCION = {
    "activo": True,
    "umbral_confianza": 0.65,
    "programa_catalogo": {"AI for devs": "hardcore_ai", "AI Sales": "ai_sales"},
    "pesos": {
        "variables": ["rol=tecnico", "tema=sales"],
        "clases": ["AI Sales", "AI for devs", "Otro"],
        "coeficientes": [[-2.0, 2.0], [4.0, -1.0], [0.0, 0.0]],
        "intercepto": [0.0, 0.0, 0.0],
    },
}


def politica_con(seccion):
    p = copy.deepcopy(cargar_politica())
    p["perfiles_por_programa"] = seccion
    return p


def test_actua_cuando_supera_el_umbral():
    programa, p = programa_aprendido("tecnico", "ninguno", "automatizar_ia", [], politica_con(SECCION))
    assert programa == "hardcore_ai" and p >= 0.65


def test_no_actua_bajo_el_umbral():
    # Sin rasgos activos las tres clases empatan (p = 1/3): manda la regla.
    assert programa_aprendido("sin_dato", "ninguno", "otro", [], politica_con(SECCION)) is None


def test_no_actua_si_el_programa_no_existe_en_el_catalogo():
    sec = copy.deepcopy(SECCION)
    sec["programa_catalogo"] = {"AI Sales": "ai_sales"}
    assert programa_aprendido("tecnico", "ninguno", "automatizar_ia", [], politica_con(sec)) is None


def test_se_puede_apagar():
    sec = dict(SECCION, activo=False)
    assert programa_aprendido("tecnico", "ninguno", "automatizar_ia", [], politica_con(sec)) is None
