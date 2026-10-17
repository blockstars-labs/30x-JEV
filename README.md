# 30X · JEV Router

Prototipo para el reto **30X: JEV**. Cada persona que se inscribe a un evento de 30X queda clasificada
en milisegundos: qué rol tiene, qué le duele, qué quiere lograr y qué tan lista está para comprar.
Con eso el sistema sugiere un programa de 30X y decide la siguiente acción, o la pasa a una persona
cuando no está seguro.

JEV (TypeSafe AI) toma los juicios rápidos; el código toma las decisiones con reglas explícitas.

> **¿Nuevo en el proyecto?** Lee primero [docs/ESTADO_DEL_PROYECTO.md](docs/ESTADO_DEL_PROYECTO.md):
> qué se ha hecho, decisiones tomadas, resultados, acceso a JEV y pendientes.

## Cómo funciona

```
Inscripción (formulario de Luma, correo o mensaje)
  → JEV responde 5 preguntas tipadas en una sola llamada
      rol (Choice) · dolor (Choice) · objetivo (Choice) · intención (Score) · perfil válido (Noul)
  → app/politica.py combina las respuestas
      afinidad compuesta (pesos en config) → programa sugerido (reglas) → acción
  → umbrales de confianza
      actúa solo | duda que cambia la decisión → LLM | revisión humana (con el motivo)
  → LLM (System Two, app/llm.py), solo donde JEV no alcanza
      revisa la duda y elige entre las opciones que dejó JEV, o dice "no seguro" → persona
      redacta el mensaje de la acción (nota al asesor o correo)
  → registro con la explicación de cada decisión
```

Límites del LLM: nunca revisa perfiles marcados como no genuinos y nunca autoriza por su cuenta
pasar a alguien a ventas; esos casos siempre los confirma una persona. Modelo: Claude Opus 5.5,
con reintento automático en otro modelo si declina (`fallbacks`).

### Clusterización dinámica

El segmento de una persona (programa sugerido + acción) no se calcula una sola vez: se recalcula
con cada cosa que pasa después de inscribirse (`app/personas.py`).

| Evento | Qué hace el sistema |
|---|---|
| Responde un correo, contesta la encuesta post-evento o actualiza su cargo | Vuelve a llamar a JEV con el texto nuevo |
| Asiste a un evento | Recalcula el compromiso en código (sin llamar a JEV, sin costo) |
| La última inferencia tiene más de 30 días | Vuelve a llamar a JEV antes de actuar |

- **Observado vs. inferido:** los hechos (eventos, fechas, cargo) se guardan tal cual; lo que infiere JEV
  guarda su fecha y caduca.
- **Compromiso:** eventos asistidos en 90 días y días desde la última interacción, calculados en código.
- **Historial:** cada reevaluación queda registrada con el evento que la causó, qué cambió
  (por ejemplo, `intención: Evaluando → Listo para conversar; acción: contenido → pasar a ventas`) y la explicación.

Principios, tomados de la documentación de TypeSafe:

- Una pregunta simple por juicio; la combinación va en código.
- Conteos, cálculos y fechas en código, nunca en JEV.
- Opción "sin dato / ninguno / otro" en cada Choice.
- Solo importa la duda que cambia la decisión: si la segunda opción de JEV lleva a la misma acción, no se frena.
- Los umbrales se calibran con datos etiquetados (`scripts/evaluar.py`), no se inventan.

## Vista del prototipo

```bash
.venv/Scripts/python -m app.servidor   # abre http://localhost:8030
```

Servidor local sin dependencias extra (`app/servidor.py` + `web/`). Si faltan los reportes, corre las
evaluaciones al arrancar. Las llaves se quedan en el servidor; el navegador nunca las ve.

| Pestaña | Qué muestra |
| --- | --- |
| Resumen | Decisiones sin intervención humana, precisión frente a la clasificación actual de 30X, quién decide cada caso (JEV, LLM o persona) y costo frente a hacerlo todo con un LLM |
| Decisiones | Las 300 inscripciones con filtro por ruta; al elegir una: lo que llegó, las probabilidades de JEV, la decisión, la explicación, la revisión del LLM y la respuesta conocida |
| Reclasificación | Líneas de tiempo por persona con cada evento y lo que cambió en su segmento |
| Pruébalo | Escribir una inscripción en vivo (con ejemplos, incluido un caso trampa) y agregarle eventos para ver cómo se reclasifica |

## Datos

- `data/perfiles_sinteticos.json`: 300 inscripciones **inventadas** (nombres, empresas y correos ficticios
  en `example.com`), con su respuesta correcta para evaluar. Incluyen casos trampa: spam y textos que
  intentan darle instrucciones al sistema.
- `data/eventos_sinteticos.json`: líneas de tiempo de ~100 de esas personas (asistencias, correos, encuestas,
  cambios de cargo), con la verdad actualizada después de cada evento.
- `data/distribuciones.json`: conteos agregados de la muestra de demo de 30X (sin filas ni personas),
  para que los perfiles sintéticos tengan proporciones realistas.
- El archivo de demo de 30X **no está en el repo** y no debe subirse.

## Uso

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # en Linux/Mac: .venv/bin/python
cp .env.example .env                                      # JEV_MODO=mock o live
.venv/Scripts/python scripts/generar_perfiles.py          # 300 perfiles, semilla 30
.venv/Scripts/python scripts/evaluar.py                   # clasificación al inscribirse → reportes/
.venv/Scripts/python scripts/evaluar_dinamica.py          # reclasificación con eventos → reportes/
.venv/Scripts/python scripts/calibrar.py live 0.9         # umbrales sugeridos → config/politica_calibrada.json
.venv/Scripts/python -m pytest -q
```

- `JEV_MODO=mock`: JEV simulado, sin llave ni costo. Sirve para probar el flujo; **sus métricas no miden a JEV**.
- `JEV_MODO=live`: JEV real. Requiere `TYPESAFE_API_KEY` en `.env` (nunca en el código).
- `LLM_MODO=mock | live | off`: el revisor y redactor. `live` usa Claude y requiere `ANTHROPIC_API_KEY`;
  `off` desactiva el LLM y todas las dudas van a personas.

## Métricas

`scripts/evaluar.py` reporta:

- Precisión por pregunta, comparada con la clasificación actual de 30X (rol 81 %, dolor 55 %, objetivo 55 %).
- Tasa de automatización y precisión cuando el sistema actúa solo.
- Pases a ventas indebidos y perfiles inválidos procesados sin revisión (deben ser 0).
- Calibración: precisión por rango de confianza.
- Latencia p50/p95 y costo por cada 1.000 decisiones.
- Rutas (automático / resuelto por el LLM / revisión humana), precisión de los casos que resolvió el LLM,
  costo del LLM y cuánto costaría clasificar todo con un LLM en vez de JEV.

`scripts/evaluar_dinamica.py` reporta, después de cada evento:

- Precisión de la decisión y pases a ventas indebidos.
- Cambios de segmento reales frente a detectados (recall y precisión).
- Cuántos eventos se resolvieron sin llamar a JEV y el costo total.

`scripts/calibrar.py` pide a JEV las respuestas una sola vez y prueba 180 combinaciones de umbrales
sin volver a llamarlo. Descarta las que pasan a ventas a alguien indebidamente o dejan pasar perfiles
no genuinos, muestra la frontera automatización ↔ precisión y deja la combinación recomendada en
`config/politica_calibrada.json` para que una persona la revise antes de aplicarla.

## Pendiente de validar con 30X

- Descripción de cada programa sugerido (hoy inferida de los datos) y las reglas de asignación.
- Achievers no tiene regla automática todavía.
- Umbrales de `config/politica.json`, que se ajustan con los resultados del JEV real.
