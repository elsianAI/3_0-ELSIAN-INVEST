# Política de Faltantes — ELSIAN INVEST

**Versión:** 1.1
**Fecha:** 2026-02-14
**Aplica a:** Todos los runners de pre-fetch y sub-agentes del pipeline

---

## Principio

> Runner intenta **fuente primaria + una alternativa**. Si ambas fallan, registra el faltante con prioridad + instrucciones y **continúa**. **Nunca bloquea.**

---

## Límites por tipo de documento

| Documento | Fuente primaria | Alternativa | Si falla ambas | Prioridad |
|-----------|----------------|-------------|----------------|-----------|
| 10-K / 20-F | SEC EDGAR API | EDGAR full-text search | `data_quality: FAIL` | CRITICO |
| 10-Q / 6-K | SEC EDGAR API | Búsqueda ampliada | Log + continuar | ALTO |
| 8-K Earnings | EDGAR (Item 2.02 / Ex99) | — | Log | ALTO |
| DEF14A | SEC EDGAR | — | Log | MEDIO |
| Credit Agreement | EDGAR Exhibit 10.x | — | Log | MEDIO |
| Transcript (earnings call) | Fintool | IR page / SA público | Log | ALTO (4 recientes) / MEDIO |
| Presentation (investor day) | Company IR | Conference pages | Log | ALTO |
| Market data snapshot | Finviz (US) / Yahoo (non-US) | Stooq OHLCV | Ticker inexistente? → CRITICO | CRITICO |
| Local filings (non-US) | Company IR / regulador local | Páginas alternativas IR/regulatorias | EXCEPTION trazada si no hay documento descargable | CRITICO |

---

## Reglas

1. **Reintentos HTTP**: Máximo 1 retry con 3 segundos de backoff (solo para 429/5xx/ConnectionError).

2. **No fuentes de pago**: Si hay paywall, extraer la porción pública disponible y registrar la limitación. No inventar contenido.

3. **No inventar URLs**: Si un documento no se encuentra, registrarlo en `faltantes[]` con campo `como_conseguirlo` describiendo cómo obtenerlo manualmente.

4. **Faltantes no bloquean el pipeline**: Los agentes downstream trabajan con lo disponible. Campos vacíos se representan como `null`. El array `faltantes` viaja con el SourcesPack para que downstream sepa qué falta.

5. **Resolución**: El operador revisa faltantes CRITICO en el dashboard (estado_resumen.py). Decide si re-ejecutar con parámetros diferentes o aceptar la limitación.

6. **Cobertura final**: En cierre de pre-fetch por ticker (scope `latest`), estado válido final es `PASS` o `EXCEPTION`. `NEEDS_ACTION` indica trabajo pendiente.

---

## Niveles de prioridad

| Prioridad | Significado | Acción requerida |
|-----------|-------------|-----------------|
| **CRITICO** | Dato esencial para el análisis. Sin él, el caso queda incompleto. | Operador debe resolver antes de decisión final. |
| **ALTO** | Dato importante. El análisis puede continuar pero con menor confianza. | Operador debería intentar resolver. |
| **MEDIO** | Dato complementario. El análisis no se ve significativamente afectado. | Resolver si es conveniente. |
| **INFO** | Informativo. No aplica a esta empresa (ej: SEC para non-US pure). | No requiere acción. |

---

## Cadena de responsabilidad

| Actor | Rol |
|-------|-----|
| **Runner** | Intenta fuente primaria + alternativa. Registra faltante en `faltantes[]` con tipo, prioridad, razón e instrucciones. |
| **SOURCES_COMPILER** | Consolida faltantes de todos los runners. No intenta resolver. |
| **Orchestrator** | Informa al operador. Continúa el pipeline con lo disponible. |
| **Operador** | Revisa faltantes CRITICO. Decide: re-ejecutar, buscar manualmente, o aceptar. |

---

## Estructura de un faltante

```json
{
  "tipo": "10-K/20-F",
  "prioridad": "CRITICO",
  "razon": "No se encontraron informes anuales en submissions SEC.",
  "como_conseguirlo": "Buscar en SEC EDGAR por CIK 0001234567 > Filings > 10-K/20-F"
}
```

---

## EXCEPTION de cobertura (cuando no se puede completar)

Si tras fallback primario + alternativa + retry no se alcanza el umbral, se permite
cierre en `EXCEPTION` con trazabilidad en:

`casos/{T}/{D}_{M}/_prefetch_coverage_exception.json`

Campos mínimos:
- `status: "EXCEPTION"`
- `required_actions_pendientes`
- `attempted_actions`
- `reason`
- `como_conseguirlo`

Esto evita bloqueo del pipeline y deja cadena de responsabilidad para revisión manual.

---

## Regla de cobertura (latest por ticker)

Clasificación:
- `Domestic_US`
- `FPI_ADR`
- `NonUS_Local`

Umbrales:
- `Domestic_US`: `SEC >= 20`, `TRANS >= 6`, `MKT >= 1`.
- `FPI_ADR`: `SEC >= 10` y además `annual >= 1` (`10-K/20-F/40-F`) + `periodic >= 1` (`10-Q/6-K`), `TRANS >= 4`, `MKT >= 1`.
- `NonUS_Local`: `LOCAL_FILINGS >= 1`, `TRANS >= 4`, `MKT >= 1`.

Estados:
- `PASS`: cumple umbral.
- `NEEDS_ACTION`: no cumple y aún no se intentó todo.
- `EXCEPTION`: no cumple, pero intentos agotados y trazados.

---

## Casos especiales

### Empresa no registrada en SEC (non-US pura)

El SEC_FETCHER registra faltante `SEC Filings` con prioridad **INFO** y, si dispone de `web_ir`/metadatos, intenta fallback local para capturar `LOCAL_FILINGS` dentro de `_sec_fetcher_output.json` (`tipo: IR_NEWS/OTHER` en `categoria: REGULATORIO`).

### ADR / Foreign Private Issuer

Si la empresa tiene CIK en SEC (porque cotiza via ADR o es FPI), el SEC_FETCHER funciona normalmente buscando 20-F y 6-K.

### Market data para bolsas no cubiertas

Si ni Stooq ni Yahoo Finance tienen datos para una bolsa específica, el MARKET_DATA runner genera un faltante CRITICO. El operador debe buscar datos en Bloomberg, Reuters, o la bolsa local.
