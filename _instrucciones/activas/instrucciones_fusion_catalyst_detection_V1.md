# FUSION CATALYST_DETECTION v1

## Objetivo
Fusionar salidas de múltiples modelos para producir un único `CatalystDetection_v1` consistente y determinista.

## Output obligatorio
Responde **solo** con JSON válido conforme a `CatalystDetection_v1.json`.
Campos obligatorios: `version_esquema`, `caso_id`, `fecha_corte`, `claims_list`, `catalyst_candidates`.

## Reglas de fusión
1. `version_esquema` debe ser exactamente `"CatalystDetection_v1"`.
2. `caso_id` y `fecha_corte`: usar el valor más frecuente; en empate elegir el lexicográficamente mayor.
3. `claims_list`: unir todas las claims deduplicando por `claim_id` cuando exista.
   Si no hay `claim_id`, deduplicar por `enunciado_normalizado`.
4. `catalyst_candidates`: deduplicar por clave determinista:
   - `tipo_normalizado + "|" + descripcion_normalizada`
   - `descripcion_normalizada` = minúsculas + trim + espacios colapsados + sin puntuación no alfanumérica.
5. Para candidatos duplicados, fusionar listas (`evidencia_actual`, `drivers_afectados`,
   `indicadores_lideres`, `riesgos_ejecucion`, `contracatalizadores`) eliminando duplicados por
   string normalizada.
6. No inventar catalizadores nuevos no presentes en ningún input.
7. Mantener neutralidad: resolver conflictos priorizando evidencia concreta y trazable.

## Estabilidad/determinismo
- Ordena `claims_list` por `claim_id` (si existe) y luego por `enunciado`.
- Ordena `catalyst_candidates` por `(tipo, descripcion)`.
- Sin texto fuera del JSON.
