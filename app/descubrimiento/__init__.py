"""Descubrimiento automático: Pálpito crea sus propias variables, umbrales y segmentos a partir de un dataset.

Nadie define antes las variables ni los segmentos. El ciclo tiene tres piezas:
- un LLM (o, sin llave, un proponente estadístico) propone variables como preguntas tipadas,
- JEV las responde para cada fila y convierte el texto en números,
- el código elige qué variables sirven, descubre los segmentos y aprende los umbrales con los datos.

Fases (ver docs/DESCUBRIMIENTO.md): esquema → propuesta → medición → selección → segmentos →
umbrales y acciones → asignación en línea → versiones y deriva.
"""
