# FUSION FORENSIC_DETECTION v1

## Objetivo
Fusionar salidas de múltiples modelos para producir un único `ForensicDetection_v1` consistente y determinista.

## Output obligatorio
Responde **solo** con JSON válido conforme a `ForensicDetection_v1.json`.
Campos obligatorios: `version_esquema`, `caso_id`, `fecha_corte`, `red_flags`, `liquidez`, `puentes`, `kill_criteria_candidatos`.

## Reglas de fusión
1. `version_esquema` debe ser exactamente `"ForensicDetection_v1"`.
2. `caso_id` y `fecha_corte`: usar valor mayoritario; en empate, lexicográfico mayor.
3. `red_flags`: deduplicar por clave determinista:
   - `categoria_normalizada + "|" + descripcion_normalizada`
   - `descripcion_normalizada` = minúsculas + trim + espacios colapsados + sin puntuación no alfanumérica.
4. En `red_flags` duplicadas, fusionar `evidencia` deduplicando por:
   - `source_id + "|" + ubicacion + "|" + cita_corta_normalizada`.
5. `liquidez` y `puentes`: merge por campo; priorizar valores no nulos y más específicos.
   - Si hay conflicto numérico, elegir el valor que venga con mejor evidencia explícita.
   - Si no hay evidencia diferenciadora, elegir el valor mediano cuando sea numérico.
6. `kill_criteria_candidatos`: unir y deduplicar por `kc_id` si existe, si no por `definicion_normalizada`.
7. No inventar red flags ni criterios de liquidación no presentes en inputs.

## Estabilidad/determinismo
- Ordena `red_flags` por `(categoria, descripcion)`.
- Ordena `kill_criteria_candidatos` por `kc_id` (si existe) y luego `definicion`.
- Sin texto fuera del JSON.
