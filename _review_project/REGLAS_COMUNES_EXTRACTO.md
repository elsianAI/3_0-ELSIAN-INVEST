# Extracto de Reglas Comunes (para contexto del Meta-Review)

> Este fichero contiene las reglas más relevantes para el proceso de review.
> Fuente: _operativa/REGLAS_COMUNES.md

## Convenciones de artefactos

- Formato ASISTIDO: artifacts generados con asistencia de plataformas manuales (ChatGPT)
  llevan `_meta.motor: "ASISTIDO"` y `_meta.plataforma: "chatgpt"`
- Los artifacts canónicos NO llevan prefijo `_` (ej: MetaReview_v1_TICKER_DATE.json)
- Los ficheros intermedios/temporales llevan prefijo `_` (ej: _review_prompt_gpt52pro_TS.md)

## Decisiones y gates

- 5 gates: data_quality, survivability, mispricing, catalyst, non_speculative
- Un gate CONDITIONAL requiere justificación explícita de por qué no bloquea
- Si algún gate es FAIL, la decisión debe ser DESCARTAR (salvo justificación excepcional)

## Probabilidades y sizing

- Probabilidades siempre en rango [0, 1]
- Escenarios: BASE + BULL + BEAR deben sumar ~1.0 (tolerancia ±0.05)
- Kelly: f = p - (1-p)/b, donde p = prob éxito, b = ratio ganancia/pérdida
- Sizing final = Kelly crudo × factor_confianza × cap_máximo(10%)

## Quality voting

- Sistema de votación determinista que evalúa calidad formal de cada paso
- No evalúa verdad fundamental — solo completitud, estructura y coherencia formal
- Scores de fusión indican acuerdo entre modelos
