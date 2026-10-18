# Puesta en marcha con JEV conectado

## Dónde voy

- [ ] 1. Instalar dependencias
- [ ] 2. Crear el archivo `.env`
- [ ] 3. Poner la llave de TypeSafe
- [ ] 4. (Opcional) Poner la llave de Anthropic
- [ ] 5. Arrancar Pálpito
- [ ] 6. Generar los segmentos con JEV conectado
- [ ] 7. Revisar las alertas de riesgo
- [ ] 8. Correr la evaluación con JEV conectado

## 1. Instalar dependencias

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt     # Windows: .venv\Scripts\python
```

## 2. Crear el archivo `.env`

```bash
cp .env.example .env
```

`.env` está en `.gitignore`: las llaves nunca se suben al repositorio ni se escriben en el código.

## 3. Poner la llave de TypeSafe

En `.env`:

```
JEV_MODO=live
TYPESAFE_API_KEY=<la llave de console.typesafe.ai/keys>
TYPESAFE_DEFAULT_MODEL=jev-1.13.0
```

## 4. (Opcional) Poner la llave de Anthropic

Sin ella, las variables las propone el proponente estadístico y los nombres de segmento salen de plantillas. Con ella,
el LLM escribe preguntas semánticas y nombres legibles. En `.env`:

```
LLM_MODO=live
ANTHROPIC_API_KEY=<la llave de console.anthropic.com>
```

El modelo está en `config/descubrimiento.json` (`modelo_llm`, hoy `claude-opus-5-5`). Claude Haiku cuesta cerca de
20 veces menos por descubrimiento.

## 5. Arrancar Pálpito

```bash
.venv/bin/python -m app.servidor        # http://localhost:8030
```

Arriba a la derecha debe decir «JEV conectado».

## 6. Generar los segmentos con JEV conectado

En la pestaña **Segmentos**, el botón de generar muestra el costo estimado antes de llamar a JEV (cerca de USD 0,20 con
JEV solo; cerca de USD 0,80 con Claude Opus). El resultado queda guardado en `reportes/descubrimiento/` y no se vuelve a pagar.

## 7. Revisar las alertas de riesgo

Botón **Alertas** (campana). La primera carga entrena con las cohortes terminadas y revisa cada mensaje con el
guardrail: cerca de USD 0,01.

## 8. Correr la evaluación con JEV conectado

```bash
.venv/bin/python scripts/evaluar_descubrimiento.py live
```

Escribe `reportes/evaluacion_descubrimiento_live.md`. Costo cercano a USD 0,40 con JEV solo.
