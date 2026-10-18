# Arquitectura de Pálpito

Pálpito es la última decisión antes de enviar: con cada persona (o cada mensaje generado con IA) decide qué hacer,
a quién, con qué contenido y si se puede enviar, a un costo que permite hacerlo miles de veces al día y con reglas
que el equipo de 30X controla.

Un principio ordena todo el código: **JEV mide, el código decide**. JEV (TypeSafe, System One) responde preguntas
tipadas y baratas; el código combina esas respuestas con reglas explícitas, umbrales aprendidos de los datos y
límites fijos que ningún modelo puede saltarse. Un LLM (System Two) entra solo donde JEV no alcanza.

## Las tres capacidades

| Capacidad | Pregunta que responde | Módulos |
|---|---|---|
| Decidir antes de enviar | ¿Qué programa, qué acción y qué mensaje para esta persona? ¿Se puede enviar? | `motor`, `politica`, `guardrail`, `llm`, `personas`, `lote` |
| Segmentos que se descubren solos | ¿Qué grupos hay en este dataset, qué los distingue y qué conviene ofrecerle a cada uno? | `app/descubrimiento/` |
| Alertas de riesgo | ¿Qué alumno puede abandonar, por qué y qué hacer esta semana? | `alertas` (usa el mismo motor de descubrimiento) |

## Mapa de módulos

```
app/
├── jev.py                 Cliente de JEV para el flujo de decisión (real o motor local) y caché
├── preguntas.py           Las preguntas tipadas que JEV responde por cada inscripción
├── motor.py               Una llamada a JEV por persona → juicios con confianza
├── politica.py            Juicios → programa, acción y ruta (automático, LLM o persona), con el motivo
├── llm.py                 System Two: revisa la duda que cambia la decisión y redacta el mensaje
├── guardrail.py           JEV revisa cada mensaje antes de enviarlo: aprobado, revisión humana o bloqueado
├── personas.py            Reclasificación con cada evento (asistencia, respuesta, cambio de cargo)
├── lote.py                Política aplicada a perfiles ya categorizados del CRM (CSV)
├── simulacion.py          Recalcula las decisiones con otra política sin volver a llamar a JEV
├── analisis.py            Explica en lenguaje natural qué produce una configuración de reglas
├── catalogo.py            Programas y acciones de 30X
├── alertas.py             Señales de asistencia, entregas y actividad → riesgo, razones, acción y mensaje
├── vista_descubrimiento.py  Estado de segmentos y alertas para la interfaz (calcula una vez, guarda)
├── servidor.py            Servidor HTTP y API (las llaves nunca llegan al navegador)
└── descubrimiento/        Motor de segmentación dinámica (ver abajo)
web/                       Interfaz sin build: index.html, app.js, estilos.css
config/                    politica.json (reglas y umbrales) · descubrimiento.json (motor de segmentos)
scripts/                   Generación de datos, evaluación y calibración
tests/                     Pruebas unitarias (pytest)
```

## Motor de descubrimiento (`app/descubrimiento/`)

Nadie define variables, umbrales ni segmentos. Con cualquier dataset:

| Paso | Módulo | Qué hace |
|---|---|---|
| 1. Leer | `datos.py` | CSV o XLSX, normaliza textos |
| 2. Perfilar | `esquema.py` | Detecta el tipo de cada columna, cuál es el resultado (conversión, abandono), cuáles son personales y cuáles filtran el resultado (fugas) |
| 3. Proponer variables | `proponer.py` | Preguntas para JEV sobre las columnas de texto: las escribe el LLM o, sin él, un proponente estadístico (términos que separan el resultado, temas, novedad) |
| 4. Medir | `medir.py`, `jev_dinamico.py` | JEV responde todas las preguntas de una fila en una sola llamada; caché de lo ya preguntado |
| 5. Seleccionar | `seleccionar.py` | Regresión L1 con estabilidad en remuestreos: se quedan las variables que predicen el resultado |
| 6. Segmentar | `segmentar.py` | K-means ponderado por relevancia; el número de segmentos se elige fusionando los que no se distinguen en el resultado |
| 7. Aprender umbrales | `aprender.py` | Umbrales de asignación y de propensión medidos fuera de muestra, por nivel de riesgo (conservador, normal, agresivo) |
| 8. Acción por segmento | `aprender.py` | Programa y siguiente paso según lo que pasó con personas parecidas (solo programas que existen en los datos) |
| 9. Asignar | `asignar.py` | Persona nueva → una llamada a JEV → segmento, confianza, acción y explicación; propensión en Python puro |
| 10. Versiones y deriva | `versiones.py`, `reporte.py` | Guarda cada versión, vigila la llegada de gente que no encaja y, al redescubrir, explica qué cambió |

Orquestación: `pipeline.descubrir()` corre los pasos 1 a 8 con tope de presupuesto; `pipeline.recalcular()` aplica
otro nivel de riesgo o un veto sin llamar a JEV.

## Límites fijos (no los cambia ningún umbral)

- Un perfil marcado como no genuino nunca recibe una acción automática ni entra a un segmento.
- El LLM nunca autoriza por su cuenta pasar a alguien a ventas.
- Ningún mensaje sale sin pasar por el guardrail.
- Solo se ofrecen programas que existen en los datos.
- Conteos, fechas y cálculos se hacen en código; a JEV solo se le piden juicios.

## API

| Método y ruta | Qué hace |
|---|---|
| `GET /api/datos` | Decisiones, métricas y política vigente |
| `POST /api/inscribir`, `POST /api/evento` | Decide sobre una inscripción nueva o reclasifica con un evento |
| `POST /api/simular` | Efecto de otra política sobre las decisiones guardadas, con análisis en lenguaje natural |
| `POST /api/guardrail` | Revisión de un mensaje antes de enviarlo |
| `POST /api/perfiles` | Lote de perfiles del CRM (hasta 100 por pedido desde el navegador) |
| `GET /api/descubrimiento` · `POST /api/descubrimiento/generar` | Reporte de segmentación dinámica |
| `POST /api/descubrimiento/ajustar` | Nivel de riesgo o veto de una variable o segmento, sin llamar a JEV |
| `POST /api/descubrimiento/asignar` | Segmento y acción para una persona nueva |
| `GET /api/descubrimiento/reporte.md` | Reporte descargable |
| `GET /api/alertas` | Alertas de riesgo de la cohorte en curso |

## Modos de ejecución

| Variable | Valores | Efecto |
|---|---|---|
| `JEV_MODO` | `live` · `mock` | `live`: JEV conectado (requiere `TYPESAFE_API_KEY`). `mock`: motor local por palabras clave, sin llave ni costo, para desarrollo |
| `LLM_MODO` | `live` · `mock` · `off` | `live`: Claude (requiere `ANTHROPIC_API_KEY`). `off`: las dudas van a una persona |

La interfaz muestra el modo arriba a la derecha («JEV conectado» o «Motor local»). Lo calculado se guarda en
`reportes/` y no se vuelve a pagar. Las versiones de JEV y del LLM están fijadas en `.env` y en
`config/descubrimiento.json` para que los umbrales aprendidos sigan siendo válidos.

## Costos (JEV a USD 0,042 por millón de tokens de entrada)

| Operación | Costo |
|---|---|
| Descubrir segmentos sobre 400 filas | ≈ USD 0,06 (más ≈ USD 0,19 con Claude Opus o ≈ USD 0,01 con Claude Haiku) |
| Asignar a una persona nueva | ≈ USD 0,00007 |
| Asignar a 10.000 personas | ≈ USD 0,71 |
| Alertas de una cohorte de 150, con guardrail | ≈ USD 0,008 |

## Evaluación

`scripts/evaluar_descubrimiento.py` compara contra la verdad conocida de los datos incluidos (que el motor nunca lee):
calidad de los segmentos (ARI), estabilidad entre semillas, detección de deriva, cero filas no genuinas en un
segmento, el mismo motor sobre otro dataset y precisión y cobertura de las alertas. Escribe el resultado en
`reportes/evaluacion_descubrimiento_<modo>.md`. Los demás scripts de `scripts/` evalúan la decisión al inscribirse,
la reclasificación con eventos, la calibración de umbrales y el guardrail.
