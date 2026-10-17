# 30X · JEV Router: estado del proyecto

Actualizado: 17 de octubre de 2026

## Resumen

El prototipo ya clasifica y reclasifica personas de punta a punta, con un LLM que resuelve las dudas de JEV y una calibración automática de umbrales, pero todo en modo simulado: falta conectar el JEV real (y el LLM real) para tener métricas válidas. El código está en [blockstars-labs/30x-JEV](https://github.com/blockstars-labs/30x-JEV), rama `main`, y los 15 tests pasan.

El reto es **30X: JEV**: mostrar qué decisiones de 30X puede tomar JEV (el modelo de decisión de TypeSafe AI) miles de veces al día, en milisegundos y por fracciones de centavo. Elegimos la idea de **clusterización dinámica** del área Comercial: cada persona que se inscribe a un evento queda en un segmento (programa sugerido + siguiente acción), y ese segmento se recalcula cuando su situación cambia.

| Entregable | Estado |
| --- | --- |
| Prototipo: clasificación al inscribirse | Hecho, en modo simulado |
| Prototipo: reclasificación dinámica | Hecho, en modo simulado |
| Ruta hacia un LLM (System Two) | Hecho, en modo simulado |
| Calibración de umbrales | Hecha (script); falta correrla con JEV real |
| Métricas con JEV real | Pendiente: falta la llave de JEV |
| Vista visual del prototipo | Hecha (`python -m app.servidor`) |
| Playbook (máx. 5 páginas u 8 slides) | Pendiente |
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
| `app/servidor.py` | Servidor local de la vista (solo librería estándar): datos de las evaluaciones y prueba en vivo |
| `web/` | La vista: Resumen, Decisiones, Reclasificación y Pruébalo |
| `config/politica.json` | Umbrales y pesos editables |
| `scripts/generar_perfiles.py` | Genera los perfiles y eventos sintéticos |
| `scripts/construir_distribuciones.py` | Saca los conteos agregados del archivo de 30X (solo en local) |
| `scripts/evaluar.py` | Métricas de la clasificación al inscribirse |
| `scripts/evaluar_dinamica.py` | Métricas de la reclasificación con eventos |
| `scripts/calibrar.py` | Prueba 180 combinaciones de umbrales y sugiere la mejor sin errores de seguridad |
| `tests/` | 15 pruebas de la política, la dinámica y el LLM |

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

## Resultados hasta ahora

Todo funciona de punta a punta, pero estas cifras salen del JEV **simulado** y no miden a JEV: sirven para probar el flujo. Las métricas reales llegan cuando tengamos la llave.

| Métrica | Clasificación al inscribirse (300 perfiles) | Reclasificación (361 decisiones) |
| --- | --- | --- |
| Decisiones sin persona (JEV solo + resueltas por el LLM) | 69,3 % (75 + 133) | 69,5 % (136 + 115) |
| Precisión de esas decisiones | 53,4 % | 56,6 % |
| Pases a ventas indebidos | 0 | 1 |
| Perfiles trampa procesados sin revisión | 0 | — |
| Cambios de segmento detectados | — | 82 (58 reales; recall 56,9 %, precisión 40,2 %) |
| Eventos resueltos sin llamar a JEV | — | 60 de 257 |

La precisión por pregunta del simulador (rol 61,7 %, dolor 46,0 %, objetivo 69,0 %) no se compara con la línea base de 30X: tanto JEV como el LLM simulados son sustitutos por palabras clave.

**Costo (300 perfiles, simulado):** JEV cuesta unos USD 0,003 en total. Revisar las dudas con el LLM cuesta unos USD 0,49. Clasificar todo con el LLM en vez de JEV costaría unos USD 2,12 (supuesto: misma entrada y 300 tokens de salida por perfil). JEV hace el trabajo de volumen por una fracción del costo y el LLM se reserva para las dudas.

**Qué vamos a reportar con JEV real** (va directo al playbook):

- Precisión de rol, dolor y objetivo frente a la línea base de 30X (81 / 55 / 55 %).
- Porcentaje de decisiones que toma solo y su precisión.
- Pases a ventas indebidos y trampas que se cuelan: la meta es **0**.
- Calibración: si JEV dice 0,9 de confianza, ¿acierta cerca del 90 %?
- Detección de cambios de segmento (recall y precisión).
- Latencia (p50/p95) y costo por cada 1.000 decisiones.
- Robustez al orden de opciones: JEV tiende a preferir la primera opción, así que reordenaremos y compararemos.
- Precisión de los casos que resolvió el LLM y su costo real.
- La frontera automatización ↔ precisión de `scripts/calibrar.py` y los umbrales recomendados.

## Acceso a JEV

No tenemos llave todavía: la organización en TypeSafe no tiene créditos y la consola no deja crear llaves sin saldo. Hay dos caminos y el código sirve para ambos.

| | TypeSafe | DigitalOcean |
| --- | --- | --- |
| Dónde se crea la llave | [console.typesafe.ai/keys](https://console.typesafe.ai/keys) | Model Studio → Model Access Keys ([guía](https://docs.digitalocean.com/products/inference/how-to/model-access-keys/)) |
| Requisito | Créditos en Billing | Créditos y un nivel de cuenta que habilite modelos de terceros |
| URL | `https://api.typesafe.ai` | `https://inference.do-ai.run` ([guía](https://docs.digitalocean.com/products/inference/how-to/use-system-one-api/)) |
| Modelo | `jev-latest` | `typesafe-jev-1.13.0` |
| Precio | USD 0,042 por millón de tokens de entrada; salida gratis | Igual |

**Cuánto cuesta probar:** una evaluación completa de 300 perfiles son unos 1–3 millones de tokens, entre USD 0,05 y 0,13. Con USD 5 alcanza para todo el reto. No encontramos publicado el mínimo de recarga de TypeSafe; aparece en la pantalla de pago.

**Configuración** en el archivo `.env` (nunca en el código ni en el chat):

```bash
JEV_MODO=live
TYPESAFE_API_KEY=<la llave>
# Solo si se usa DigitalOcean:
TYPESAFE_BASE_URL=https://inference.do-ai.run
TYPESAFE_DEFAULT_MODEL=typesafe-jev-1.13.0
```

Falta probar que el SDK de TypeSafe funcione contra la URL de DigitalOcean; si no, se agrega un cliente HTTP directo. Antes de pagar vale la pena preguntar por créditos del hackathon (community@30x.com) y desactivar la recarga automática.

## Cómo responde a los criterios de evaluación

| Criterio (peso) | Qué lo respalda |
| --- | --- |
| Impacto en el reto (30 %) | Resuelve lo que 30X pidió primero: segmentos que cambian con la persona. Usa sus programas y categorías reales, y se mide contra su clasificación actual (81 / 55 / 55 %) |
| Innovación (20 %) | División System One / System Two: JEV decide en milisegundos y el LLM solo entra en las dudas que cambian la decisión. Reclasificación por eventos, separando hechos observados de inferencias que caducan |
| Viabilidad técnica (20 %) | Código funcionando de punta a punta, 15 tests, métricas reproducibles con perfiles etiquetados y calibración de umbrales con datos |
| Viabilidad de implementación (20 %) | Costo por decisión de fracciones de centavo, umbrales y pesos editables sin programar, cola de revisión humana con motivo, cero pases a ventas indebidos como regla, corre fuera de los sistemas de 30X |
| Presentación (10 %) | Vista del prototipo lista para la demo (incluye un caso trampa y la reclasificación en vivo). Falta el playbook de 8 slides |

## Pendientes y preguntas abiertas

Lo más urgente es conseguir la llave de JEV: sin ella no hay métricas reales ni umbrales calibrados para el playbook.

**Próximos pasos, en orden**

- [x] Ruta hacia un LLM (revisor de dudas y redactor de mensajes)
- [x] Script de calibración de umbrales
- [ ] Conseguir créditos y llave de JEV (TypeSafe o DigitalOcean)
- [ ] Conseguir llave de Anthropic para el LLM real (o correr con `LLM_MODO=off`)
- [ ] Hacer una llamada de prueba y correr ambas evaluaciones con JEV real
- [ ] Correr `scripts/calibrar.py live`, revisar `config/politica_calibrada.json` y aplicar los umbrales
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
