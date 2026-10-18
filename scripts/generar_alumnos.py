"""Genera registros sintéticos de alumnos de programas de 30X para las alertas de riesgo de abandono.

Registros crudos, como llegarían de la plataforma (el código calcula después conteos y fechas):
- alumnos.csv: alumno, programa, cohorte, cargo, fecha de inicio y estado final (cohortes terminadas).
- asistencias.csv: una fila por alumno y sesión (10 sesiones semanales).
- entregas.csv: una fila por alumno y tarea, con fecha límite y fecha de entrega (vacía si no entregó).
- actividad.csv: mensajes del alumno al mentor o a la comunidad, con fecha.

Cada alumno sale de un perfil latente (comprometido, sin tiempo, frustrado, rezagado o desconectado) que
el sistema nunca ve; la verdad se guarda aparte en verdad.json. Tres cohortes terminadas sirven para
aprender quién abandona; la cohorte actual va en la semana 5 y es la que recibe las alertas.
Nombres y correos inventados (dominio example.com).

Uso:
    python scripts/generar_alumnos.py [semilla]
"""

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app.descubrimiento.datos import escribir_csv  # noqa: E402

SALIDA = RAIZ / "data" / "alumnos"
PROGRAMAS = ["AI Sales", "Sales Machine", "AI for Executives", "30X Executive Program", "AI for devs", "AI Second Brain"]
CARGOS = ["Gerente comercial", "Fundadora", "Director de operaciones", "Desarrollador", "Jefa de marketing", "CEO",
          "Coordinador de ventas", "Analista de datos", "Gerente general", "Líder de producto"]
NOMBRES = ["Valentina", "Santiago", "Camila", "Mateo", "Isabella", "Sebastián", "Mariana", "Nicolás", "Daniela", "Andrés"]
APELLIDOS = ["Rojas", "Herrera", "Castaño", "Quintero", "Salazar", "Mejía", "Ospina", "Villalba"]

PERFILES = {
    "comprometido": {"peso": 55, "asistencia": (0.93, 0.92), "entrega": 0.92, "tarde": 0.08, "actividad": 0.85, "abandono": 0.04,
                     "mensajes": ["Me encantó la sesión de hoy, muy práctica", "Ya apliqué lo de prospección con mi equipo",
                                  "Gracias por la grabación, la vuelvo a ver el fin de semana", "Comparto el avance de mi proyecto",
                                  "Excelente el caso que mostraron, lo vamos a probar"]},
    "sin_tiempo": {"peso": 15, "asistencia": (0.85, 0.35), "entrega": 0.55, "tarde": 0.5, "actividad": 0.45, "abandono": 0.48,
                   "mensajes": ["Esta semana estoy a full con el trabajo", "No he podido conectarme por viajes de trabajo",
                                "¿Quedan grabadas las sesiones? No llego a tiempo", "Tengo cierre de mes y no me da el tiempo",
                                "Perdón por la entrega tarde, se me cruzaron reuniones"]},
    "frustrado": {"peso": 10, "asistencia": (0.75, 0.6), "entrega": 0.75, "tarde": 0.2, "actividad": 0.55, "abandono": 0.55,
                  "mensajes": ["Esperaba algo más práctico", "Siento que esto no aplica a mi empresa",
                               "No me está sirviendo tanto como pensé", "Esto ya lo había visto en otros cursos",
                               "Me cuesta ver cómo llevar esto a mi realidad"]},
    "rezagado": {"peso": 10, "asistencia": (0.82, 0.7), "entrega": 0.4, "tarde": 0.3, "actividad": 0.6, "abandono": 0.38,
                 "mensajes": ["No entendí cómo configurar el agente", "Me perdí en la parte técnica",
                              "¿Hay material para principiantes?", "Intenté la tarea pero no me funcionó el flujo",
                              "Necesito ayuda con el paso a paso de la integración"]},
    "desconectado": {"peso": 10, "asistencia": (0.4, 0.2), "entrega": 0.25, "tarde": 0.3, "actividad": 0.1, "abandono": 0.78,
                     "mensajes": ["Hola", "Ok", "Luego reviso"]},
}
SESIONES, TAREAS, SEMANA_CORTE = 10, 6, 5


def elegir(rng, pesos: dict):
    claves = list(pesos)
    return rng.choices(claves, weights=[pesos[k]["peso"] for k in claves])[0]


def cohorte(rng: random.Random, nombre: str, inicio: date, n: int, terminada: bool, inicio_id: int):
    alumnos, asistencias, entregas, actividad, verdad = [], [], [], [], {}
    for k in range(n):
        aid = f"A-{inicio_id + k:04d}"
        perfil = elegir(rng, PERFILES)
        p = PERFILES[perfil]
        nombre_p = f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)}"
        abandona = rng.random() < p["abandono"]
        semana_abandono = rng.randint(4, 8) if abandona else None
        ultima_semana = SESIONES if terminada else SEMANA_CORTE
        for s in range(1, ultima_semana + 1):
            avance = (s - 1) / (SESIONES - 1)
            prob = p["asistencia"][0] + (p["asistencia"][1] - p["asistencia"][0]) * avance
            if semana_abandono and s >= semana_abandono:
                prob = 0.03
            asistencias.append({"alumno": aid, "sesion": str(s), "fecha": (inicio + timedelta(weeks=s - 1)).isoformat(),
                                "asistio": "Sí" if rng.random() < prob else "No"})
        for t in range(1, TAREAS + 1):
            limite = inicio + timedelta(weeks=t + 1, days=-1)
            if not terminada and limite > inicio + timedelta(weeks=SEMANA_CORTE - 1):
                continue
            entrega = rng.random() < p["entrega"] and not (semana_abandono and t + 1 >= semana_abandono)
            fecha = limite + timedelta(days=rng.randint(1, 6) if rng.random() < p["tarde"] else -rng.randint(0, 3))
            entregas.append({"alumno": aid, "tarea": str(t), "fecha_limite": limite.isoformat(),
                             "fecha_entrega": fecha.isoformat() if entrega else ""})
        dias = ultima_semana * 7
        for d in range(dias):
            if semana_abandono and d >= (semana_abandono - 1) * 7:
                break
            if rng.random() < p["actividad"] / 6:
                origen = PERFILES[rng.choice(list(PERFILES))] if rng.random() < 0.1 else p
                actividad.append({"alumno": aid, "fecha": (inicio + timedelta(days=d)).isoformat(),
                                  "texto": rng.choice(origen["mensajes"])})
        alumnos.append({"alumno": aid, "nombre": nombre_p, "correo": f"{aid.lower()}@example.com", "programa": rng.choice(PROGRAMAS),
                        "cohorte": nombre, "cargo": rng.choice(CARGOS), "fecha_inicio": inicio.isoformat(),
                        "estado_final": ("Abandonó" if abandona else "Terminó") if terminada else ""})
        verdad[aid] = {"perfil": perfil, "abandona": abandona}
    return alumnos, asistencias, entregas, actividad, verdad


def main(semilla: int = 30) -> None:
    rng = random.Random(semilla)
    SALIDA.mkdir(parents=True, exist_ok=True)
    tablas = {"alumnos": [], "asistencias": [], "entregas": [], "actividad": []}
    verdad = {}
    planes = [("2026-04", date(2026, 4, 6), 130, True), ("2026-05", date(2026, 5, 4), 130, True),
              ("2026-06", date(2026, 6, 1), 130, True), ("2026-09", date(2026, 9, 14), 150, False)]
    siguiente = 1
    for nombre, inicio, n, terminada in planes:
        partes = cohorte(rng, nombre, inicio, n, terminada, siguiente)
        for clave, filas in zip(tablas, partes[:4]):
            tablas[clave] += filas
        verdad.update(partes[4])
        siguiente += n
    for clave, filas in tablas.items():
        escribir_csv(SALIDA / f"{clave}.csv", filas)
        print(f"{clave}: {len(filas)} filas")
    (SALIDA / "verdad.json").write_text(json.dumps({"_nota": "Solo para evaluar: el sistema nunca lee este archivo.",
                                                    "corte": (date(2026, 9, 14) + timedelta(weeks=SEMANA_CORTE - 1, days=6)).isoformat(),
                                                    "alumnos": verdad}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
