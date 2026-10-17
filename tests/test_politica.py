from app.politica import Juicio, Juicios, cargar_politica, decidir


def juicios(rol="fundador", dolor="ninguno", objetivo="vender_mas", intencion=2, p_listo=None,
            valido=0.95, conf=0.9, alternativas=None):
    alternativas = alternativas or {}

    def j(campo, valor):
        segunda = alternativas.get(campo, "otro" if campo == "objetivo" else "sin_dato" if campo == "rol" else "ninguno")
        return Juicio(valor, conf if campo in alternativas else 0.95, {valor: 0.7, segunda: 0.3})

    probs = {i: 0.0 for i in range(4)}
    probs[intencion] = 1.0
    if p_listo is not None:
        probs = {0: 0.0, 1: 0.0, 2: 1 - p_listo, 3: p_listo}
    return Juicios(j("rol", rol), j("dolor", dolor), j("objetivo", objetivo),
                   float(intencion), probs, valido)


POL = cargar_politica()


def test_perfil_invalido_siempre_va_a_revision():
    d = decidir(juicios(valido=0.1, p_listo=0.99), ["sales"], POL)
    assert d.ruta == "revision_humana"
    assert d.accion == "revision_humana"


def test_listo_y_decisor_pasa_a_ventas_automaticamente():
    d = decidir(juicios(p_listo=0.9, intencion=3), ["sales"], POL)
    assert (d.ruta, d.accion) == ("automatico", "pasar_a_ventas")


def test_intencion_no_concluyente_no_pasa_a_ventas_solo():
    d = decidir(juicios(p_listo=0.6), ["sales"], POL)
    assert d.ruta == "revision_humana"
    assert d.accion_propuesta == "pasar_a_ventas"


def test_duda_que_no_cambia_la_decision_no_frena():
    # Duda en dolor entre "ninguno" y "capital": un fundador que quiere expandirse va a Inmersión igual.
    d = decidir(juicios(objetivo="expandirse", conf=0.2, alternativas={"dolor": "capital"}), ["leadership"], POL)
    assert d.ruta == "automatico"
    assert d.programa == "inmersion_ejecutiva"


def test_duda_que_cambia_la_decision_va_a_revision():
    # Duda en objetivo entre "vender_mas" y "expandirse" cambia el programa de un fundador.
    d = decidir(juicios(conf=0.2, alternativas={"objetivo": "expandirse"}), ["sales"], POL)
    assert d.ruta == "revision_humana"


def test_afinidad_baja_no_sugiere_programa():
    d = decidir(juicios(rol="sin_dato", objetivo="otro", intencion=0), [], POL)
    assert d.programa == "ninguno"
    assert d.accion == "nutrir_general"
