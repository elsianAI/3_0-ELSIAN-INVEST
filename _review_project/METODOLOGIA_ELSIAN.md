# Metodología ELSIAN-INVEST 3.0

## Pipeline de análisis

El pipeline analiza oportunidades de inversión en renta variable small/mid-cap mediante un sistema multi-agente automatizado.

## Pasos del pipeline

1. **SOURCES**: Recopilación de fuentes (SEC filings vía EDGAR, earnings transcripts, market data vía yfinance/FMP)
2. **TRUTH_PACK**: Extracción y validación de datos financieros factuales a partir de los filings originales. Incluye validación de identidades contables (balance, cashflow)
3. **IMPLIED**: Cálculo de expectativas implícitas del mercado (reverse DCF, múltiplos implícitos, crecimiento implícito)
4. **CATALYST**: Detección y scoring de catalizadores a corto/medio plazo (multi-modelo)
5. **FORENSIC**: Análisis forense financiero (calidad de ingresos, red flags contables, análisis de supervivencia)
6. **BULL**: Construcción del caso alcista con claims, evidencias y probabilidades (multi-modelo)
7. **RED_TEAM**: Crítica destructiva del caso: cuestiona cada claim del BULL (multi-modelo)
8. **ARBITRO**: Decisión final: evalúa gates, construye assumption ledger, calcula escenarios probabilísticos, sizing Kelly

## Modelo multi-agente

Cada paso analítico (CATALYST, FORENSIC, BULL, RED_TEAM) se ejecuta en paralelo por 3 modelos (Claude Opus, Codex, Gemini Pro). Los resultados se fusionan mediante un modelo árbitro en un artifact consolidado (AgentReport_v1). El ARBITRO final recibe SOLO los artifacts fusionados.

## Decisiones posibles

- **INVERTIR**: Todos los gates pasan (PASS o CONDITIONAL con justificación), sizing > 0%
- **WATCHLIST**: Potencial detectado pero falta convicción, catalizador no inmediato, o datos insuficientes parciales
- **DESCARTAR**: Riesgos inaceptables, gates en FAIL, o asimetría desfavorable
- **BLOQUEADO**: Datos fundamentales insuficientes no remediables

## Sizing (Kelly)

- Kelly crudo calculado a partir de probabilidades y retornos de escenarios
- Ajustado por confianza global (×0.7 por defecto)
- Cap máximo: 10% de cartera
- Solo se aplica sizing > 0 si decisión = INVERTIR

## Scoring SMCQRV

Score de 0-100 que integra 6 dimensiones:
- **S**urvivability (20%): Riesgo de supervivencia empresarial
- **M**ispricing (25%): Grado de infravaloración detectado
- **C**atalyst (15%): Calidad y temporalidad de catalizadores
- **Q**uality (15%): Calidad del negocio (márgenes, retorno sobre capital)
- **R**isk (15%): Evaluación de riesgos (regulatorio, competitivo, macro)
- **V**aluation (10%): Consistencia de la valoración con evidencia
