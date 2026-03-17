---
description: Generate or update expected.json ground truth for any ticker
---

TICKER="${input:ticker}"
PERIOD_SCOPE="${input:period_scope|ANNUAL_ONLY}"

Quiero que generes/actualices el ground truth de este caso en deterministic, sin tocar código.

## Objetivo

Crear/actualizar `deterministic/cases/${TICKER}/expected.json` — la fuente de verdad curada manualmente contra la que el pipeline evalúa su extracción.

## Parámetro: PERIOD_SCOPE

- `ANNUAL_ONLY` (default) — solo periodos FY*. Recomendado para iteración rápida.
- `FULL` — todos los periodos detectables: FY* + Q* + H*. Más completo pero más lento de curar.

## Fuentes (leer en este orden)

1. `deterministic/cases/${TICKER}/case.json` — ticker, currency, source_hint
2. `deterministic/cases/${TICKER}/filings_manifest.json` — qué filings se descargaron
3. `deterministic/config/field_aliases.json` — los 22 campos canónicos válidos (claves que no empiezan por `_`)
4. `deterministic/cases/${TICKER}/filings/*.clean.md` — PRIORIDAD. Tablas markdown extraídas de los filings
5. `deterministic/cases/${TICKER}/filings/*.txt` — FALLBACK. Texto plano del filing

## Restricciones absolutas

- NO modificar código Python.
- NO crear commits.
- NO inventar valores. Si un número no es inequívoco en el filing, omitirlo.
- NO editar extraction_result.json ni filings_manifest.json.

## Estructura obligatoria

```json
{
  "version": "1.0",
  "ticker": "${TICKER}",
  "currency": "<de case.json, o detectada del filing si case.json no la especifica>",
  "scale": "mixed",
  "scale_notes": "<OBLIGATORIO: explicar en qué unidad están los valores monetarios y las excepciones. Ejemplo: 'Monetary fields in thousands as stated in filing tables. EPS in raw units. Shares in thousands.'>",
  "periods": {
    "<period_key>": {
      "fecha_fin": "<ISO date: 2024-12-31>",
      "tipo_periodo": "<anual | trimestral | semestral>",
      "fields": {
        "<canonical_name>": {
          "value": 0.0,
          "source_filing": "<nombre exacto del fichero de donde salió el valor>"
        }
      }
    }
  }
}
```

## Naming de periodos (EXACTO, sin variaciones)

- Anuales: `FY2024`, `FY2023`, etc.
- Trimestrales: `Q1-2024`, `Q2-2024`, `Q3-2024`, `Q4-2024`
- Semestrales: `H1-2024`, `H2-2024`

No uses otros formatos (ni `2024`, ni `Q3 2024` con espacio, ni `FY 2024` con espacio).

## Cobertura de periodos (depende de PERIOD_SCOPE)

**Si PERIOD_SCOPE = ANNUAL_ONLY (default):**
- Incluir todos los periodos ANUALES (FY*) claramente disponibles en los filings.
- NO incluir trimestrales ni semestrales.
- Excepción: si no hay NINGÚN periodo anual disponible, incluir los periodos más completos que existan (H* o Q*) y documentar en scale_notes por qué.

**Si PERIOD_SCOPE = FULL:**
- Incluir todos los periodos detectables: FY* + Q* + H*.
- Priorizar calidad: si un trimestral tiene datos parciales o ambiguos, omitirlo.
- Los trimestrales suelen tener menos campos (no siempre hay balance sheet trimestral). Solo incluir los campos que estén inequívocamente en el filing.

**En ambos casos:** mejor 2 periodos perfectos que 6 con errores.

## Los 22 campos canónicos

Intenta cubrir TODOS los que estén disponibles en los filings. Los 22 son:

**Income Statement:** ingresos, cost_of_revenue, gross_profit, ebitda, ebit, net_income, eps_basic, eps_diluted, research_and_development, sga, depreciation_amortization, interest_expense, income_tax

**Balance Sheet:** total_assets, total_liabilities, total_equity, cash_and_equivalents, total_debt

**Cash Flow:** cfo, capex, fcf

**Per-share / Shares:** dividends_per_share, shares_outstanding

Si un campo NO existe en los filings (por ejemplo, la empresa no reporta ebitda o no paga dividendos), simplemente no lo incluyas. NO pongas `"value": 0` — omitir es diferente de cero.

## Reglas de extracción (trampas conocidas)

### Generales
- Guardar valores en la MISMA unidad que muestra el filing (si dice "in thousands", el valor es en miles).
- No escalar a unidades absolutas.
- No mezclar periodos comparativos del mismo filing (un 10-K de FY2024 muestra FY2024 y FY2023 lado a lado — cada uno va a su periodo).
- Cada valor DEBE incluir `source_filing` con el nombre exacto del fichero.

### Convención de signos (OBLIGATORIA — leer antes de curar cualquier campo)

**Principio general:** valores tal como aparecen en la cara del estado financiero, en su presentación estándar.

**Income Statement — gastos siempre POSITIVOS:**
- `cost_of_revenue`, `research_and_development`, `sga`, `depreciation_amortization`, `interest_expense`, `income_tax`: guardar como **número positivo**. Los gastos aparecen como valores positivos en la cara del income statement (son importes que reducen el beneficio, pero se presentan sin signo negativo).
- `income_tax`: positivo = expense/provision. Puede ser **negativo** SOLO cuando el filing dice explícitamente "benefit from income taxes" o muestra un crédito fiscal.
- `ingresos`, `gross_profit`: siempre **positivos**.
- `ebit`, `ebitda`, `net_income`: **positivos** cuando hay beneficio, **negativos** cuando hay pérdida (reflejan la realidad económica).
- `eps_basic`, `eps_diluted`: siguen el signo de `net_income`.

**Balance Sheet — siempre POSITIVOS:**
- `total_assets`, `total_liabilities`, `cash_and_equivalents`, `total_debt`: **positivos**.
- `total_equity`: positivo cuando hay equity positivo, negativo cuando el déficit acumulado supera el capital.

**Cash Flow:**
- `cfo`: positivo = "net cash provided by", negativo = "net cash used in".
- `capex`: siempre **NEGATIVO** (es un outflow de inversión, tal como aparece en el cash flow statement).
- `fcf`: sigue su signo reportado.

**Per-share / Shares:**
- `dividends_per_share`: **positivo**.
- `shares_outstanding`: **positivo**.

**TRAMPA IMPORTANTE — 20-F y paréntesis:** Algunos filings (especialmente 20-F de foreign private issuers) muestran gastos entre paréntesis como convención de formato. Esto NO significa que el valor sea negativo. Si el 20-F muestra `(200,362)` para cost_of_revenue, guardar `200362` (positivo), porque en la presentación estándar de un income statement los gastos son positivos.

**Caso de duda:** consultar `deterministic/cases/TZOO/expected.json` como referencia (score 100%).

### Confusiones frecuentes
- `net_income` ≠ EPS. Si la fila dice "per share" o "per diluted share", es EPS, no net_income.
- `total_liabilities` ≠ "total liabilities and stockholders' equity" (eso es total_assets). Buscar "total liabilities" SOLO.
- `total_equity` = "total stockholders' equity" o "total shareholders' equity". No confundir con "equity attributable to parent" si hay minority interests.
- `cash_and_equivalents` = "cash and cash equivalents" solamente. NO "cash + restricted cash" si existe la línea separada.
- `shares_outstanding`: preferir "weighted average basic shares outstanding" (las que usa EPS basic). Si no existe, usar "basic shares outstanding". Nunca diluted shares para este campo.
- `ebit` = "operating income" o "income from operations". No confundir con EBITDA.
- `ebitda`: solo si se reporta explícitamente. NO calcular manualmente (EBIT + D&A).
- `fcf`: solo si se reporta explícitamente. NO calcular (CFO + capex).

### Filings EU / IFRS (si source_hint es eu_manual)
- Los filings pueden estar en francés, español o alemán.
- "Chiffre d'affaires" = ingresos, "Résultat net" = net_income, "Résultat opérationnel" = ebit.
- IFRS usa "profit for the year" en lugar de "net income".
- "Profit attributable to owners of the parent" es net_income (no "profit for the year" si hay minority interests).
- El nombre de los periodos sigue el mismo formato: FY2024, H1-2024, etc.

### Filings de earnings / 8-K
- Los 8-K/earnings releases a menudo muestran Non-GAAP metrics. Preferir GAAP siempre que exista.
- Si solo hay Non-GAAP, omitir el campo (no incluir adjusted metrics como ground truth).

### Política de restatements

**Regla base:** usar siempre el valor del **filing primario del periodo** (el 10-K/10-Q que cubre ese periodo fiscal).

**Excepción:** usar el valor de un filing posterior SOLO si ese filing contiene evidencia textual explícita de ajuste. Los triggers válidos son:
- `restated` / `as restated`
- `as revised` / `as corrected`
- `reclassified` / `as reclassified`

Estos triggers deben aparecer en la cabecera de columna comparativa, en una nota al pie, o en un párrafo que explique el ajuste.

**Si no hay trigger explícito:** las diferencias entre el filing primario y el comparativo de un filing posterior se tratan como NO restatement. El expected.json conserva el valor del filing primario.

**Cuando se aplica un restatement**, añadir bloque `restatement` al campo afectado (solo cuando `applied: true`):
```json
{
  "value": 8851,
  "source_filing": "SRC_002_10-K_FY2023.clean.md",
  "restatement": {
    "applied": true,
    "trigger": "reclassified",
    "evidence_text": "reclassified as discontinued operations",
    "restated_in_filing": "SRC_005_10-K_FY2020.clean.md",
    "original_source_filing": "SRC_006_10-K_FY2019.clean.md",
    "original_value": 10863
  }
}
```
Si NO hay restatement, el campo queda limpio: solo `value` y `source_filing`.

**Incluir en raíz de expected.json:** `"restatement_policy": "as_reported_unless_explicit_restatement"`

## Proceso

1. Si ya existe `expected.json`, crear backup: `cp expected.json expected.prev.json`
2. Leer los filings (.clean.md primero, .txt como fallback) y extraer los valores.
3. Escribir `expected.json` con la estructura obligatoria.
4. Validar que el JSON es parseable: `python3 -c "import json; json.load(open('deterministic/cases/${TICKER}/expected.json'))"`
5. Ejecutar evaluación: `python3 -m deterministic.cli eval ${TICKER}`

## Entrega (texto breve al final)

```
Periodos: FY2024, FY2023 (2 periodos)
Campos por periodo: FY2024=17, FY2023=17 (34 total)
Scale: monetary in thousands, EPS raw, shares in thousands
Eval: score=X%, matched=N, wrong=N, missed=N, extra=N, required_fields_coverage_pct=X%
Código modificado: NO
Commit: NO
```
