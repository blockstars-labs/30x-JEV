# 30X · JEV Router: estado del proyecto

Actualizado: 18 de octubre de 2026

## Resumen

El prototipo ya funciona con **JEV real** (jev-1.13.0): en 300 inscripciones sintéticas acierta 99–100 % en rol, dolor y objetivo (30X hoy: 81 / 55 / 55 %), decide solo el 94 % de los casos con 96 % de precisión y no tuvo ningún pase a ventas indebido. El LLM sigue simulado (falta llave de Anthropic). El código está en [blockstars-labs/30x-JEV](https://github.com/blockstars-labs/30x-JEV), rama `main`, y los 22 tests pasan.

El reto es **30X: JEV**: mostrar qué decisiones de 30X puede tomar JEV (el modelo de decisión de TypeSafe AI) miles de veces al día, en milisegundos y por fracciones de centavo. Elegimos la idea de **clusterización dinámica** del área Comercial: cada persona que se inscribe a un evento queda en un segmento (programa sugerido + siguiente acción), y ese segmento se recalcula cuando su situación cambia.

| Entregable | Estado |
| --- | --- |
| Prototipo: clasificación al inscribirse | Hecho, en modo simulado |
| Prototipo: reclasificación dinámica | Hecho, en modo simulado |
| Ruta hacia un LLM (System Two) | Hecho, en modo simulado |
| Calibración de umbrales | Hecha con JEV real |
| Métricas con JEV real | Hechas (18 de octubre) |
| Vista visual del prototipo | Hecha (`python -m app.servidor`) |
| Panel de política (umbrales y pesos en vivo) | Hecho |
| Guardrail de JEV sobre los mensajes del LLM | Hecho, en modo simulado |
| Playbook (máx. 5 páginas u 8 slides) | Hecho, con los resultados reales: [docs/PLAYBOOK.md](PLAYBOOK.md) y versión en 8 slides |
| Repositorio público | Pendiente: hoy es privado |

## Qué se ha hecho

Todo el trabajo es del 17 de octubre de 2026. Las decisiones importantes están en negrita.

| Paso | Qué se hizo | Por qué |
| --- | --- | --- |
| 1 | Se analizó primero el reto de Blinka (agente de pagos) y **se descartó** | El equipo decidió cambiar al reto 30X: JEV |
| 2 | Se compararon las ideas del reto y otras 9 opciones por área | Para elegir la que mejor encaja con JEV y con los datos |
| 3 | **Se eligió clusterización dinámica (Comercial)** | Es la primera idea que pide 30X, los datos de demo calzan y hay una línea base para superar |
| 4 | Se analizó el archivo de perfiles de demo de 30X (697 perfiles) | Saber qué programas vende 30X y cómo los clasifica hoy |
| 5 | **Solo se publican perfiles sintéticos** | Restricción del reto: nada de datos personales y repo público |
| 6 | Se leyó la documentación de TypeSafe y el SKILL.md | Usar la API real y las buenas prácticas del modelo |
| 7 | Repo renombrado a `30x-JEV` y carpeta local `Documents\JEV` | Orden: la carpeta vieja `Blinka` ya no se usa |
| 8 | **Python + SDK oficial de TypeSafe** | El SDK de Python es el más completo |
| 9 | Commit `a51f6a6`: base del sistema | Perfiles sintéticos, preguntas, política, evaluación |
| 10 | Commit `b82c3e3`: reclasificación dinámica | Historial por persona, eventos y cambios de segmento |
| 11 | Ruta hacia un LLM: revisor de dudas y redactor de mensajes | El enunciado pide definir cuándo pasa a una persona **o a un LLM** |
| 12 | Script de calibración de umbrales | Elegir umbrales con datos, sin volver a llamar a JEV |
| 13 | Vista del prototipo: resumen, decisiones, reclasificación y prueba en vivo | Mostrar a JEV decidiendo, para la demo y el playbook |
| 14 | Playbook de 8 slides (presentación aparte, con espacios para las métricas reales) | Entregable obligatorio |
| 15 | Panel de política en la vista | Mostrar que 30X controla las reglas: mover umbrales y ver el efecto sin llamar a JEV |
| 16 | Guardrail: JEV revisa los mensajes del LLM antes de enviarlos | Cierra el ciclo (JEV decide, el LLM escribe, JEV vigila) y cubre la idea de guardrails de 30X |
| 17 | **Conexión a JEV real** (18 de octubre) y tres correcciones con datos | Ver «Resultados con JEV real» |

## Cómo funciona

JEV toma los juicios rápidos y el código toma las decisiones con reglas explícitas. Así cada decisión se puede explicar y los umbrales se cambian sin volver a llamar al modelo.

```mermaid
flowchart LR
    A["Inscripción o mensaje<br/>texto nuevo de la persona"] --> B["JEV: 5 preguntas<br/>una llamada, 70 a 500 ms"]
    B --> C["Política en código<br/>afinidad, programa, acción"]
    E["Asistió a un evento<br/>sin texto nuevo"] -- "recalcula sin llamar a JEV" --> C
    C --> D{"¿Confianza<br/>suficiente?"}
    D -- sí --> F["Actúa solo<br/>ventas o envío de contenido"]
    D -- "duda que cambia la decisión" --> L["LLM revisa la duda<br/>elige o dice «no seguro»"]
    L -- resuelta --> F
    L -- "no seguro o pasar a ventas" --> G["Revisión humana<br/>con el motivo de la duda"]
    D -- "perfil no genuino" --> G
```

Cada texto nuevo pasa por JEV; una asistencia sin texto solo se recalcula en código. Todo resultado queda registrado con su explicación.

### Las 5 preguntas a JEV (una sola llamada)

| Pregunta | Tipo | Opciones |
| --- | --- | --- |
| ¿Qué rol tiene? | Choice | Fundador/CEO, Director o C-level, Líder comercial, Gerente, Técnico, Otro, Sin dato |
| ¿Cuál es su dolor principal? | Choice | Los 9 dolores de 30X + Ninguno |
| ¿Cuál es su objetivo principal? | Choice | Los 10 objetivos de 30X + Otro |
| ¿Qué tan fuerte es su intención de compra? | Score | Sin intención, Explorando, Evaluando, Listo para conversar |
| ¿Es una inscripción genuina? | Noul | Sí/no: detecta spam y textos con instrucciones al sistema |

Las instrucciones van en inglés (JEV rinde mejor así) y los datos de la persona quedan en español. Nombre y correo no se envían.

### Qué hace el código con las respuestas

1. **Afinidad compuesta** (baja, media, alta, muy alta): intención 45 %, poder de decisión por rol 25 %, claridad de la necesidad 15 %, compromiso observado 15 %.
2. **Programa sugerido** con reglas ordenadas: Inmersión Ejecutiva, Sales Machine, Hardcore AI, AI Sales o ninguno. Achievers no tiene regla todavía.
3. **Acción**: pasar a un asesor comercial, enviar contenido del programa, enviar contenido general o revisión humana.
4. **Explicación** en lenguaje natural, guardada con cada decisión.

### Cuándo pasa a una persona

| Situación | Umbral inicial | Resultado |
| --- | --- | --- |
| Perfil poco genuino | p < 0,8 | Revisión humana |
| Duda en rol, dolor u objetivo que cambia la decisión | confianza < 0,45 | Revisión humana |
| Intención de compra no concluyente | p(listo) entre 0,5 y 0,8 | Revisión antes de pasar a ventas |
| Rol incierto antes de pasar a ventas | confianza < 0,7 | Revisión antes de pasar a ventas |

Solo frena la duda que cambiaría la decisión: si la segunda opción de JEV lleva al mismo programa y acción, el sistema actúa solo. Los umbrales están en `config/politica.json` y hay que calibrarlos con el JEV real.

### Cuándo entra el LLM (System Two)

JEV resuelve rápido y barato la mayoría de los casos; el LLM (Claude Opus 5.5) solo entra en dos momentos:

| Momento | Qué hace | Límite |
| --- | --- | --- |
| JEV duda en rol, dolor u objetivo y esa duda cambia la decisión | Lee el texto y elige entre las 3 opciones más probables según JEV, o responde «no seguro» | «No seguro» → persona. Si el resultado es pasar a ventas, igual confirma una persona |
| La acción ya está decidida | Redacta la nota para el asesor o el correo de contenido | No inventa precios, fechas ni beneficios |

El LLM nunca revisa perfiles marcados como no genuinos (spam o texto con instrucciones al sistema): esos van directo a una persona. Con `LLM_MODO=off` el sistema funciona igual y todas las dudas van a personas.

### Reclasificación dinámica

| Evento | Qué hace el sistema |
| --- | --- |
| Responde un correo, contesta la encuesta post-evento o actualiza su cargo | Vuelve a llamar a JEV con el texto nuevo |
| Asiste a un evento | Recalcula el compromiso en código, sin llamar a JEV |
| La última inferencia tiene más de 30 días | Vuelve a llamar a JEV antes de actuar |

Los hechos observados (eventos, fechas, cargo) se guardan tal cual; lo que infiere JEV guarda su fecha y caduca. Cada cambio de segmento queda registrado con el evento que lo causó, por ejemplo: *respondió «¿Cuánto cuesta?» → intención: Evaluando → Listo para conversar → pasar a ventas*.

## Datos y restricciones

El archivo de demo de 30X nunca entra al repo; solo se publican perfiles inventados y conteos agregados.

**Lo que aprendimos del archivo de 30X** (697 perfiles: 298 con deal en el CRM y 399 leads sin deal):

- Programas sugeridos hoy: AI Sales (211), Inmersión Ejecutiva (133), Sales Machine (100), Hardcore AI (35), Achievers (21) y sin programa (197).
- Faltan muchos datos: 73 % sin rol, 85 % sin dolor declarado, 97 % sin país.
- La clasificación actual de 30X acierta 81 % en rol, 55 % en dolor y 55 % en objetivo (medido por 30X contra 220 perfiles revisados a mano). Esa es la **línea base** a superar.
- La afinidad casi no predice quién paga.

**Qué hay en el repo**

| Archivo | Contenido | Se publica |
| --- | --- | --- |
| `data/perfiles_sinteticos.json` | 300 inscripciones inventadas (formulario, correo o mensaje) con su respuesta correcta; ~6 % son trampas (spam, instrucciones al sistema) | Sí |
| `data/eventos_sinteticos.json` | 104 líneas de tiempo con 257 eventos y la verdad tras cada evento | Sí |
| `data/distribuciones.json` | Conteos agregados del archivo de 30X, sin filas ni personas | Sí (confirmar con el equipo) |
| Archivo `.xlsx` de 30X | Datos de demo de 30X | No, bloqueado en `.gitignore` |
| `.env` | Llave de JEV | No, bloqueado en `.gitignore` |

Nombres, empresas y correos son ficticios; los correos usan el dominio reservado `example.com`.

**Restricciones del reto que cumplimos**

- Nada de datos personales reales.
- El prototipo corre fuera de los sistemas de 30X (sin CRM ni Luma).
- No se clona a nadie de 30X ni se inventan productos: solo se usan los programas del archivo.
- Límites de JEV: conteos, fechas y cálculos van en código; preguntas simples; opción «otro / sin dato»; camino a una persona.

## Estructura del repo y cómo correrlo

Con Python 3.10 o superior, el proyecto corre en local en unos minutos y no necesita llave en modo simulado.

| Ruta | Para qué sirve |
| --- | --- |
| `app/catalogo.py` | Categorías de 30X (rol, dolor, objetivo, programas, intención) y su descripción para JEV |
| `app/preguntas.py` | Las 5 preguntas a JEV y qué datos de la persona se le envían |
| `app/jev.py` | Cliente de JEV: modo `live` (SDK de TypeSafe) y `mock` (simulado) |
| `app/politica.py` | Afinidad, reglas de programa, umbrales, revisión humana y explicaciones |
| `app/motor.py` | Flujo de una inscripción: estado → JEV → política → registro |
| `app/personas.py` | Reclasificación dinámica: historial, eventos, compromiso, vigencia |
| `app/llm.py` | LLM (System Two): revisor de dudas y redactor de mensajes, modos `live`, `mock` y `off` |
| `app/servidor.py` | Servidor local de la vista (solo librería estándar): datos, prueba en vivo, simulación de política y guardrail |
| `app/simulacion.py` | Recalcula decisiones con otra política sobre respuestas ya guardadas (calibración y panel) |
| `app/guardrail.py` | JEV revisa los mensajes del LLM: promesas, tono, coherencia, instrucciones; correos y teléfonos en código |
| `web/` | La vista: Resumen, Decisiones, Reclasificación y Pruébalo |
| `config/politica.json` | Umbrales y pesos editables |
| `scripts/generar_perfiles.py` | Genera los perfiles y eventos sintéticos |
| `scripts/construir_distribuciones.py` | Saca los conteos agregados del archivo de 30X (solo en local) |
| `scripts/evaluar.py` | Métricas de la clasificación al inscribirse |
| `scripts/evaluar_dinamica.py` | Métricas de la reclasificación con eventos |
| `scripts/calibrar.py` | Prueba 180 combinaciones de umbrales y sugiere la mejor sin errores de seguridad |
| `scripts/evaluar_guardrail.py` | Mide el guardrail sobre 20 mensajes etiquetados: fugas y falsas alarmas |
| `tests/` | 22 pruebas de la política, la dinámica, el LLM, la simulación y el guardrail |

**Pasos** (en Windows; en Mac o Linux cambia `.venv/Scripts/python` por `.venv/bin/python`):

```bash
git clone https://github.com/blockstars-labs/30x-JEV.git
cd 30x-JEV
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env
.venv/Scripts/python scripts/generar_perfiles.py
.venv/Scripts/python scripts/evaluar.py
.venv/Scripts/python scripts/evaluar_dinamica.py
.venv/Scripts/python scripts/calibrar.py
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m app.servidor   # vista en http://localhost:8030
```

Los reportes quedan en `reportes/` (no se suben al repo). En el `.env`, `JEV_MODO=mock` usa el simulador y `JEV_MODO=live` el JEV real; `LLM_MODO` acepta `mock`, `live` (requiere `ANTHROPIC_API_KEY`) u `off`.

## Resultados con JEV real

Medido el 18 de octubre de 2026 con `jev-1.13.0` sobre los datos sintéticos del repo. El LLM estuvo apagado, así que las cifras miden JEV + reglas.

| Métrica | Resultado | Referencia |
| --- | --- | --- |
| Acierto en rol / dolor / objetivo | 99 % / 100 % / 99 % | 30X hoy: 81 / 55 / 55 % |
| Acierto en intención de compra | 79 % | — |
| Decisiones sin intervención humana | 93,7 % (281 de 300) | — |
| Precisión de esas decisiones | 96,4 % | Los 10 errores son de bajo riesgo: contenido general en vez del de un programa, o al revés |
| Pases a ventas indebidos / trampas procesadas solas | 0 / 0 | Meta: 0 |
| Latencia p50 / p95 | 268 / 358 ms | — |
| Costo | USD 0,07 por 1.000 decisiones | Hacerlo con un LLM costaría unas 180 veces más |
| Reclasificación: cambios de segmento detectados | recall 86 %, precisión 74 % | Con el simulador: 57 % / 34 % |
| Guardrail (20 mensajes etiquetados) | 0 fugas de 12, 0 falsas alarmas de 8 | — |

**Lo que corregimos gracias a JEV real**

1. **Dolor:** al preguntar solo "¿cuál es su dolor?", JEV deducía un dolor a partir del objetivo ("quiero automatizar" → "procesos manuales") y acertaba el 49,7 %. Agregamos una pregunta sí/no aparte ("¿describe explícitamente un problema?") que el código combina con la elección: pasó a 100 %.
2. **Umbral de perfil genuino:** el valor inicial (0,8) mandaba casi todo a revisión, porque JEV da a las inscripciones genuinas entre 0,52 y 0,78. `calibrar.py` mostró que las trampas nunca pasan de 0,10; quedó en 0,35, con margen a ambos lados. Validado en 5 particiones 70/30 con datos no vistos: 91–97 % de automatización y 95–98 % de precisión, siempre sin errores de seguridad.
3. **Guardrail:** la pregunta de coherencia mezclaba dos juicios (programa y persona) y frenaba 6 de 8 mensajes buenos. Separada, quedó en 0 falsas alarmas.

**Cuidado al presentarlo:** las inscripciones son sintéticas, generadas con plantillas a partir de las proporciones de 30X. El texto real es más variado, así que estas cifras hay que confirmarlas con una muestra real etiquetada por 30X. Con 300 casos y cero errores graves, la regla de tres dice que la tasa real podría llegar hasta 1 %.

## Acceso a JEV

Conectado a JEV real por TypeSafe desde el 18 de octubre. La llave va en el archivo `.env` (nunca en el código ni en el chat; git lo ignora):

```bash
JEV_MODO=live
TYPESAFE_API_KEY=<la llave, sin comillas ni espacios>
LLM_MODO=mock   # o live con ANTHROPIC_API_KEY, u off
```

Todas las evaluaciones con JEV real costaron menos de USD 0,10. También se puede usar JEV desde DigitalOcean (`TYPESAFE_BASE_URL=https://inference.do-ai.run` y `TYPESAFE_DEFAULT_MODEL=typesafe-jev-1.13.0`), aunque esa ruta no está probada.

## Cómo responde a los criterios de evaluación

| Criterio (peso) | Qué lo respalda |
| --- | --- |
| Impacto en el reto (30 %) | Resuelve lo que 30X pidió primero: segmentos que cambian con la persona. Usa sus programas y categorías reales, y se mide contra su clasificación actual (81 / 55 / 55 %) |
| Innovación (20 %) | División System One / System Two: JEV decide en milisegundos, el LLM solo entra en las dudas que cambian la decisión y JEV vuelve a vigilar lo que escribe el LLM (guardrail). Reclasificación por eventos, separando hechos observados de inferencias que caducan |
| Viabilidad técnica (20 %) | Código funcionando de punta a punta, 15 tests, métricas reproducibles con perfiles etiquetados y calibración de umbrales con datos |
| Viabilidad de implementación (20 %) | Costo por decisión de fracciones de centavo, umbrales y pesos editables sin programar (con un panel que muestra el efecto antes de aplicarlos), cola de revisión humana con motivo, cero pases a ventas indebidos como regla, corre fuera de los sistemas de 30X |
| Presentación (10 %) | Vista del prototipo lista para la demo (incluye un caso trampa y la reclasificación en vivo). Falta el playbook de 8 slides |

## Pendientes y preguntas abiertas

Lo más urgente es conseguir la llave de JEV: sin ella no hay métricas reales ni umbrales calibrados para el playbook.

**Próximos pasos, en orden**

- [x] Ruta hacia un LLM (revisor de dudas y redactor de mensajes)
- [x] Script de calibración de umbrales
- [x] Conseguir créditos y llave de JEV
- [ ] Conseguir llave de Anthropic para el LLM real (o correr con `LLM_MODO=off`)
- [x] Correr todas las evaluaciones con JEV real
- [x] Calibrar con JEV real y aplicar el umbral de perfil genuino
- [ ] Probar el sesgo por orden de opciones
- [ ] Escribir el playbook (8 slides: problema, qué decide JEV, preguntas, política y umbrales, quién opera, resultados vs. línea base, costo y latencia, riesgos)
- [x] Vista del prototipo: resumen, decisiones con detalle, reclasificación y prueba en vivo
- [ ] Revisar el repo (sin llaves ni datos de 30X) y hacerlo público

**Preguntas para el equipo**

- ¿Quién consigue la llave y por qué camino: TypeSafe, DigitalOcean o créditos del hackathon?
- ¿Cómo nos repartimos el trabajo: playbook, vista del prototipo, evaluación con JEV real?
- ¿Commit directo a `main` o ramas con Pull Request? Hasta ahora se ha subido directo a `main`.
- ¿Podemos publicar `data/distribuciones.json` (conteos agregados del archivo de 30X) o lo quitamos?
- ¿Quién opera el sistema en 30X (quién revisa la cola humana, quién ajusta reglas)? Lo pide el playbook.
- Las descripciones de los programas y sus reglas son inferidas de los datos. ¿Las validamos con 30X? Achievers no tiene regla.
