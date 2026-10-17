# 30X · JEV Router

Prototipo para el reto **30X: JEV**. Cada persona que se inscribe a un evento de 30X queda clasificada
en milisegundos: qué rol tiene, qué le duele, qué quiere lograr y qué tan lista está para comprar.
Con eso el sistema sugiere un programa de 30X y decide la siguiente acción, o la pasa a una persona
cuando no está seguro.

JEV (TypeSafe AI) toma los juicios rápidos; el código toma las decisiones con reglas explícitas.

## Cómo funciona

```
Inscripción (formulario de Luma, correo o mensaje)
  → JEV responde 5 preguntas tipadas en una sola llamada
      rol (Choice) · dolor (Choice) · objetivo (Choice) · intención (Score) · perfil válido (Noul)
  → app/politica.py combina las respuestas
      afinidad compuesta (pesos en config) → programa sugerido (reglas) → acción
  → umbrales de confianza
      actúa solo | revisión humana (con el motivo)
  → registro con la explicación de cada decisión
```

Principios, tomados de la documentación de TypeSafe:

- Una pregunta simple por juicio; la combinación va en código.
- Conteos, cálculos y fechas en código, nunca en JEV.
- Opción "sin dato / ninguno / otro" en cada Choice.
- Solo importa la duda que cambia la decisión: si la segunda opción de JEV lleva a la misma acción, no se frena.
- Los umbrales se calibran con datos etiquetados (`scripts/evaluar.py`), no se inventan.

## Datos

- `data/perfiles_sinteticos.json`: 300 inscripciones **inventadas** (nombres, empresas y correos ficticios
  en `example.com`), con su respuesta correcta para evaluar. Incluyen casos trampa: spam y textos que
  intentan darle instrucciones al sistema.
- `data/distribuciones.json`: conteos agregados de la muestra de demo de 30X (sin filas ni personas),
  para que los perfiles sintéticos tengan proporciones realistas.
- El archivo de demo de 30X **no está en el repo** y no debe subirse.

## Uso

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # en Linux/Mac: .venv/bin/python
cp .env.example .env                                      # JEV_MODO=mock o live
.venv/Scripts/python scripts/generar_perfiles.py          # 300 perfiles, semilla 30
.venv/Scripts/python scripts/evaluar.py                   # métricas en reportes/
.venv/Scripts/python -m pytest -q
```

- `JEV_MODO=mock`: JEV simulado, sin llave ni costo. Sirve para probar el flujo; **sus métricas no miden a JEV**.
- `JEV_MODO=live`: JEV real. Requiere `TYPESAFE_API_KEY` en `.env` (nunca en el código).

## Métricas

`scripts/evaluar.py` reporta:

- Precisión por pregunta, comparada con la clasificación actual de 30X (rol 81 %, dolor 55 %, objetivo 55 %).
- Tasa de automatización y precisión cuando el sistema actúa solo.
- Pases a ventas indebidos y perfiles inválidos procesados sin revisión (deben ser 0).
- Calibración: precisión por rango de confianza.
- Latencia p50/p95 y costo por cada 1.000 decisiones.

## Pendiente de validar con 30X

- Descripción de cada programa sugerido (hoy inferida de los datos) y las reglas de asignación.
- Achievers no tiene regla automática todavía.
- Umbrales de `config/politica.json`, que se ajustan con los resultados del JEV real.
