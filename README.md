# Pálpito para 30X

La última decisión antes de enviar. 30X ya genera contenido, mensajes y propuestas con IA; Pálpito decide, persona
por persona, qué se envía, a quién y cuándo, y qué necesita una mirada humana. Barato para hacerlo miles de veces al
día y controlado con reglas que el equipo ajusta sin tocar código.

**JEV mide, el código decide.** JEV (TypeSafe AI) responde preguntas tipadas en milisegundos y por fracciones de
centavo; el código combina esas respuestas con reglas explícitas y umbrales aprendidos de los datos. Un LLM entra
solo donde JEV no alcanza.

## Qué hace

| Capacidad | Resultado |
|---|---|
| Decidir antes de enviar | Cada inscripción recibe programa, acción y mensaje, o pasa a una persona con el motivo. Cada mensaje pasa por el guardrail de JEV antes de salir |
| Segmentos que se descubren solos | Con cualquier dataset, el sistema crea sus variables, aprende sus umbrales y forma sus segmentos. Cuando llega gente nueva que no encaja, los redescubre y explica qué cambió |
| Alertas de riesgo | Con asistencia, entregas y actividad, estima qué alumno puede abandonar, por qué y qué hacer esta semana |

## Vistas

| Vista | Qué muestra |
|---|---|
| Personas | De dónde llegan las personas, con filtros, búsqueda y la ficha de cada una con su historia |
| Decisiones | Cada decisión con su porqué, lo que escribió la persona y la confianza de JEV |
| Reglas | Umbrales y pesos que recalculan todas las decisiones al instante, con un análisis en lenguaje natural de lo que produce la configuración |
| Segmentos | El reporte de segmentación dinámica: versión 1, llegada de un lote, versión 2, flujo de personas, segmentos vigentes con nivel de riesgo y vetos, asignación de una persona y costos |
| Alertas | Alumnos en riesgo alto y medio, con razones, siguiente paso y mensaje revisado |
| Clasificar en vivo | Un lote de perfiles del CRM (CSV de hasta 100 filas) y el guardrail sobre mensajes |

Búsqueda global con ⌘K (o `/`).

## Cómo decide

```
Inscripción (Luma, correo o mensaje)
  → JEV responde las preguntas tipadas en una sola llamada (rol, dolor, objetivo, intención, perfil genuino)
  → la política combina las respuestas: programa, acción y ruta
      actúa sola | duda que cambia la decisión → LLM | persona (con el motivo)
  → el mensaje pasa por el guardrail de JEV: aprobado, revisión humana o bloqueado
  → registro con la explicación de cada decisión
```

Límites fijos: un perfil no genuino nunca recibe una acción automática, el LLM nunca autoriza un pase a ventas y
ningún mensaje sale sin revisión. Detalle en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Puesta en marcha

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt     # Windows: .venv\Scripts\python
cp .env.example .env                                      # llaves y modo de JEV
.venv/bin/python -m app.servidor                          # http://localhost:8030
.venv/bin/python -m pytest -q
```

Paso a paso con JEV conectado: [docs/PUESTA_EN_MARCHA.md](docs/PUESTA_EN_MARCHA.md). Sin llave, Pálpito corre con
el motor local (sin costo) y lo indica arriba a la derecha.

## Datos incluidos

Todos los datos del repositorio son generados y no corresponden a personas reales (correos en `example.com`):

- `data/perfiles_sinteticos.json` y `data/eventos_sinteticos.json`: inscripciones y su historia de eventos.
- `data/descubrimiento/`: inscripciones a eventos, un lote posterior con un grupo nuevo y un registro a webinar.
- `data/alumnos/`: alumnos, asistencias, entregas y actividad de cuatro cohortes.
- `data/distribuciones.json`: conteos agregados del archivo de perfiles de 30X, sin filas ni personas.

El motor de segmentos acepta cualquier CSV o XLSX con el mismo tipo de columnas. Los archivos de 30X no se guardan en
el repositorio (`*.xlsx` y `data/privado/` están ignorados).

## Evaluación

| Script | Qué mide |
|---|---|
| `scripts/evaluar.py` | Decisión al inscribirse: precisión por pregunta, automatización, pases indebidos (deben ser 0), latencia y costo por 1.000 |
| `scripts/evaluar_dinamica.py` | Reclasificación con eventos: cambios de segmento detectados y costo |
| `scripts/calibrar.py` | Umbrales: prueba 180 combinaciones sin volver a llamar a JEV y propone la mejor en `config/politica_calibrada.json` |
| `scripts/evaluar_guardrail.py` | Guardrail sobre mensajes etiquetados |
| `scripts/evaluar_descubrimiento.py` | Segmentos y alertas: calidad (ARI), estabilidad, deriva, reglas fijas, otro dataset, precisión y cobertura |

Los resultados quedan en `reportes/`.

## Documentación

- [docs/PLAYBOOK.md](docs/PLAYBOOK.md): la propuesta para 30X, cómo decide, quién lo opera y cómo se mide.
- [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md): módulos, motor de descubrimiento, API, modos y costos.
- [docs/PUESTA_EN_MARCHA.md](docs/PUESTA_EN_MARCHA.md): llaves y ejecución con JEV conectado.
- [docs/ESTADO_DEL_PROYECTO.md](docs/ESTADO_DEL_PROYECTO.md): historia del proyecto y decisiones tomadas.
- [docs/marca/MARCA.md](docs/marca/MARCA.md): marca y uso del logo.

## Por validar con 30X

- Descripción de cada programa y reglas de asignación (hoy inferidas de los datos).
- Achievers todavía no tiene regla automática.
- Umbrales de `config/politica.json` con una muestra real de 30X.
