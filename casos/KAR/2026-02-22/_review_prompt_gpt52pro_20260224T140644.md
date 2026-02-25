# Meta-Review: KAR — 2026-02-22

## Contexto del caso
- Ticker: KAR
- Fecha de análisis: 2026-02-22
- Pipeline completado: 2026-02-24T11:39:57.007494+00:00
- Timestamp de compilación: 20260224T140644
- Modelos utilizados: gemini, codex, claude
- Decisión ARBITRO: WATCHLIST (score: 57/100, confianza: 0.58)

---

## Calidad del pipeline (quality votes)

> **Nota anti-sesgo:** Los scores de calidad son una señal de calidad formal del pipeline (validación de schema, completitud de campos, ratio de nulos). No son indicadores de verdad fundamental ni de calidad del razonamiento. Úsalos como contexto, no como juicio previo.

| Paso | Score fusión | Rango modelos |
|------|-------------|---------------|
| ARBITRO | 99.9 | 66–100 |
| ARBITRO | 100.0 | 66–100 |
| BULL | 100.0 | 98–100 |
| CATALYST_DETECTION | 100.0 | 100–100 |
| CATALYST_SCORING | 100.0 | 97–100 |
| FORENSIC_DETECTION | 99.3 | 99–100 |
| FORENSIC_SCORING | 98.8 | 91–99 |
| IMPLIED | 98.4 | — |
| RED_TEAM | 100.0 | 100–100 |
| TP_EXTRACTOR_FILING | 61.1 | — |

---

## Perspectiva BULL

### Resumen ejecutivo
{"bullets": ["KAR cotiza a EV/FCF 4.1x y FCF yield 24%, descontando una contracción de FCF de -19% a -28% CAGR a 5 años que es inconsistente con activos en desarrollo, deuda neta negativa y un ciclo de capex transitorio.", "La normalización del capex (de US$204M en FY25 a ~US$130-150M) genera mecánicamente US$50-70M de FCF incremental sin necesidad de crecimiento de ingresos, atacando directamente la tesis bajista implícita.", "El balance con caja neta positiva (US$341M vs deuda US$333.5M) elimina el riesgo de quiebra y otorga opcionalidad total para asignación de capital (M&A o buybacks).", "La opacidad contable (sin EBIT explícito, 84% datos trimestrales nulos) crea una prima de complejidad injustificada para un productor con activos convencionales y balance fortificado.", "Riesgos reconocidos: confirmación pendiente de normalización de capex en FY2026, dependencia de commodities, ejecución offshore incierta y posible peak earnings post-adquisición TY2023."], "veredicto_role_local": "WATCHLIST", "confianza_0_1": 0.65}

### Claims principales (CRITICO + IMPORTANTE)
```json
[
  {
    "claim_id": "CLM_F01",
    "enunciado": "El mercado descuenta un escenario de run-off acelerado (FCF CAGR -19% a -28% a 5 años) que es desproporcionado respecto a la evidencia de activos en desarrollo y el ciclo de inversión en curso; la valoración a 4x EV/FCF implica que el FCF desaparecerá en 4-5 años, incompatible con la base de reservas e infraestructura instalada.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_F02",
    "enunciado": "La normalización del capex post-ciclo de desarrollo generará un salto mecánico en FCF de US$50-70M sin requerir crecimiento de ingresos, dado que FY2025 representa un pico de inversión transitorio concentrado en Q4.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_F03",
    "enunciado": "La posición de caja neta positiva (US$341M caja vs US$333.5M deuda, deuda neta -US$7.7M) proporciona un colchón financiero que elimina el riesgo de quiebra y otorga opcionalidad total de capital allocation no reflejada en el múltiplo.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_F04",
    "enunciado": "La estructura operativa de KAR tiene apalancamiento operativo significativo: con margen bruto de 48.82% y CFO/ingresos de 56%, cada incremento de ingresos se amplifica desproporcionadamente en caja, y la estabilización de ingresos basta para proteger FCF.",
    "criticidad": "IMPORTANTE"
  },
  {
    "claim_id": "CLM_F05",
    "enunciado": "La opacidad informativa (sin EBIT, 84% datos trimestrales nulos) genera una prima de descuento verificable que comprime el múltiplo por debajo de su valor justo operativo; cualquier mejora de disclosure es re-rating puro y actúa como catalizador soft.",
    "criticidad": "IMPORTANTE"
  },
  {
    "claim_id": "CLM_F06",
    "enunciado": "La caída de ingresos FY2025 (-19%) incorpora un componente de precio de commodities que es reversible y no refleja deterioro de base productiva; la estabilización o mejora del Brent revertiría parcialmente la tendencia sin volumen incremental.",
    "criticidad": "IMPORTANTE"
  }
]
```
---

## Perspectiva RED_TEAM

### Resumen ejecutivo
{"bullets": ["El ajuste de 'Caja Neta' del Bull ignora US$177.7M de pasivos por arrendamiento (FPSOs); al incluirlos, la posición neta real es deuda US$170M, no caja neta positiva (consenso ambos modelos).", "La tesis bull descansa críticamente en la normalización de capex FY2026, un evento no confirmado: la trayectoria de 4 años es monotónicamente creciente (US$60M→US$105M→US$135M→US$204M) y en offshore maduro el costo de extracción sube, no baja.", "KAR muestra patrón de peak earnings post-adquisición: ingresos cayendo -19% YoY con capex acelerándose +51%, sugiriendo que la adquisición TY2023 (~US$717M) puede haber destruido valor.", "Opacidad contable extrema (sin EBIT, 84% datos trimestrales nulos) impide validar si los márgenes operativos reales están deteriorándose; el EBIT implícito (~18-22%) es muy inferior al margen bruto de 49%.", "El FCF yield del 24% puede ser trampa de valor: la ausencia de retorno de capital histórico a accionistas pese a caja abundante señala desalineación management-accionistas, y el descuento del mercado puede estar preceando correctamente un activo de vida corta."], "veredicto_role_local": "WATCHLIST_NEGATIVO", "confianza_0_1": 0.72}

### Claims principales (CRITICO + IMPORTANTE)
```json
[
  {
    "claim_id": "CLM_RT01",
    "enunciado": "La supuesta 'Caja Neta Positiva' es una ilusión contable que excluye US$177.7M de pasivos por arrendamiento (leases operativos esenciales como FPSOs, principal US$51.8M corriente + US$125.9M no corriente); la posición financiera real ajustada es Deuda Neta de ~US$170M, no caja neta positiva.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_RT02",
    "enunciado": "La normalización de capex asumida por el BULL (de US$204M a ~US$130-150M) es una hipótesis no probada: no existe guidance FY2026, el patrón de capex creciente durante 4 años sugiere escalada estructural, y en offshore maduro el costo de extracción sube exponencialmente. Reducir capex provocaría colapso acelerado de producción.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_RT03",
    "enunciado": "El patrón de ingresos declinantes post-adquisición (FY2024 US$776M → FY2025 US$628M, -19%) combinado con capex acelerado es consistente con peak earnings y destrucción de valor adquisitivo, no con ciclo de inversión transitorio.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_RT04",
    "enunciado": "La ausencia de retorno de capital a accionistas (sin dividendos ni buybacks reportados) pese a deuda neta negativa y FCF de US$300M es una señal de alarma: el management puede estar priorizando M&A destructivo o reteniendo caja sin disciplina.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_RT05",
    "enunciado": "La opacidad contable (sin EBIT reportado, sin desglose de costos operativos, 84% datos trimestrales nulos) puede estar ocultando márgenes operativos en deterioro: la depreciación de US$210M (27% de ingresos) implica EBIT real de ~US$137-169M (margen 18-22%), muy inferior al margen bruto de 49% que sugiere el CFO. El mercado asigna un múltiplo de liquidación porque no confía en la métrica de rentabilidad real.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_RT06",
    "enunciado": "El argumento de 'la empresa se paga sola en 4 años' ignora que en E&P offshore el decline rate natural de los pozos erosiona la base productiva, requiriendo reinversión continua que el BULL subestima al tratar el capex elevado como transitorio.",
    "criticidad": "IMPORTANTE"
  },
  {
    "claim_id": "CLM_RT07",
    "enunciado": "El Q3-2025 con capex de solo US$4.5M seguido de Q4-2025 con US$44M no demuestra 'fin de proyecto'; puede indicar retrasos de ejecución o estacionalidad de facturación que se repetirán con capex concentrado en H2 cada año.",
    "criticidad": "IMPORTANTE"
  }
]
```
---

## Perspectiva CATALYST

### Resumen ejecutivo
{"bullets": ["El mercado descuenta contracción de FCF de 19-28% CAGR a 5 años (EV/FCF 4.1x, FCF Yield ~24%), un escenario de run-off acelerado inconsistente con activos en desarrollo y vida de reserva.", "Los catalizadores financieros (normalización de capex, desapalancamiento, retorno de capital) tienen mayor probabilidad y timing más claro que los operativos (ramp-up de producción, exploración).", "La normalización del Capex (+51% YoY en FY2025) y el ramp-up de producción (Who Dat/Brasil) son los drivers más tangibles para cerrar el gap de valoración, pero dependen de ejecución operativa offshore con incertidumbre material.", "La opacidad informativa (sin EBIT, historico trimestral 84% null) penaliza el múltiplo y limita la capacidad de monitorear progreso temprano; la mejora de disclosure es un catalizador 'soft' pero con baja probabilidad.", "El balance con deuda neta negativa (-US$7.7M) protege contra el downside inmediato, pero el precio de commodities es el factor exógeno dominante: si Brent se sostiene >US$70/bbl, los catalizadores se refuerzan mutuamente.", "La tesis depende de demostrar que la caída de ingresos FY2025 (-19%) es transitoria y no estructural; se requiere combinación de al menos 2-3 catalizadores para revertir la narrativa del mercado."], "veredicto_role_local": "WATCHLIST", "confianza_0_1": 0.68, "justificacion": "2 de 3 modelos asignan WATCHLIST. Gemini otorga APTO (0.82) por enfocarse en los catalizadores de mayor probabilidad, pero Claude (0.58) y Codex (0.74) identifican mayor incertidumbre de timing y dependencia de variables exógenas. La probabilidad ponderada media de los catalizadores es ~0.43 y la confianza de timing ~0.49 (Codex). Existen 2-3 catalizadores con calidad suficiente para seguimiento activo (normalización capex, desapalancamiento, ramp-up), pero la mayoría depende de ejecución operativa compleja o factores exógenos. El valor recomendado de 0.68 refleja la calidad del conjunto de catalizadores con penalización por timing incierto."}

---

## Perspectiva FORENSIC

### Resumen ejecutivo
{"bullets": ["Liquidez robusta (caja US$341M, CFO FY2024 US$435M, deuda neta negativa -US$7.7M) descarta riesgo de insolvencia en 12-24 meses.", "Deterioro acelerado de ingresos (-19% anual, -30% Q4 YoY) coincide con disparo de capex (+51%), elevando intensidad de capital de 17.3% a 32.4% y amenazando sostenibilidad del FCF.", "Opacidad severa: EBIT ausente en todos los periodos, 84% de datos trimestrales nulos, sin calendario de vencimientos ni covenants, signos inconsistentes en P&L.", "Lease liabilities de US$177.7M no incluidos en deuda reportada elevan obligaciones financieras ajustadas un 53% a US$511M; deuda neta ajustada real ~US$170M.", "Calidad de beneficios cuestionable: gap NI-CFO >22% tras D&A y depreciación cuadruplicada señalan agresividad contable y posibles ajustes no monetarios insostenibles.", "Veredicto WATCHLIST: supervivencia no comprometida a corto plazo, pero trayectoria operativa descendente y opacidad contable exigen monitorización activa y obtención de datos faltantes antes de considerar inversión material."], "veredicto_role_local": "WATCHLIST", "confianza_0_1": 0.67}

---

## DecisionPacket completo (ARBITRO)

```json
{
  "version_esquema": "DecisionPacket_v2",
  "backward_compatible_with": "DecisionPacket_v1",
  "caso_id": "CASE_20260222_KAR",
  "fecha_corte": "2026-02-22",
  "empresa": {
    "ticker": "KAR",
    "nombre": "Karoon Energy Ltd",
    "bolsa": "ASX",
    "pais": "AU",
    "sector": "Energy",
    "industria": "Oil & Gas E&P Offshore"
  },
  "input_refs": {
    "sources_pack_caso_id": "CASE_20260222_KAR",
    "truth_pack_caso_id": "CASE_20260222_KAR",
    "implied_expectations_caso_id": "CASE_20260222_KAR",
    "agent_reports": [
      {
        "agent_role": "BULL",
        "agent_nombre": "BULL_FUSION_v1",
        "report_ref": "AgentReport_v1_BULL",
        "confianza_0_1": 0.65
      },
      {
        "agent_role": "RED_TEAM",
        "agent_nombre": "RED_TEAM_v1",
        "report_ref": "AgentReport_v1_REDTEAM",
        "confianza_0_1": 0.72
      },
      {
        "agent_role": "CATALYST",
        "agent_nombre": "CATALYST_SCORING_v1",
        "report_ref": "AgentReport_v1_CATALYST",
        "confianza_0_1": 0.68
      },
      {
        "agent_role": "FORENSIC",
        "agent_nombre": "FORENSIC_SCORING_v1",
        "report_ref": "AgentReport_v1_FORENSIC",
        "confianza_0_1": 0.67
      }
    ]
  },
  "charter": {
    "objetivo": "Rentabilidad extraordinaria en 6-30 meses con perfil no especulativo",
    "horizonte_meses": {
      "min": 6,
      "max": 30
    },
    "restricciones_no_especulativo": [
      "Evitar tesis binaria",
      "Evitar dependencia de financiacion salvadora",
      "Exigir supervivencia 12-24 meses razonable",
      "Exigir catalizador no binario y medible"
    ]
  },
  "resumen_ejecutivo": {
    "decision": "WATCHLIST",
    "tamaño_recomendado_pct_cartera": 0,
    "confianza_global_0_1": 0.58,
    "racional_5_lineas": [
      "KAR cotiza a EV/FCF 4.1x con FCF yield 24%, descontando un colapso de FCF (CAGR -19% a -28%) que parece excesivo si el capex de desarrollo FY2025 (US$204M) es realmente transitorio y la empresa mantiene balance con caja neta positiva (excluyendo leases).",
      "Sin embargo, la tesis alcista depende críticamente de la normalización del capex (de US$204M a <US$150M), una hipótesis plausible pero sin confirmar: no existe guidance FY2026, no hay desglose mantenimiento vs desarrollo, y la tendencia de 4 años es monotónicamente creciente (US$60M→US$204M).",
      "La tendencia operativa es negativa (ingresos -19% YoY, Q4 -30% YoY, capex +51%), la opacidad contable es severa (sin EBIT en 5 periodos, 84% datos trimestrales nulos), y el ajuste por leases operativos (US$177.7M) transforma la caja neta en deuda neta ajustada de ~US$170M.",
      "Los 3 modelos (gemini, codex, claude) convergen unánimemente en WATCHLIST con sizing 0%; la probabilidad del escenario BEAR oscila entre 30-40%, nivel insuficiente para asignar capital sin datos confirmatorios.",
      "La decisión prudente es esperar a la publicación del reporte auditado FY2025, el guidance de capex FY2026 y datos de reservas/producción por activo antes de asignar capital."
    ],
    "lo_mas_importante_ahora": [
      "Obtener FCF FY2025 auditado completo (CFO, capex, net income, EBIT): si FCF >US$150M, la tesis se fortalece materialmente.",
      "Guidance de capex FY2026 con desglose mantenimiento vs desarrollo: si <US$160M, el catalizador principal se confirma.",
      "Datos de producción por activo (Who Dat, Bauna/Patola) y reservas 1P/2P con decline rates para evaluar si el run-off descontado es correcto.",
      "Verificar tabla de vencimientos de deuda, covenants y headroom: riesgo de refinanciación no cuantificable sin estos datos.",
      "Monitorizar estabilización de ingresos trimestrales: si >US$155M sostenido, señal positiva de suelo.",
      "Evaluar anuncios de retorno de capital: ausencia prolongada confirmaría desalineación management-accionistas."
    ],
    "principales_riesgos": [
      "Value Trap estructural: capex alto puede ser necesario para frenar declive natural offshore; trayectoria de 4 años creciente es evidencia adversa.",
      "Deterioro acelerado de ingresos (-19% YoY, Q4 -30% YoY) sin descomposición precio/volumen; si es volumen, es estructural e irreversible.",
      "Leases operativos de US$177.7M convierten deuda neta reportada (-US$7.7M) en deuda neta ajustada (+US$170M), reduciendo el margen de seguridad real.",
      "Opacidad contable severa: sin EBIT, gap NI+D&A vs CFO del 22%, imposibilidad de validar rentabilidad operativa real.",
      "Riesgo de goodwill impairment post-adquisición TY2023 (US$717M) con D&A cuadruplicada e ingresos declinantes.",
      "Ausencia total de retorno de capital pese a caja abundante; riesgo de M&A destructivo financiado con caja existente.",
      "Sin covenants ni vencimientos publicados, el riesgo de refinanciación es no auditable."
    ]
  },
  "_comment_v2_decision_probabilistica": "NUEVO EN V2: bloque probabilístico que complementa la decisión categórica",
  "decision_probabilistica": {
    "probabilidad_exito_0_1": 0.65,
    "retorno_esperado_ponderado_pct": 16.2,
    "escenarios_ponderados": {
      "base": {
        "probabilidad_0_1": 0.45,
        "retorno_estimado_pct": 25
      },
      "bull": {
        "probabilidad_0_1": 0.2,
        "retorno_estimado_pct": 70
      },
      "bear": {
        "probabilidad_0_1": 0.35,
        "retorno_estimado_pct": -22
      }
    },
    "sizing_kelly": {
      "kelly_crudo_pct": 30.5,
      "factor_ajuste_confianza": 0.42,
      "kelly_ajustado_pct": 12.8,
      "tope_maximo_pct": 10,
      "sizing_preliminar_pct": 10.0,
      "sizing_final_pct": 0,
      "nota": "Kelly crudo positivo refleja asimetría moderada. Factor de ajuste bajo (0.42) por convicción limitada dada opacidad contable y catalizador no confirmado. sizing_final_pct = 0 porque decisión = WATCHLIST hasta confirmar catalizador de capex."
    },
    "intervalo_confianza_90_pct": {
      "percentil_5": -30,
      "percentil_50": 16.2,
      "percentil_95": 66
    },
    "conviccion_0_1": 0.58,
    "ratio_asimetria": 1.14,
    "_comment_ratio_asimetria": "upside_base / abs(downside_bear). >2 = asimetría favorable. <1 = desfavorable. 1.14 = moderada.",
    "expected_value_anualizado_pct": 12.2,
    "decision_categorica": "WATCHLIST",
    "_comment_decision_categorica": "Retrocompatible: replica resumen_ejecutivo.decision. Los 3 modelos convergen en WATCHLIST. P(éxito) y ratio asimetría positivos pero insuficientes sin confirmación de catalizadores."
  },
  "_comment_v2_sensibilidad": "NUEVO EN V2: análisis de sensibilidad sobre supuestos clave",
  "analisis_sensibilidad": [
    {
      "assumption_id": "A-001",
      "variable": "capex_fy2026_usd_m",
      "valor_base": 150,
      "rango_test": {
        "min": 100,
        "max": 210,
        "paso": 20
      },
      "impacto_en_retorno_pct": {
        "si_min": 55,
        "si_max": -20
      },
      "impacto_en_decision": "Si capex >US$180M sin mejora de producción >10% YoY → DESCARTAR (value trap confirmada). Si capex <US$140M con guidance → INVERTIR.",
      "nota": "Variable más sensible del caso. Concentra el mayor desacuerdo BULL vs RED_TEAM. Los 3 modelos la identifican como #1 en impacto."
    },
    {
      "assumption_id": "A-002",
      "variable": "ingresos_trimestrales_run_rate_usd_m",
      "valor_base": 155,
      "rango_test": {
        "min": 130,
        "max": 180,
        "paso": 10
      },
      "impacto_en_retorno_pct": {
        "si_min": -30,
        "si_max": 30
      },
      "impacto_en_decision": "Si ingresos trimestrales <US$140M sostenido → kill criteria KC-001 se activa (SALIR). Si >US$170M sostenido → fortalece INVERTIR.",
      "nota": "Run-rate actual Q4-2025 US$156M; la estabilización es condición necesaria para la tesis."
    },
    {
      "assumption_id": "A-003",
      "variable": "fcf_fy2025_usd_m",
      "valor_base": 150,
      "rango_test": {
        "min": 50,
        "max": 250,
        "paso": 50
      },
      "impacto_en_retorno_pct": {
        "si_min": -30,
        "si_max": 35
      },
      "impacto_en_decision": "Si FCF FY2025 <US$100M → confirma compresión severa y DESCARTAR. Si >US$200M → fortalece tesis y mueve a INVERTIR.",
      "nota": "Dato más esperado del caso; no disponible hasta publicación del annual report FY2025."
    },
    {
      "assumption_id": "A-005",
      "variable": "deuda_neta_ajustada_usd_m",
      "valor_base": 170,
      "rango_test": {
        "min": 50,
        "max": 320,
        "paso": 50
      },
      "impacto_en_retorno_pct": {
        "si_min": 10,
        "si_max": -20
      },
      "impacto_en_decision": "Si deuda neta ajustada >US$300M o ratio deuda ajustada/CFO >1.5x → decisión baja a DESCARTAR. Si leases se reducen a <US$100M → decisión puede upgradearse.",
      "nota": "Incluye lease liabilities para evitar sesgo de caja neta reportada. Los 3 modelos coinciden en usar métrica ajustada."
    },
    {
      "assumption_id": "A-009",
      "variable": "reserves_2p_life_years",
      "valor_base": 8,
      "rango_test": {
        "min": 4,
        "max": 15,
        "paso": 2
      },
      "impacto_en_retorno_pct": {
        "si_min": -40,
        "si_max": 30
      },
      "impacto_en_decision": "Si vida de reservas <5 años → mercado tiene razón con valoración de run-off (DESCARTAR). Si >10 años con decline <15% → INVERTIR.",
      "nota": "Dato no disponible; petición ALTA de fuentes. Prueba definitiva de la tesis de run-off. Identificado solo por claude y codex."
    },
    {
      "assumption_id": "A-014",
      "variable": "headroom_covenants_pct",
      "valor_base": 20,
      "rango_test": {
        "min": 5,
        "max": 35,
        "paso": 5
      },
      "impacto_en_retorno_pct": {
        "si_min": -20,
        "si_max": 4
      },
      "impacto_en_decision": "Si headroom <10% o hay waiver/breach → DESCARTAR inmediato. Principal bloqueador para INVERTIR según codex.",
      "nota": "Supuesto crítico sin evidencia directa actual; opacidad total sobre covenants."
    }
  ],
  "gates": {
    "data_quality_gate": {
      "status": "PASS",
      "por_que": [
        "TruthPack data_quality.status = PASS con 100% confidence, 10 gates ejecutados.",
        "ImpliedExpectations status = OK con reverse DCF convergente en 24/24 combinaciones.",
        "Balance identity PASS (diff 0%), cashflow identity PASS (diff 4.47%).",
        "Limitaciones documentadas (opacidad EBIT, falta desglose trimestral, FY2025 no auditado) son gestionables vía margen de seguridad y WATCHLIST.",
        "53% completitud general es aceptable pero limita triangulación (84% null trimestral)."
      ],
      "faltantes_criticos": [
        {
          "item": "EBIT / Operating Income",
          "como_resolver": "Extraer Operating Income del annual report FY2025 o calcular proxy vía EBITDA - D&A."
        },
        {
          "item": "CFO/FCF Auditado FY2025",
          "como_resolver": "Esperar publicación de Annual Report FY2025."
        },
        {
          "item": "acciones_diluidas",
          "como_resolver": "Nota de EPS en annual report, diluted weighted-average shares."
        },
        {
          "item": "vencimientos_deuda_y_covenants",
          "como_resolver": "Notas de deuda financiera en annual report, credit agreement, maturity schedule y headroom."
        }
      ]
    },
    "survivability_gate": {
      "status": "CONDITIONAL",
      "por_que": [
        "FORENSIC evalúa supervivencia PASS con score 3/5 y runway estimado de 24 meses.",
        "Caja US$341M cubre servicio de deuda+leases (US$84.6M/año) con cobertura ~5x por CFO.",
        "CFO FY2024 US$434.6M es material y positivo; incluso con compresión del 30%, FCF estimado positivo.",
        "Lease liabilities US$177.7M elevan deuda ajustada y reducen margen de seguridad real (deuda neta ajustada ~US$170M).",
        "Falta detalle de vencimientos y covenants, por lo que el riesgo de refinanciación no es auditable al 100%."
      ],
      "condiciones_si_conditional": [
        "Publicar covenants y vencimientos con headroom >=20%.",
        "Mantener caja >US$200M y FCF TTM positivo.",
        "Evitar breach/waiver de covenant en próximos reportes."
      ]
    },
    "mispricing_gate": {
      "status": "PASS",
      "por_que": [
        "EV/FCF 4.13x y FCF yield 24.06% implican deterioro extremo de caja futura (CAGR -19% a -28% en 24 combinaciones).",
        "Gap claro entre precio (liquidación/run-off) y valor intrínseco de empresa en marcha si normalización se confirma.",
        "Existen mecanismos de cierre del gap (normalización capex, estabilización ingresos, disciplina de capital).",
        "PERO el mecanismo de cierre depende de catalizador NO CONFIRMADO (normalización de capex sin guidance); debilita materialmente el gate.",
        "Sin datos de reservas, no se puede refutar con certeza la tesis de run-off del mercado."
      ]
    },
    "catalyst_gate": {
      "status": "PASS",
      "por_que": [
        "Se consolidan 3-4 catalizadores no binarios, medibles y en ventana 6-24 meses.",
        "Catalizador principal (capex normalization) es no binario, medible y con ventana de 6-18 meses.",
        "Calidad del set calificada como MEDIA por consenso de modelos; probabilidad ponderada media ~0.45.",
        "PERO: catalizador principal carece de evidencia confirmatoria directa (no hay guidance, tendencia es creciente).",
        "Se requiere combinación de 2-3 catalizadores para revertir narrativa, lo cual baja la probabilidad conjunta."
      ]
    },
    "non_speculative_gate": {
      "status": "PASS",
      "banderas": {
        "tesis_binaria_detectada": false,
        "dependencia_financiacion_salvadora": false,
        "opacidad_inaceptable": false
      },
      "por_que": [
        "No es tesis binaria: existe gradiente de outcomes (normalización parcial genera retorno parcial).",
        "Empresa operativa con generación de caja real y activos tangibles en producción.",
        "No depende de financiación salvadora: caja neta positiva y FCF positivo eliminan necesidad de acceder a mercados.",
        "La opacidad es alta (sin EBIT, 84% datos nulos) pero no inaceptable: métricas de balance y FCF son verificables.",
        "La decisión final WATCHLIST con sizing 0% refleja prudencia ante incertidumbre residual."
      ]
    }
  },
  "scoring_preliminar": {
    "metodo": "Score_0_100",
    "componentes": {
      "S_supervivencia_0_25": 17,
      "M_mispricing_0_25": 19,
      "C_catalizador_0_20": 12,
      "Q_calidad_0_15": 7,
      "R_downside_0_15": 8,
      "V_penalizacion_0_a_menos15": -6
    },
    "total_0_100": 57,
    "nota": "Score moderado-bajo. Fortaleza en Supervivencia (17/25) y Mispricing (19/25). Penalizado por Calidad/opacidad (Q=7, V=-6) y catalizador no confirmado (C=12). Rango de los 3 modelos: [53, 60, 61]."
  },
  "assumption_ledger": {
    "reglas": {
      "id_prefix": "A-",
      "max_supuestos": 40,
      "supuesto_critico_sin_evidencia_fuerte": "penalizar_tamaño_o_watchlist"
    },
    "supuestos": [
      {
        "assumption_id": "A-001",
        "enunciado": "El capex FY2025 de US$203.8M es transitorio (ciclo de desarrollo) y se normalizará a US$130-150M en FY2026, liberando US$50-70M de FCF incremental.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.58,
        "confianza_0_1": 0.5,
        "impacto": "ALTO",
        "drivers_afectados": [
          "FCF",
          "CAPEX"
        ],
        "evidencias": [
          {
            "source_id": "SRC_008",
            "ubicacion": "Investor Presentation FY2025 capex",
            "cita_corta": "Capex FY2025 US$203.8M; Q3 US$4.5M vs Q4 US$44M",
            "interpretacion": "Concentración en Q4 sugiere capex de proyecto puntual, no mantenimiento recurrente."
          },
          {
            "source_id": "SRC_001",
            "ubicacion": "Annual Report FY2024 capex",
            "cita_corta": "Capex FY2024 US$134.7M generando FCF US$299.9M",
            "interpretacion": "FY2024 como referencia de nivel pre-ciclo de desarrollo."
          }
        ],
        "falsacion": {
          "test": "Capex FY2026 guiado o reportado >=US$180M sin incremento de producción >10% YoY",
          "ventana_meses": {
            "min": 3,
            "max": 18
          },
          "fuente_prevista": "earnings",
          "accion_si_falla": "REDUCIR_50"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "BULL",
            "claim_id": "CLM_F02"
          },
          {
            "agent_role": "CATALYST",
            "claim_id": "CLM_03"
          },
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT02"
          }
        ],
        "notas_arbitro": "Supuesto MÁS CRÍTICO de la tesis. Consenso 3/3 modelos. La trayectoria de 4 años es monotónicamente creciente (US$60M→US$204M). Sin guidance FY2026 ni desglose mantenimiento/desarrollo, la hipótesis es especulativa. Red Team califica como FRAGIL (prob fallo 0.60). Rango de probabilidad modelos: [0.55, 0.60, 0.62]. Se usa 0.58 como mediana ponderada por evidencia citada."
      },
      {
        "assumption_id": "A-002",
        "enunciado": "Los ingresos trimestrales se estabilizarán por encima de US$150M en FY2026, deteniendo la tendencia de caída (-19% FY2025, Q4 YoY -30%).",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.52,
        "confianza_0_1": 0.45,
        "impacto": "ALTO",
        "drivers_afectados": [
          "FCF",
          "MARGEN_OPERATIVO"
        ],
        "evidencias": [
          {
            "source_id": "SRC_008",
            "ubicacion": "Investor Presentation FY2025 ingresos trimestrales",
            "cita_corta": "Q3 US$164M → Q4 US$156M, tendencia descendente",
            "interpretacion": "No hay señal de estabilización en los datos disponibles."
          }
        ],
        "falsacion": {
          "test": "Ingresos trimestrales <US$140M durante 2 trimestres consecutivos en FY2026",
          "ventana_meses": {
            "min": 3,
            "max": 12
          },
          "fuente_prevista": "earnings",
          "accion_si_falla": "SALIR"
        },
        "dependencias": [
          "A-006",
          "A-009"
        ],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "BULL",
            "claim_id": "CLM_F06"
          },
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT03"
          },
          {
            "agent_role": "CATALYST",
            "claim_id": "CLM_02"
          }
        ],
        "notas_arbitro": "Consenso 3/3 modelos en criticidad. Sin descomposición precio/volumen no se puede saber si la caída es reversible. Rango prob: [0.50, 0.52, 0.55]. Se usa 0.52."
      },
      {
        "assumption_id": "A-003",
        "enunciado": "El FCF FY2025 auditado será positivo y material (>US$100M), demostrando que la capacidad de generación de caja no se ha destruido pese al capex de US$204M.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.6,
        "confianza_0_1": 0.55,
        "impacto": "ALTO",
        "drivers_afectados": [
          "FCF"
        ],
        "evidencias": [
          {
            "source_id": "SRC_001",
            "ubicacion": "TruthPack FY2024",
            "cita_corta": "CFO US$434.6M; margen bruto 48.82%; CFO/ingresos 56%",
            "interpretacion": "Con ingresos FY2025 de US$628M y margen CFO similar (~50-55%), CFO estimado ~US$310-345M menos capex US$204M = FCF ~US$106-141M."
          }
        ],
        "falsacion": {
          "test": "FCF FY2025 reportado <US$50M o negativo",
          "ventana_meses": {
            "min": 3,
            "max": 6
          },
          "fuente_prevista": "earnings",
          "accion_si_falla": "SALIR"
        },
        "dependencias": [
          "A-002"
        ],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "BULL",
            "claim_id": "CLM_F07"
          },
          {
            "agent_role": "FORENSIC",
            "claim_id": "CLM_001"
          },
          {
            "agent_role": "CATALYST",
            "claim_id": "CLM_05"
          }
        ],
        "notas_arbitro": "Dato más esperado del caso. Forensic estima FCF FY2025 <US$200M con p=0.60-0.72. Rango prob modelos: [0.58, 0.60, 0.60]. Se usa 0.60."
      },
      {
        "assumption_id": "A-004",
        "enunciado": "La posición de caja neta (excluyendo leases) se mantendrá positiva o neutra durante FY2026, proporcionando colchón de solvencia.",
        "tipo": "INFERENCIA",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.77,
        "confianza_0_1": 0.72,
        "impacto": "ALTO",
        "drivers_afectados": [
          "OTRO"
        ],
        "evidencias": [
          {
            "source_id": "SRC_001",
            "ubicacion": "Balance Sheet FY2024",
            "cita_corta": "Caja US$341M vs deuda US$333.5M; deuda neta -US$7.7M",
            "interpretacion": "Con FCF estimado positivo incluso en escenario de estrés, la caja debería mantenerse."
          }
        ],
        "falsacion": {
          "test": "Caja cae <US$200M con deuda neta positiva >US$150M",
          "ventana_meses": {
            "min": 6,
            "max": 24
          },
          "fuente_prevista": "filing",
          "accion_si_falla": "REDUCIR_50"
        },
        "dependencias": [
          "A-003"
        ],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "BULL",
            "claim_id": "CLM_F03"
          },
          {
            "agent_role": "FORENSIC",
            "claim_id": "CLM_003"
          }
        ],
        "notas_arbitro": "Rango prob modelos: [0.74, 0.80]. Alta probabilidad dado FCF históricamente positivo. Leases y capex elevado reducen colchón si CFO se comprime >30%."
      },
      {
        "assumption_id": "A-005",
        "enunciado": "Los lease liabilities de US$177.7M son obligaciones financieras reales que elevan la deuda neta ajustada a ~US$170M, reduciendo materialmente el margen de seguridad reportado.",
        "tipo": "HECHO",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.97,
        "confianza_0_1": 0.93,
        "impacto": "ALTO",
        "drivers_afectados": [
          "COSTE_DEUDA",
          "OTRO"
        ],
        "evidencias": [
          {
            "source_id": "SRC_001",
            "ubicacion": "TruthPack lease_data FY2024",
            "cita_corta": "Lease liabilities US$177.7M; pagos anuales US$51.1M (principal US$39.4M + finance charge US$11.7M)",
            "interpretacion": "FPSO leases son deuda operativa esencial; sin el FPSO, la producción se detiene."
          }
        ],
        "falsacion": {
          "test": "N/A - Hecho contable verificado. Se revisaría si empresa demuestra que leases pueden cancelarse sin paralización operativa.",
          "ventana_meses": {
            "min": 0,
            "max": 12
          },
          "fuente_prevista": "filing",
          "accion_si_falla": "REVISAR_COMITE"
        },
        "dependencias": [],
        "estado": "CONFIRMADA",
        "origen": [
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT01"
          },
          {
            "agent_role": "FORENSIC",
            "claim_id": "CLM_004"
          }
        ],
        "notas_arbitro": "Consenso total 3/3 modelos. Se acepta la corrección de Red Team: deuda ajustada real ~US$511M vs caja US$341M."
      },
      {
        "assumption_id": "A-006",
        "enunciado": "La caída de ingresos FY2025 (-19%) tiene un componente de precio de commodities significativo (40-60%) que es potencialmente reversible.",
        "tipo": "HIPOTESIS",
        "criticidad": "IMPORTANTE",
        "probabilidad_0_1": 0.42,
        "confianza_0_1": 0.35,
        "impacto": "ALTO",
        "drivers_afectados": [
          "FCF",
          "MARGEN_OPERATIVO"
        ],
        "evidencias": [
          {
            "source_id": "SRC_008",
            "ubicacion": "Investor Presentation FY2025",
            "cita_corta": "Ingresos FY2025 US$628.5M vs FY2024 US$776.5M (-19%); sin descomposición precio/volumen",
            "interpretacion": "Sin datos de precio realizado, la estimación de contribución precio vs volumen es genérica."
          }
        ],
        "falsacion": {
          "test": "Precio realizado estable YoY y ingresos siguen cayendo >10%, confirmando declive de volumen estructural",
          "ventana_meses": {
            "min": 3,
            "max": 12
          },
          "fuente_prevista": "earnings",
          "accion_si_falla": "REVISAR_COMITE"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "BULL",
            "claim_id": "CLM_F06"
          }
        ],
        "notas_arbitro": "Identificado por claude; codex y gemini lo subsumen en A-002/A-003. Red Team señala que Brent ha sido relativamente estable. Confianza muy baja por falta total de datos de precio realizado."
      },
      {
        "assumption_id": "A-007",
        "enunciado": "El apalancamiento operativo de KAR (margen bruto 49%, CFO/ingresos 56%) protegerá la generación de caja incluso con ingresos menores.",
        "tipo": "INFERENCIA",
        "criticidad": "IMPORTANTE",
        "probabilidad_0_1": 0.62,
        "confianza_0_1": 0.58,
        "impacto": "ALTO",
        "drivers_afectados": [
          "FCF",
          "MARGEN_OPERATIVO"
        ],
        "evidencias": [
          {
            "source_id": "SRC_001",
            "ubicacion": "TruthPack métricas FY2024",
            "cita_corta": "Gross profit US$379.1M (48.82%), CFO US$434.6M (56% ingresos)",
            "interpretacion": "Alta conversión a caja indica costos variables bajos; estructura favorable."
          }
        ],
        "falsacion": {
          "test": "CFO/ingresos cae <35% o margen bruto <40% durante dos periodos consecutivos",
          "ventana_meses": {
            "min": 6,
            "max": 18
          },
          "fuente_prevista": "earnings",
          "accion_si_falla": "REDUCIR_50"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "BULL",
            "claim_id": "CLM_F04"
          },
          {
            "agent_role": "CATALYST",
            "claim_id": "CLM_06"
          }
        ],
        "notas_arbitro": "Rango prob modelos: [0.60, 0.65]. Red Team advierte que el apalancamiento opera en ambas direcciones. CFO/ingresos de 56% puede incluir efectos no sostenibles (gap NI+D&A vs CFO de 22%)."
      },
      {
        "assumption_id": "A-008",
        "enunciado": "La adquisición TY2023 (~US$717M) no destruyó valor irreversiblemente; los activos adquiridos contribuyen a la generación de caja actual.",
        "tipo": "HIPOTESIS",
        "criticidad": "IMPORTANTE",
        "probabilidad_0_1": 0.55,
        "confianza_0_1": 0.42,
        "impacto": "ALTO",
        "drivers_afectados": [
          "FCF",
          "MULTIPLO",
          "OTRO"
        ],
        "evidencias": [
          {
            "source_id": "SRC_001",
            "ubicacion": "TruthPack TY2023 y FY2024",
            "cita_corta": "CFI TY2023 -US$728M; D&A cuadruplicada a US$210M; ingresos post-adquisición declinando",
            "interpretacion": "D&A elevada refleja base de activos adquiridos, pero ingresos cayendo sugiere retorno dudoso."
          }
        ],
        "falsacion": {
          "test": "Impairment de activos >US$150M o write-down de goodwill asociado a adquisición",
          "ventana_meses": {
            "min": 6,
            "max": 24
          },
          "fuente_prevista": "filing",
          "accion_si_falla": "REVISAR_COMITE"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT03"
          },
          {
            "agent_role": "FORENSIC",
            "claim_id": "CLM_006"
          }
        ],
        "notas_arbitro": "Consenso codex y claude. Forensic asigna p=0.42 a impairment >US$50M. Sin desglose de goodwill, el riesgo es real pero no cuantificable."
      },
      {
        "assumption_id": "A-009",
        "enunciado": "Las reservas 1P/2P de KAR tienen vida útil >7 años con decline rates <20% anuales, haciendo que la valoración de run-off terminal sea excesiva.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.5,
        "confianza_0_1": 0.25,
        "impacto": "ALTO",
        "drivers_afectados": [
          "FCF",
          "CAPEX"
        ],
        "evidencias": [],
        "falsacion": {
          "test": "Reservas 2P reportadas con vida útil <5 años o decline rate >20% promedio ponderado",
          "ventana_meses": {
            "min": 3,
            "max": 12
          },
          "fuente_prevista": "filing",
          "accion_si_falla": "SALIR"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT06"
          },
          {
            "agent_role": "BULL",
            "claim_id": "CLM_F01"
          }
        ],
        "notas_arbitro": "NINGÚN agente ni modelo tiene datos de reservas. Es la prueba definitiva de run-off. Confianza 0.25 por ausencia total de evidencia. Identificado por claude; codex y gemini lo omiten como supuesto explícito pero lo mencionan en puntos abiertos."
      },
      {
        "assumption_id": "A-010",
        "enunciado": "El management evitará M&A destructivo y priorizará disciplina de capital, con potencial retorno de capital a accionistas en 12-18 meses.",
        "tipo": "HIPOTESIS",
        "criticidad": "IMPORTANTE",
        "probabilidad_0_1": 0.38,
        "confianza_0_1": 0.4,
        "impacto": "MEDIO",
        "drivers_afectados": [
          "MULTIPLO",
          "FCF",
          "OTRO"
        ],
        "evidencias": [
          {
            "source_id": "SRC_001",
            "ubicacion": "Cash Flow FY2024",
            "cita_corta": "CFF FY2024 -US$37.2M; no hay evidencia de buyback o dividendo material",
            "interpretacion": "Retorno actual mínimo vs capacidad (US$300M FCF). Ausencia de retorno es red flag."
          }
        ],
        "falsacion": {
          "test": "Anuncio de adquisición >US$100M sin programa simultáneo de retorno de capital",
          "ventana_meses": {
            "min": 1,
            "max": 24
          },
          "fuente_prevista": "PR",
          "accion_si_falla": "CONGELAR_COMPRAS"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT04"
          },
          {
            "agent_role": "CATALYST",
            "claim_id": "CAT_03"
          },
          {
            "agent_role": "BULL",
            "claim_id": "CLM_F03"
          }
        ],
        "notas_arbitro": "Consenso 3/3 modelos. Rango prob retorno de capital: [0.35, 0.40, 0.50]. Se usa 0.38 dada ausencia de señales."
      },
      {
        "assumption_id": "A-011",
        "enunciado": "La mejora de disclosure (EBIT, datos trimestrales completos) reducirá la prima de descuento de opacidad en el múltiplo.",
        "tipo": "INFERENCIA",
        "criticidad": "CONTEXTUAL",
        "probabilidad_0_1": 0.3,
        "confianza_0_1": 0.4,
        "impacto": "MEDIO",
        "drivers_afectados": [
          "MULTIPLO",
          "OTRO"
        ],
        "evidencias": [
          {
            "source_id": "ImpliedExpectations_v1",
            "ubicacion": "banderas",
            "cita_corta": "opacidad_alta: true; EBIT null en 5 periodos; historico trimestral 84% null",
            "interpretacion": "La falta de métricas estándar impide valoración institucional normal."
          }
        ],
        "falsacion": {
          "test": "No se publica EBIT ni mejora de completitud en 18 meses",
          "ventana_meses": {
            "min": 6,
            "max": 18
          },
          "fuente_prevista": "filing",
          "accion_si_falla": "REVISAR_COMITE"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "CATALYST",
            "claim_id": "CLM_06"
          },
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT05"
          }
        ],
        "notas_arbitro": "Consenso 3/3 modelos en prob baja (~0.30-0.33). Catalizador soft; no justifica entrada por sí solo."
      },
      {
        "assumption_id": "A-012",
        "enunciado": "La calidad de los beneficios es aceptable: el gap residual NI+D&A vs CFO (22% FY2024) se explica por partidas no-cash legítimas.",
        "tipo": "HIPOTESIS",
        "criticidad": "IMPORTANTE",
        "probabilidad_0_1": 0.6,
        "confianza_0_1": 0.45,
        "impacto": "MEDIO",
        "drivers_afectados": [
          "FCF"
        ],
        "evidencias": [
          {
            "source_id": "SRC_001",
            "ubicacion": "TruthPack FY2024",
            "cita_corta": "NI US$127.5M + D&A US$210M = US$337.5M vs CFO US$434.6M, gap US$97.1M (22.3%)",
            "interpretacion": "Gap supera umbral de 15%; probables ajustes de WC, impuestos diferidos o SBC."
          }
        ],
        "falsacion": {
          "test": "Reconciliación detallada CFO muestra ajustes no-cash insostenibles o manipulativos >US$50M",
          "ventana_meses": {
            "min": 3,
            "max": 12
          },
          "fuente_prevista": "filing",
          "accion_si_falla": "REDUCIR_50"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "FORENSIC",
            "claim_id": "CLM_005"
          }
        ],
        "notas_arbitro": "Identificado por claude y codex. Sin desglose de reconciliación CFO, no se puede determinar origen del gap."
      },
      {
        "assumption_id": "A-013",
        "enunciado": "Los proyectos en desarrollo (Who Dat, Bauna/Patola) generarán producción incremental suficiente para compensar decline rates naturales en H2-2026.",
        "tipo": "HIPOTESIS",
        "criticidad": "IMPORTANTE",
        "probabilidad_0_1": 0.48,
        "confianza_0_1": 0.4,
        "impacto": "ALTO",
        "drivers_afectados": [
          "FCF",
          "CAPEX"
        ],
        "evidencias": [
          {
            "source_id": "SRC_006",
            "ubicacion": "Investor Presentation strategy overview",
            "cita_corta": "Who Dat optimization strategy; Brazil growth options mentioned",
            "interpretacion": "Proyectos existen pero sin KPIs concretos ni timeline confirmado."
          }
        ],
        "falsacion": {
          "test": "Ingresos trimestrales no superan US$170M en ningún trimestre de 2026",
          "ventana_meses": {
            "min": 6,
            "max": 18
          },
          "fuente_prevista": "earnings",
          "accion_si_falla": "REDUCIR_50"
        },
        "dependencias": [
          "A-001",
          "A-009"
        ],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "CATALYST",
            "claim_id": "CLM_07"
          },
          {
            "agent_role": "BULL",
            "claim_id": "CLM_F02"
          }
        ],
        "notas_arbitro": "Rango prob modelos: [0.45, 0.48, 0.55]. Sin datos de producción por activo ni decline rates, altamente especulativo."
      },
      {
        "assumption_id": "A-014",
        "enunciado": "No existen covenants financieros que se activen con la caída actual, ni vencimientos concentrados de deuda en 12-18 meses.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.55,
        "confianza_0_1": 0.35,
        "impacto": "ALTO",
        "drivers_afectados": [
          "COSTE_DEUDA",
          "OTRO"
        ],
        "evidencias": [
          {
            "source_id": "AgentReport_v1_FORENSIC",
            "ubicacion": "peticiones_de_fuentes y limitaciones",
            "cita_corta": "Sin calendario de vencimientos ni covenants con headroom",
            "interpretacion": "La ausencia de disclosure impide confirmar plenamente el riesgo de refinanciación."
          }
        ],
        "falsacion": {
          "test": "Se reporta breach covenant, waiver o cobertura de vencimientos <=1.0x",
          "ventana_meses": {
            "min": 1,
            "max": 24
          },
          "fuente_prevista": "filing",
          "accion_si_falla": "SALIR"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "FORENSIC",
            "claim_id": "CLM_007"
          },
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT05"
          }
        ],
        "notas_arbitro": "Codex lo eleva a bloqueador principal para INVERTIR. Rango prob: [0.45, 0.55, 0.65]. Confianza muy baja por ausencia total de datos."
      },
      {
        "assumption_id": "A-015",
        "enunciado": "El mercado re-ratificará el múltiplo de KAR de 4.1x EV/FCF hacia 5.5-6.5x si se confirma normalización de capex y estabilización de ingresos.",
        "tipo": "HIPOTESIS",
        "criticidad": "IMPORTANTE",
        "probabilidad_0_1": 0.43,
        "confianza_0_1": 0.4,
        "impacto": "ALTO",
        "drivers_afectados": [
          "MULTIPLO"
        ],
        "evidencias": [
          {
            "source_id": "ImpliedExpectations_v1",
            "ubicacion": "multiples_implicitos",
            "cita_corta": "EV/FCF 4.13x; FCF yield 24.06%",
            "interpretacion": "Múltiplo extremo incluso para E&P offshore si FCF se demuestra sostenible."
          }
        ],
        "falsacion": {
          "test": "EV/FCF permanece <5.5x durante 18 meses pese a estabilización operativa demostrada",
          "ventana_meses": {
            "min": 6,
            "max": 18
          },
          "fuente_prevista": "precio",
          "accion_si_falla": "REVISAR_COMITE"
        },
        "dependencias": [
          "A-001",
          "A-002",
          "A-003"
        ],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "BULL",
            "claim_id": "CLM_F01"
          },
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT05"
          }
        ],
        "notas_arbitro": "Rango prob modelos: [0.40, 0.43, 0.45]. Red Team asigna p=0.55 a que el múltiplo NO se expanda. Value traps en E&P pueden persistir años."
      }
    ]
  },
  "evidence_graph": {
    "version": "EvidenceGraph_v1",
    "nodos": [
      {
        "node_id": "E-001",
        "tipo": "EVIDENCIA",
        "label": "SRC_008: Capex FY2025 US$204M, Q3 $4.5M vs Q4 $44M",
        "ref": {
          "source_id": "SRC_008"
        }
      },
      {
        "node_id": "E-002",
        "tipo": "EVIDENCIA",
        "label": "SRC_001: Capex FY2024 US$134.7M, FCF US$300M",
        "ref": {
          "source_id": "SRC_001"
        }
      },
      {
        "node_id": "E-003",
        "tipo": "EVIDENCIA",
        "label": "SRC_008: Ingresos FY2025 US$628M (-19%), Q4 US$156M",
        "ref": {
          "source_id": "SRC_008"
        }
      },
      {
        "node_id": "E-004",
        "tipo": "EVIDENCIA",
        "label": "SRC_001: Caja US$341M, deuda US$333.5M, leases US$177.7M",
        "ref": {
          "source_id": "SRC_001"
        }
      },
      {
        "node_id": "E-005",
        "tipo": "EVIDENCIA",
        "label": "SRC_001: CFO US$434.6M, margen bruto 48.82%",
        "ref": {
          "source_id": "SRC_001"
        }
      },
      {
        "node_id": "E-006",
        "tipo": "EVIDENCIA",
        "label": "ImpliedExp: FCF CAGR implícito -19% a -28% en 24/24 combinaciones",
        "ref": {
          "source_id": "ImpliedExpectations_v1"
        }
      },
      {
        "node_id": "E-007",
        "tipo": "EVIDENCIA",
        "label": "SRC_001: D&A US$210M (cuadruplicada), NI US$127.5M, gap NI+D&A vs CFO 22%",
        "ref": {
          "source_id": "SRC_001"
        }
      },
      {
        "node_id": "E-008",
        "tipo": "EVIDENCIA",
        "label": "SRC_001: CFI TY2023 -US$728M (adquisición)",
        "ref": {
          "source_id": "SRC_001"
        }
      },
      {
        "node_id": "E-009",
        "tipo": "EVIDENCIA",
        "label": "Opacidad: EBIT ausente 5 periodos, trimestrales 84% null",
        "ref": {
          "source_id": "ImpliedExpectations_v1"
        }
      },
      {
        "node_id": "A-001",
        "tipo": "SUPUESTO",
        "label": "Capex se normaliza a US$130-150M en FY2026",
        "ref": {
          "assumption_id": "A-001"
        }
      },
      {
        "node_id": "A-002",
        "tipo": "SUPUESTO",
        "label": "Ingresos se estabilizan >US$150M trimestral",
        "ref": {
          "assumption_id": "A-002"
        }
      },
      {
        "node_id": "A-003",
        "tipo": "SUPUESTO",
        "label": "FCF FY2025 >US$100M",
        "ref": {
          "assumption_id": "A-003"
        }
      },
      {
        "node_id": "A-005",
        "tipo": "SUPUESTO",
        "label": "Leases elevan deuda neta ajustada a US$170M",
        "ref": {
          "assumption_id": "A-005"
        }
      },
      {
        "node_id": "A-009",
        "tipo": "SUPUESTO",
        "label": "Reservas con vida >7 años",
        "ref": {
          "assumption_id": "A-009"
        }
      },
      {
        "node_id": "A-014",
        "tipo": "SUPUESTO",
        "label": "Sin stress de covenants/vencimientos",
        "ref": {
          "assumption_id": "A-014"
        }
      },
      {
        "node_id": "A-015",
        "tipo": "SUPUESTO",
        "label": "Re-rating de múltiplo hacia 5.5-6.5x",
        "ref": {
          "assumption_id": "A-015"
        }
      },
      {
        "node_id": "C-001",
        "tipo": "CATALIZADOR",
        "label": "Normalización Capex post-ciclo",
        "ref": {
          "catalyst_id": "C-001"
        }
      },
      {
        "node_id": "C-002",
        "tipo": "CATALIZADOR",
        "label": "Ramp-up producción Who Dat/Brasil",
        "ref": {
          "catalyst_id": "C-002"
        }
      },
      {
        "node_id": "C-003",
        "tipo": "CATALIZADOR",
        "label": "Retorno de capital / disciplina",
        "ref": {
          "catalyst_id": "C-003"
        }
      },
      {
        "node_id": "C-004",
        "tipo": "CATALIZADOR",
        "label": "Recuperación precios commodities",
        "ref": {
          "catalyst_id": "C-004"
        }
      },
      {
        "node_id": "SC-BASE",
        "tipo": "ESCENARIO",
        "label": "Escenario BASE: normalización + estabilización",
        "ref": {
          "scenario_id": "BASE"
        }
      },
      {
        "node_id": "SC-BULL",
        "tipo": "ESCENARIO",
        "label": "Escenario BULL: normalización agresiva + crecimiento",
        "ref": {
          "scenario_id": "BULL"
        }
      },
      {
        "node_id": "SC-BEAR",
        "tipo": "ESCENARIO",
        "label": "Escenario BEAR: capex estructural + decline continuo",
        "ref": {
          "scenario_id": "BEAR"
        }
      },
      {
        "node_id": "D-001",
        "tipo": "DECISION",
        "label": "Decisión: WATCHLIST",
        "ref": {
          "decision": "WATCHLIST"
        }
      }
    ],
    "aristas": [
      {
        "from": "E-001",
        "to": "A-001",
        "relacion": "SOPORTA",
        "peso_0_1": 0.55,
        "nota": "Patrón Q3/Q4 sugiere capex de proyecto, pero tendencia 4 años es creciente."
      },
      {
        "from": "E-002",
        "to": "A-001",
        "relacion": "SOPORTA",
        "peso_0_1": 0.6,
        "nota": "FY2024 como referencia pre-ciclo de capex normalizado."
      },
      {
        "from": "E-003",
        "to": "A-002",
        "relacion": "SOPORTA",
        "peso_0_1": 0.4,
        "nota": "Tendencia descendente Q3→Q4 no soporta estabilización; evidencia mixta."
      },
      {
        "from": "E-004",
        "to": "A-005",
        "relacion": "SOPORTA",
        "peso_0_1": 0.9,
        "nota": "Datos de balance y leases verificados en TruthPack."
      },
      {
        "from": "E-005",
        "to": "A-003",
        "relacion": "SOPORTA",
        "peso_0_1": 0.6,
        "nota": "Margen alto sugiere CFO resiliente, pero FY2025 no auditado."
      },
      {
        "from": "E-006",
        "to": "SC-BEAR",
        "relacion": "INFORMA",
        "peso_0_1": 0.75,
        "nota": "Expectativas implícitas del mercado son extremadamente negativas."
      },
      {
        "from": "E-007",
        "to": "A-008",
        "relacion": "SOPORTA",
        "peso_0_1": 0.45,
        "nota": "D&A cuadruplicada post-adquisición crea riesgo de impairment."
      },
      {
        "from": "E-009",
        "to": "A-014",
        "relacion": "SOPORTA",
        "peso_0_1": 0.8,
        "nota": "Sin disclosure de covenants no se audita riesgo completo."
      },
      {
        "from": "A-001",
        "to": "C-001",
        "relacion": "DEPENDE_DE",
        "peso_0_1": 0.9,
        "nota": "El catalizador principal ES la normalización de capex."
      },
      {
        "from": "C-001",
        "to": "A-001",
        "relacion": "DISPARA",
        "peso_0_1": 0.9,
        "nota": "Guidance de capex valida o invalida el supuesto central."
      },
      {
        "from": "C-002",
        "to": "A-002",
        "relacion": "DISPARA",
        "peso_0_1": 0.65,
        "nota": "Producción incremental puede estabilizar ingresos."
      },
      {
        "from": "C-003",
        "to": "A-015",
        "relacion": "DISPARA",
        "peso_0_1": 0.55,
        "nota": "Retorno de capital/disclosure favorece rerating."
      },
      {
        "from": "A-001",
        "to": "SC-BASE",
        "relacion": "DEPENDE_DE",
        "peso_0_1": 0.9,
        "nota": "BASE necesita capex normalizado."
      },
      {
        "from": "A-002",
        "to": "SC-BASE",
        "relacion": "DEPENDE_DE",
        "peso_0_1": 0.8,
        "nota": "Sin estabilización de ingresos el BASE no se sostiene."
      },
      {
        "from": "A-005",
        "to": "SC-BEAR",
        "relacion": "SOPORTA",
        "peso_0_1": 0.6,
        "nota": "Leases reducen margen de seguridad real y agravan downside."
      },
      {
        "from": "A-014",
        "to": "SC-BEAR",
        "relacion": "DEPENDE_DE",
        "peso_0_1": 0.6,
        "nota": "Covenants/vencimientos opacos incrementan riesgo de cola."
      },
      {
        "from": "SC-BASE",
        "to": "D-001",
        "relacion": "INFORMA",
        "peso_0_1": 0.75,
        "nota": "Base case positivo pero dependiente de catalizadores no confirmados."
      },
      {
        "from": "SC-BULL",
        "to": "D-001",
        "relacion": "INFORMA",
        "peso_0_1": 0.45,
        "nota": "Upside existe pero requiere confirmaciones aún no observadas."
      },
      {
        "from": "SC-BEAR",
        "to": "D-001",
        "relacion": "INFORMA",
        "peso_0_1": 0.8,
        "nota": "Bear probability significativa (35%) justifica WATCHLIST con sizing 0."
      }
    ],
    "validacion_grafo": {
      "ids_unicos": true,
      "aristas_referencian_nodos_existentes": true,
      "supuestos_criticos_tienen_falsacion": true,
      "detalle": "Grafo fusionado con nodos y aristas de los 3 modelos. Todos los supuestos CRITICO tienen falsación definida."
    }
  },
  "catalizadores_consolidados": [
    {
      "catalyst_id": "C-001",
      "nombre": "Normalización de Capex post-ciclo de desarrollo",
      "es_no_binario": true,
      "ventana_meses": {
        "min": 6,
        "probable": 12,
        "max": 18
      },
      "probabilidad_0_1": 0.6,
      "mecanismo_cierre_gap": "Si capex vuelve a US$130-150M, FCF se expande mecánicamente en US$50-70M sin crecimiento de ingresos, contradeciendo directamente la narrativa de deterioro permanente descontada al 4.1x EV/FCF.",
      "supuestos_afectados": [
        "A-001",
        "A-003",
        "A-015"
      ],
      "tests_confirmatorios": [
        {
          "descripcion": "Guidance capex FY2026 <US$160M con desglose mantenimiento vs desarrollo",
          "fuente_prevista": "earnings",
          "ventana_meses": {
            "min": 3,
            "max": 12
          }
        },
        {
          "descripcion": "Capex trimestral promedio <US$35M en H1-2026 (run-rate <US$140M)",
          "fuente_prevista": "earnings",
          "ventana_meses": {
            "min": 3,
            "max": 9
          }
        }
      ]
    },
    {
      "catalyst_id": "C-002",
      "nombre": "Ramp-up producción Who Dat y Brasil",
      "es_no_binario": true,
      "ventana_meses": {
        "min": 6,
        "probable": 15,
        "max": 24
      },
      "probabilidad_0_1": 0.5,
      "mecanismo_cierre_gap": "Producción incremental revierte tendencia de ingresos, invalidando la tesis de run-off del mercado y forzando re-rating del múltiplo.",
      "supuestos_afectados": [
        "A-002",
        "A-013"
      ],
      "tests_confirmatorios": [
        {
          "descripcion": "Ingresos trimestrales >US$170M sostenidos 2 trimestres en 2026",
          "fuente_prevista": "earnings",
          "ventana_meses": {
            "min": 6,
            "max": 18
          }
        },
        {
          "descripcion": "Producción por activo reporta mejora YoY y uptime operativo >95%",
          "fuente_prevista": "kpi_operativo",
          "ventana_meses": {
            "min": 6,
            "max": 24
          }
        }
      ]
    },
    {
      "catalyst_id": "C-003",
      "nombre": "Retorno de capital a accionistas y disciplina de capital",
      "es_no_binario": true,
      "ventana_meses": {
        "min": 6,
        "probable": 15,
        "max": 24
      },
      "probabilidad_0_1": 0.36,
      "mecanismo_cierre_gap": "Señaliza disciplina de capital y confianza del management en sostenibilidad del FCF, reduciendo descuento de value trap y prima de opacidad.",
      "supuestos_afectados": [
        "A-010",
        "A-011",
        "A-015"
      ],
      "tests_confirmatorios": [
        {
          "descripcion": "Anuncio de buyback >US$50M o dividendo yield >3%",
          "fuente_prevista": "PR",
          "ventana_meses": {
            "min": 6,
            "max": 18
          }
        },
        {
          "descripcion": "Reporte de EBIT en al menos 2 publicaciones consecutivas",
          "fuente_prevista": "filing",
          "ventana_meses": {
            "min": 6,
            "max": 18
          }
        }
      ]
    },
    {
      "catalyst_id": "C-004",
      "nombre": "Estabilización o recuperación de precios de commodities",
      "es_no_binario": true,
      "ventana_meses": {
        "min": 3,
        "probable": 9,
        "max": 18
      },
      "probabilidad_0_1": 0.45,
      "mecanismo_cierre_gap": "Mejora de precio realizado revierte caída de ingresos sin necesidad de volumen incremental. Cada US$5/bbl genera ~US$30-50M FCF incremental por apalancamiento operativo.",
      "supuestos_afectados": [
        "A-002",
        "A-006"
      ],
      "tests_confirmatorios": [
        {
          "descripcion": "Precio realizado por barril superior al promedio FY2025 durante 2 trimestres",
          "fuente_prevista": "earnings",
          "ventana_meses": {
            "min": 3,
            "max": 12
          }
        }
      ]
    }
  ],
  "escenarios": [
    {
      "scenario_id": "BASE",
      "probabilidad_0_1": 0.45,
      "ventana_meses": {
        "min": 6,
        "probable": 15,
        "max": 24
      },
      "descripcion": "Capex se normaliza a ~US$140-150M en FY2026. Ingresos se estabilizan en US$580-630M. CFO comprimido proporcionalmente a ~US$330-370M. FCF se recupera a US$190-230M. Mercado reconoce gradualmente que el run-off no se materializa y re-ratifica hacia 5.5-6.5x EV/FCF.",
      "drivers_clave": [
        "A-001",
        "A-002",
        "A-003",
        "A-007"
      ],
      "retorno_12_24m_pct_rango": {
        "min": 5,
        "base": 25,
        "max": 42
      },
      "nota_valoracion": "Asume rerating parcial a ~6x EV/FCF. FCF normalizado US$210M × 6.0x = EV US$1,260M. Con FCF acumulado, retorno base ~25%. Consenso 3/3 modelos en retorno base 22-25%."
    },
    {
      "scenario_id": "BULL",
      "probabilidad_0_1": 0.2,
      "ventana_meses": {
        "min": 9,
        "probable": 18,
        "max": 30
      },
      "descripcion": "Capex se normaliza agresivamente (<US$130M). Producción incremental de Who Dat y Brasil revierte tendencia de ingresos (>US$650M). Management anuncia retorno de capital significativo. Múltiplo re-ratifica a 7-9x EV/FCF.",
      "drivers_clave": [
        "A-001",
        "A-013",
        "A-010",
        "A-015"
      ],
      "retorno_12_24m_pct_rango": {
        "min": 40,
        "base": 70,
        "max": 105
      },
      "nota_valoracion": "Requiere materialización simultánea de al menos 2-3 catalizadores. Rango modelos base: [65, 70, 75]. Se usa 70."
    },
    {
      "scenario_id": "BEAR",
      "probabilidad_0_1": 0.35,
      "ventana_meses": {
        "min": 3,
        "probable": 12,
        "max": 24
      },
      "descripcion": "Capex permanece alto (>US$170M) por necesidad estructural de reinversión offshore. Ingresos siguen cayendo a US$550-600M. FCF se comprime a US$100-150M. Value trap se confirma: múltiplo permanece deprimido. Posible impairment de activos adquiridos.",
      "drivers_clave": [
        "A-001",
        "A-002",
        "A-008",
        "A-009"
      ],
      "retorno_12_24m_pct_rango": {
        "min": -45,
        "base": -22,
        "max": -5
      },
      "nota_valoracion": "Rango modelos bear base: [-20, -22, -25]. Se usa -22. Caja neta protege contra insolvencia pero no contra destrucción de equity value. Rango P(bear) modelos: [0.30, 0.35, 0.40]. Se usa 0.35."
    }
  ],
  "kill_criteria_final": [
    {
      "kc_id": "KC-001",
      "relacionado_con_assumption_id": "A-002",
      "definicion": "Ingresos trimestrales <US$140M durante 2 trimestres consecutivos en FY2026.",
      "ventana_meses": {
        "min": 3,
        "max": 12
      },
      "fuente_prevista": "earnings",
      "accion": "SALIR",
      "severidad": "ALTA",
      "por_que": "Confirma aceleración del declive estructural más allá de la tendencia actual; la tesis de estabilización sería inválida."
    },
    {
      "kc_id": "KC-002",
      "relacionado_con_assumption_id": "A-003",
      "definicion": "FCF TTM (CFO - capex) negativo o inferior a US$50M durante 2 periodos consecutivos de reporte.",
      "ventana_meses": {
        "min": 6,
        "max": 18
      },
      "fuente_prevista": "earnings",
      "accion": "SALIR",
      "severidad": "ALTA",
      "por_que": "Invalida completamente la tesis de generador de caja; implica agotamiento de capacidad de autofinanciación."
    },
    {
      "kc_id": "KC-003",
      "relacionado_con_assumption_id": "A-001",
      "definicion": "Capex FY2026 guiado o reportado >=US$200M sin incremento de producción >10% YoY.",
      "ventana_meses": {
        "min": 6,
        "max": 18
      },
      "fuente_prevista": "earnings",
      "accion": "REDUCIR_50",
      "severidad": "ALTA",
      "por_que": "Confirma que el capex elevado es estructural y la normalización es ilusión. Degrada escenario BASE a improbable."
    },
    {
      "kc_id": "KC-004",
      "relacionado_con_assumption_id": "A-004",
      "definicion": "Caja <US$200M con deuda neta ajustada (deuda + leases - caja) / CFO TTM >1.5x durante 2 trimestres.",
      "ventana_meses": {
        "min": 6,
        "max": 24
      },
      "fuente_prevista": "filing",
      "accion": "SALIR",
      "severidad": "ALTA",
      "por_que": "Deterioro del principal activo de seguridad (liquidez) elimina colchón contra pérdida permanente de capital."
    },
    {
      "kc_id": "KC-005",
      "relacionado_con_assumption_id": "A-014",
      "definicion": "Breach de covenant financiero, solicitud de waiver, o emisión de equity >US$200M para financiar operaciones.",
      "ventana_meses": {
        "min": 1,
        "max": 24
      },
      "fuente_prevista": "filing",
      "accion": "SALIR",
      "severidad": "ALTA",
      "por_que": "Dispara riesgo financiero binario no compatible con mandato no especulativo."
    },
    {
      "kc_id": "KC-006",
      "relacionado_con_assumption_id": "A-008",
      "definicion": "Impairment de activos >US$150M o write-down de goodwill asociado a adquisición TY2023.",
      "ventana_meses": {
        "min": 6,
        "max": 24
      },
      "fuente_prevista": "filing",
      "accion": "REVISAR_COMITE",
      "severidad": "ALTA",
      "por_que": "Erosionaría ~20% del patrimonio, confirmaría destrucción de valor adquisitivo y podría activar covenants."
    },
    {
      "kc_id": "KC-007",
      "relacionado_con_assumption_id": "A-010",
      "definicion": "Anuncio de adquisición >US$100M sin programa simultáneo de retorno de capital al accionista.",
      "ventana_meses": {
        "min": 1,
        "max": 24
      },
      "fuente_prevista": "PR",
      "accion": "CONGELAR_COMPRAS",
      "severidad": "MEDIA",
      "por_que": "M&A sin retorno de capital confirma desalineación management-accionistas y perpetúa value trap."
    }
  ],
  "plan_monitorizacion": {
    "frecuencias": {
      "pulso_diario": {
        "activo": true,
        "que_mirar": [
          "Precio KAR vs umbral (stop -20%)",
          "Noticias corporativas en ASX",
          "Brent spot",
          "Anuncios regulatorios y PR"
        ]
      },
      "revision_semanal": {
        "activo": true,
        "que_mirar": [
          "Estado de supuestos críticos A-001 a A-005, A-009, A-014",
          "Avance de catalizadores C-001 a C-004",
          "Evolución de commodities y sentimiento E&P offshore"
        ]
      },
      "modo_evento": {
        "activo": true,
        "que_mirar": [
          "Annual Report FY2025 (prioridad máxima: CFO, FCF, EBIT, balance)",
          "Investor Presentation con guidance FY2026 de capex y producción",
          "Producción trimestral y reservas",
          "Anuncio de retorno de capital o M&A",
          "Earnings calls transcripts",
          "Covenants y vencimientos de deuda"
        ]
      }
    },
    "lista_de_checks_por_supuesto": [
      {
        "assumption_id": "A-001",
        "indicadores": [
          "Capex trimestral absoluto",
          "Guidance capex FY2026",
          "Split mantenimiento vs desarrollo",
          "Capex/ingresos"
        ],
        "fuente": "earnings",
        "frecuencia": "TRIMESTRAL"
      },
      {
        "assumption_id": "A-002",
        "indicadores": [
          "Ingresos trimestrales",
          "Run-rate anualizado",
          "Producción por activo si disponible"
        ],
        "fuente": "earnings",
        "frecuencia": "TRIMESTRAL"
      },
      {
        "assumption_id": "A-003",
        "indicadores": [
          "CFO trimestral y FY2025 auditado",
          "FCF = CFO - capex",
          "Margen FCF"
        ],
        "fuente": "earnings",
        "frecuencia": "TRIMESTRAL"
      },
      {
        "assumption_id": "A-005",
        "indicadores": [
          "Lease liabilities corriente y no corriente",
          "Deuda neta ajustada",
          "Pagos de lease vs generación de caja"
        ],
        "fuente": "filing",
        "frecuencia": "TRIMESTRAL"
      },
      {
        "assumption_id": "A-009",
        "indicadores": [
          "Reservas 1P/2P publicadas",
          "Decline rates por activo",
          "Vida útil de reservas"
        ],
        "fuente": "filing",
        "frecuencia": "TRIMESTRAL"
      },
      {
        "assumption_id": "A-014",
        "indicadores": [
          "Maturity ladder",
          "Headroom covenants",
          "Waivers o breaches"
        ],
        "fuente": "filing",
        "frecuencia": "TRIMESTRAL"
      },
      {
        "assumption_id": "A-008",
        "indicadores": [
          "Test de impairment",
          "Write-downs",
          "Notas de goodwill/intangibles"
        ],
        "fuente": "10-K",
        "frecuencia": "ANUAL"
      }
    ],
    "umbrales_alerta": [
      {
        "tipo": "PRECIO",
        "condicion": "Caída >20% desde precio actual o sin noticias explicativas",
        "accion": "REVISAR_COMITE",
        "severidad": "MEDIA"
      },
      {
        "tipo": "COMMODITY",
        "condicion": "Brent cae <US$60/bbl sostenido >30 días",
        "accion": "REVISAR_COMITE",
        "severidad": "ALTA"
      },
      {
        "tipo": "FCF",
        "condicion": "FCF TTM <=0 en dos trimestres",
        "accion": "REVISAR_COMITE",
        "severidad": "ALTA"
      },
      {
        "tipo": "BALANCE",
        "condicion": "Deuda neta ajustada >US$300M o caja <US$150M",
        "accion": "REVISAR_COMITE",
        "severidad": "ALTA"
      }
    ]
  },
  "predicciones_para_calibracion_consolidadas": [
    {
      "pred_id": "CP-001",
      "descripcion": "Capex FY2026 será reportado o guiado por debajo de US$160M.",
      "probabilidad_0_1": 0.6,
      "ventana_meses": {
        "min": 3,
        "max": 18
      },
      "criterio_validacion": "Guidance oficial o reporte anual con cifra de Capex FY2026 < US$160M.",
      "fuente_prevista": "earnings",
      "origen": [
        {
          "agent_role": "BULL",
          "pred_id": "PRED_F01"
        },
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_001"
        },
        {
          "agent_role": "FORENSIC",
          "pred_id": "PRED_005"
        }
      ]
    },
    {
      "pred_id": "CP-002",
      "descripcion": "FCF FY2025 auditado será inferior a US$200M.",
      "probabilidad_0_1": 0.68,
      "ventana_meses": {
        "min": 3,
        "max": 6
      },
      "criterio_validacion": "FCF (CFO - capex) < US$200M en annual report FY2025.",
      "fuente_prevista": "earnings",
      "origen": [
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_007"
        },
        {
          "agent_role": "FORENSIC",
          "pred_id": "PRED_001"
        },
        {
          "agent_role": "RED_TEAM",
          "pred_id": "PRED_RT06"
        }
      ]
    },
    {
      "pred_id": "CP-003",
      "descripcion": "KAR reportará al menos un trimestre 2026 con ingresos >US$170M.",
      "probabilidad_0_1": 0.5,
      "ventana_meses": {
        "min": 3,
        "max": 12
      },
      "criterio_validacion": "Revenue trimestral 2026 >US$170M en al menos un periodo.",
      "fuente_prevista": "earnings",
      "origen": [
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_002"
        },
        {
          "agent_role": "BULL",
          "pred_id": "PRED_F04"
        }
      ]
    },
    {
      "pred_id": "CP-004",
      "descripcion": "KAR anunciará programa de retorno de capital (buyback o dividendo significativo >US$30M) en los próximos 12-18 meses.",
      "probabilidad_0_1": 0.39,
      "ventana_meses": {
        "min": 6,
        "max": 18
      },
      "criterio_validacion": "Comunicado oficial autorizando buyback o dividendo >US$30M.",
      "fuente_prevista": "PR",
      "origen": [
        {
          "agent_role": "BULL",
          "pred_id": "PRED_F03"
        },
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_004"
        },
        {
          "agent_role": "RED_TEAM",
          "pred_id": "PRED_RT04"
        }
      ]
    },
    {
      "pred_id": "CP-005",
      "descripcion": "KAR mantendrá posición de deuda neta negativa (caja >= deuda financiera) durante FY2026.",
      "probabilidad_0_1": 0.74,
      "ventana_meses": {
        "min": 6,
        "max": 18
      },
      "criterio_validacion": "Caja >= deuda total en balance sheet a cierre FY2026.",
      "fuente_prevista": "earnings",
      "origen": [
        {
          "agent_role": "BULL",
          "pred_id": "PRED_F06"
        },
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_006"
        }
      ]
    },
    {
      "pred_id": "CP-006",
      "descripcion": "EV/FCF de KAR superará 5.5x dentro de 18 meses.",
      "probabilidad_0_1": 0.43,
      "ventana_meses": {
        "min": 6,
        "max": 18
      },
      "criterio_validacion": "EV/FCF trailing >5.5x en cualquier punto del periodo.",
      "fuente_prevista": "precio",
      "origen": [
        {
          "agent_role": "BULL",
          "pred_id": "PRED_F05"
        },
        {
          "agent_role": "RED_TEAM",
          "pred_id": "PRED_RT05"
        }
      ]
    },
    {
      "pred_id": "CP-007",
      "descripcion": "Margen bruto FY2025 se mantendrá por encima de 42%.",
      "probabilidad_0_1": 0.59,
      "ventana_meses": {
        "min": 3,
        "max": 6
      },
      "criterio_validacion": "Gross profit / ingresos >= 42% en annual report FY2025.",
      "fuente_prevista": "earnings",
      "origen": [
        {
          "agent_role": "BULL",
          "pred_id": "PRED_F07"
        },
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_009"
        }
      ]
    },
    {
      "pred_id": "CP-008",
      "descripcion": "Caja al cierre del próximo periodo reportado se mantendrá >US$250M.",
      "probabilidad_0_1": 0.75,
      "ventana_meses": {
        "min": 3,
        "max": 6
      },
      "criterio_validacion": "Cash and equivalents > US$250M en balance sheet.",
      "fuente_prevista": "earnings",
      "origen": [
        {
          "agent_role": "FORENSIC",
          "pred_id": "PRED_003"
        }
      ]
    },
    {
      "pred_id": "CP-009",
      "descripcion": "Se registrará impairment >US$50M ligado a activos de TY2023.",
      "probabilidad_0_1": 0.42,
      "ventana_meses": {
        "min": 6,
        "max": 24
      },
      "criterio_validacion": "Cargo por deterioro >US$50M en filing anual/trimestral.",
      "fuente_prevista": "10-K",
      "origen": [
        {
          "agent_role": "FORENSIC",
          "pred_id": "PRED_006"
        }
      ]
    }
  ],
  "arbitraje": {
    "notas_arbitro": [
      "FUSIÓN 3 MODELOS (gemini, codex, claude): Convergencia total en decisión WATCHLIST con sizing 0%. Los 3 modelos coinciden en los mismos bloqueadores verificables.",
      "Se prioriza la prudencia ante la falta de datos auditados FY2025, guidance FY2026 y datos de reservas.",
      "Se acepta la corrección de Red Team sobre leases (deuda ajustada) como consenso unánime de los 3 modelos.",
      "Se eleva survivability_gate de PASS (gemini/claude) a CONDITIONAL (codex) por la falta de covenants/vencimientos, adoptando el criterio más conservador.",
      "CONDICIONES PARA UPGRADE A INVERTIR: (a) FCF FY2025 >US$150M, (b) Guidance capex FY2026 <US$160M con desglose, (c) Reservas 2P con vida >7 años, (d) Covenants con headroom >20%.",
      "La probabilidad BEAR se fija en 0.35 (rango modelos: [0.30, 0.35, 0.40]) como valor intermedio."
    ],
    "desacuerdos_detectados": [
      {
        "tema": "Normalización de capex: transitorio vs estructural",
        "agentes": [
          {
            "agent_role": "BULL",
            "posicion": "Capex FY2025 es pico transitorio de desarrollo; FY2024 (US$135M) es nivel normalizado",
            "confianza_0_1": 0.73
          },
          {
            "agent_role": "RED_TEAM",
            "posicion": "Trayectoria de 4 años creciente es evidencia de necesidad estructural; cortar capex acelera decline",
            "confianza_0_1": 0.75
          }
        ],
        "resolucion_arbitro": {
          "estado": "NO_RESUELTO",
          "decision": "convertir_en_escenario",
          "por_que": "Sin guidance FY2026 ni desglose mantenimiento/desarrollo, ambas posiciones son plausibles. Consenso 3/3 modelos en dejar como escenario. Se refleja en P(BASE)=0.45 vs P(BEAR)=0.35.",
          "accion": "Esperar guidance de capex FY2026 y datos de producción por activo."
        }
      },
      {
        "tema": "Caja neta como margen de seguridad vs deuda ajustada por leases",
        "agentes": [
          {
            "agent_role": "BULL",
            "posicion": "Caja neta positiva (-US$7.7M) elimina riesgo de quiebra y otorga opcionalidad",
            "confianza_0_1": 0.93
          },
          {
            "agent_role": "RED_TEAM",
            "posicion": "Incluyendo leases (US$177.7M), deuda neta real es +US$170M; margen de seguridad es menor",
            "confianza_0_1": 0.9
          }
        ],
        "resolucion_arbitro": {
          "estado": "RESUELTO",
          "decision": "penalizar_tamaño",
          "por_que": "Consenso 3/3 modelos: se adopta métrica ajustada por leases. La caja excede la deuda financiera pero la deuda ajustada total es material. Se refleja en A-005 CONFIRMADO y scoring V_penalizacion.",
          "accion": "Todos los análisis de deuda neta incluyen leases. Gate de supervivencia fijado en CONDITIONAL."
        }
      },
      {
        "tema": "Probabilidad de value trap vs mispricing real",
        "agentes": [
          {
            "agent_role": "RED_TEAM",
            "posicion": "Probabilidad value trap 0.60; patrón clásico de E&P offshore barato que permanece barato",
            "confianza_0_1": 0.72
          },
          {
            "agent_role": "BULL",
            "posicion": "FCF yield 24% es excesivo; normalización de capex rompe el patrón de value trap",
            "confianza_0_1": 0.65
          }
        ],
        "resolucion_arbitro": {
          "estado": "NO_RESUELTO",
          "decision": "convertir_en_escenario",
          "por_que": "La probabilidad de value trap depende de A-001 (capex) y A-009 (reservas), ambos no resueltos. Se asigna P(BEAR)=0.35. Kill criteria KC-001 a KC-005 detectarían value trap en formación.",
          "accion": "Monitorizar kill criteria. Resolución empírica con datos FY2025-FY2026."
        }
      },
      {
        "tema": "Calidad de disclosure y impacto en múltiplo",
        "agentes": [
          {
            "agent_role": "BULL",
            "posicion": "Mejora de disclosure podría reratear múltiplo",
            "confianza_0_1": 0.63
          },
          {
            "agent_role": "FORENSIC",
            "posicion": "Opacidad actual impide validar calidad de earnings; puede ser deliberada",
            "confianza_0_1": 0.7
          }
        ],
        "resolucion_arbitro": {
          "estado": "NO_RESUELTO",
          "decision": "pedir_fuente",
          "por_que": "Falta EBIT y series trimestrales completas; sin estos datos no se cierra el desacuerdo. Consenso 3/3 modelos en solicitar fuentes.",
          "accion": "Solicitar líneas de EBIT, acciones diluidas y reconciliaciones detalladas."
        }
      }
    ],
    "puntos_abiertos": [
      "FCF FY2025 auditado: dato más crítico pendiente. Sin él, toda la tesis es inferencia sobre FY2024.",
      "Guidance de capex FY2026 y desglose mantenimiento vs desarrollo: resuelve el desacuerdo central.",
      "Reservas 1P/2P con vida útil y decline rates: prueba definitiva de si el mercado tiene razón con run-off.",
      "Producción por activo (Who Dat, Bauna/Patola): valida o invalida ramp-up de producción.",
      "Precio realizado por barril: separa efecto precio vs volumen en caída de ingresos.",
      "Covenants y vencimientos de deuda: riesgo no cuantificable por ausencia de datos.",
      "EBIT/Operating Income: resolución de opacidad contable y prima de descuento.",
      "Política de retorno de capital del management: señal de alineación o desalineación.",
      "Obligaciones de desmantelamiento (decommissioning): pasivo contingente potencialmente material.",
      "Calidad del gap NI+D&A vs CFO (22%): partidas no-cash legítimas o señal de manipulación."
    ]
  },
  "peticiones_de_fuentes": [
    {
      "prioridad": "ALTA",
      "item": "Annual Report FY2025 completo (CFO, FCF, NI, EBIT, balance sheet)",
      "por_que_importa": "Sin este dato, la tesis entera se basa en FY2024 como proxy. Es el dato más crítico para validar o refutar la tesis.",
      "como_obtenerlo": "ASX announcements, KAR investor relations, annual report filing."
    },
    {
      "prioridad": "ALTA",
      "item": "Guidance de capex FY2026 con desglose mantenimiento vs desarrollo",
      "por_que_importa": "Resuelve el desacuerdo central entre Bull y Red Team; confirma o invalida el catalizador principal.",
      "como_obtenerlo": "Investor Presentation FY2025, earnings call transcript, sección outlook."
    },
    {
      "prioridad": "ALTA",
      "item": "Tabla de vencimientos de deuda y covenants con headroom",
      "por_que_importa": "Necesaria para cerrar survivability_gate de CONDITIONAL a PASS.",
      "como_obtenerlo": "Notas de deuda, credit agreement y sección de liquidez en filing."
    },
    {
      "prioridad": "ALTA",
      "item": "Reporte de Reservas 1P/2P con vida útil y decline rates por activo",
      "por_que_importa": "Prueba definitiva de si la valoración de run-off es correcta o excesiva.",
      "como_obtenerlo": "Annual Report sección reservas, competent person's report, ASX continuous disclosure."
    },
    {
      "prioridad": "ALTA",
      "item": "Producción por activo (Who Dat, Bauna/Patola) en boepd y uptime FPSO",
      "por_que_importa": "Permite separar volumen vs precio en caída de ingresos y evaluar ramp-up.",
      "como_obtenerlo": "Quarterly production report, ASX announcements."
    },
    {
      "prioridad": "ALTA",
      "item": "Precio realizado por barril y política de hedging",
      "por_que_importa": "Aísla componente precio vs volumen; calibra sensibilidad del FCF al commodity.",
      "como_obtenerlo": "Annual Report sección revenue by commodity, notas de derivados."
    },
    {
      "prioridad": "MEDIA",
      "item": "Línea de EBIT/Operating Income y acciones diluidas",
      "por_que_importa": "Reduce opacidad y permite triangulación operativa estándar.",
      "como_obtenerlo": "Income statement consolidado y nota de EPS en filing."
    },
    {
      "prioridad": "MEDIA",
      "item": "Política formal de asignación de capital (retorno a accionistas vs M&A)",
      "por_que_importa": "Define probabilidad de rerating por gobernanza de capital.",
      "como_obtenerlo": "PR corporativo, transcript de resultados, marco de capital allocation."
    }
  ],
  "salida_para_siguiente_agente": {
    "monitor_input_recomendado": "Usar este DecisionPacket_v2 fusionado como entrada base del Monitor. Foco en: (1) Annual Report FY2025 cuando se publique, (2) Guidance capex FY2026, (3) Reservas y producción, (4) Kill criteria KC-001 a KC-007.",
    "estado_caso": "EN_ESPERA",
    "proxima_revision_sugerida": "2026-05-15"
  },
  "log": {
    "autochequeos": {
      "decision_respeta_gates": true,
      "supuestos_criticos_tienen_evidencia": true,
      "supuestos_criticos_tienen_falsacion": true,
      "kill_criteria_mapeados_a_supuestos": true,
      "salida_solo_json": true,
      "_comment_v2_checks": "NUEVO EN V2: checks probabilísticos",
      "probabilidades_escenarios_suman_1": true,
      "kelly_sizing_dentro_de_tope": true,
      "intervalo_confianza_coherente_con_escenarios": true,
      "decision_categorica_coherente_con_probabilistica": true,
      "sizing_final_igual_preliminar_si_invertir": true,
      "sensibilidad_cubre_supuestos_criticos": true
    },
    "limitaciones": [
      "FY2025 en input no incluye CFO/FCF auditados; solo datos de investor presentation.",
      "EBIT no disponible en ningún periodo; margen operativo y ROIC no calculables.",
      "Sin datos de reservas, producción por activo ni decline rates; evaluación de run-off es inferencial.",
      "Sin tabla de vencimientos de deuda ni covenants; riesgo de refinanciación no cuantificable.",
      "Histórico trimestral con 84% incompletitud; estacionalidad y tendencia granular no evaluables.",
      "Sin datos de precio realizado por barril; separación precio/volumen en caída de ingresos es genérica.",
      "Signos inconsistentes en P&L entre periodos limitan reconstrucción fiable de EBIT.",
      "Metadatos de empresa (bolsa ASX, país AU) inferidos por claude, no del TruthPack directamente."
    ],
    "revision": {
      "es_revision": false,
      "revision_num": 1,
      "decision_packet_anterior_caso_id": null,
      "monitoring_updates_usados": [],
      "resumen_cambios": [
        "Primera emisión DecisionPacket_v2 fusionado para CASE_20260222_KAR.",
        "Fusión de 3 modelos (gemini, codex, claude) con convergencia total en WATCHLIST.",
        "Bloque probabilístico completo y análisis de sensibilidad fusionados.",
        "Decisión categórica final: WATCHLIST con sizing final 0%."
      ]
    }
  },
  "control": {
    "estado_flujo": "ARBITRATE",
    "next_step": "MONITOR",
    "next_agent_role": "MONITOR",
    "loop_budget_max": 2,
    "loop_budget_restante": 2,
    "issues": [],
    "work_orders": [],
    "dispatch_queue": []
  },
  "_meta": {
    "fusion": {
      "modelos_usados": [
        "gemini",
        "codex",
        "claude"
      ],
      "criterios_de_resolucion": [
        "Decisión categórica: unanimidad 3/3 en WATCHLIST → se adopta WATCHLIST.",
        "Datos cuantitativos: cuando coinciden se usan directamente; cuando difieren se usa mediana o valor más evidenciado.",
        "Probabilidades de escenarios: rango cruzado de 3 modelos; se usa mediana ponderada por evidencia.",
        "Gates: se adopta el criterio más conservador (survivability CONDITIONAL de codex prevalece sobre PASS de gemini/claude).",
        "Supuestos: se fusionan los 15 supuestos únicos identificados entre los 3 modelos, eliminando duplicados.",
        "Kill criteria: unión de todos los kill criteria, priorizando los más estrictos para cada supuesto.",
        "Empresa metadata: claude proporciona bolsa ASX y país AU con mayor especificidad que UNKNOWN de gemini/codex.",
        "Scoring: mediana de los 3 scores (53, 60, 61) = 57.",
        "Confianza global: rango [0.54, 0.68, 0.68] → 0.58 como valor conservador ponderado por calidad de argumentación."
      ],
      "conflictos_detectados": [
        {
          "campo": "empresa.bolsa",
          "valores": {
            "gemini": "UNKNOWN",
            "codex": "UNKNOWN",
            "claude": "ASX"
          },
          "resolucion": "Se usa ASX de claude por ser más específico y coherente con Karoon Energy como empresa australiana."
        },
        {
          "campo": "empresa.nombre",
          "valores": {
            "gemini": "Karoon Energy Ltd",
            "codex": "UNKNOWN",
            "claude": "Karoon Energy"
          },
          "resolucion": "Se usa 'Karoon Energy Ltd' de gemini como nombre formal más completo."
        },
        {
          "campo": "confianza_global_0_1",
          "valores": {
            "gemini": 0.68,
            "codex": 0.68,
            "claude": 0.54
          },
          "resolucion": "Se usa 0.58 como valor conservador. Claude argumenta convincentemente que la opacidad contable y la ausencia de catalizador confirmado justifican confianza menor."
        },
        {
          "campo": "decision_probabilistica.probabilidad_exito_0_1",
          "valores": {
            "gemini": 0.65,
            "codex": 0.7,
            "claude": 0.6
          },
          "resolucion": "Se usa 0.65 (mediana). La probabilidad de éxito depende de catalizadores no confirmados."
        },
        {
          "campo": "escenarios.bear.probabilidad_0_1",
          "valores": {
            "gemini": 0.35,
            "codex": 0.3,
            "claude": 0.4
          },
          "resolucion": "Se usa 0.35 (mediana). Claude argumenta P(bear) más alta por opacidad y tendencia adversa; codex más optimista por balance."
        },
        {
          "campo": "escenarios.bull.probabilidad_0_1",
          "valores": {
            "gemini": 0.2,
            "codex": 0.2,
            "claude": 0.15
          },
          "resolucion": "Se usa 0.20 (consenso 2/3). Claude argumenta P(bull) menor por requerir 3+ catalizadores simultáneos."
        },
        {
          "campo": "gates.survivability_gate.status",
          "valores": {
            "gemini": "PASS",
            "codex": "CONDITIONAL",
            "claude": "PASS"
          },
          "resolucion": "Se usa CONDITIONAL (criterio más conservador de codex). La falta de covenants/vencimientos justifica no dar PASS limpio."
        },
        {
          "campo": "scoring_preliminar.total_0_100",
          "valores": {
            "gemini": 60,
            "codex": 61,
            "claude": 53
          },
          "resolucion": "Se usa 57 (mediana redondeada). Claude penaliza más por opacidad (Q=7 vs Q=5/10) y catalizador (C=11 vs C=12/14)."
        },
        {
          "campo": "assumption A-001 probabilidad_0_1",
          "valores": {
            "gemini": 0.6,
            "codex": 0.62,
            "claude": 0.55
          },
          "resolucion": "Se usa 0.58 (mediana). Claude más conservador por tendencia creciente de 4 años sin guidance."
        },
        {
          "campo": "proxima_revision_sugerida",
          "valores": {
            "gemini": "2026-05-30",
            "codex": "2026-05-31",
            "claude": "2026-04-30"
          },
          "resolucion": "Se usa 2026-05-15 como punto intermedio, permitiendo capturar annual report FY2025 si se publica en abril."
        },
        {
          "campo": "catalizadores C-004 (commodities)",
          "valores": {
            "gemini": "no incluido como catalizador separado",
            "codex": "no incluido como catalizador separado",
            "claude": "incluido como C-004"
          },
          "resolucion": "Se incluye como C-004. Claude lo argumenta con mecanismo cuantificable (US$5/bbl = US$30-50M FCF). Gemini y codex lo mencionan en supuestos pero no lo elevan a catalizador."
        }
      ]
    }
  }
}
```

---

## Solicitud de review

Revisa este caso aplicando los criterios definidos en las instrucciones del proyecto.

**Áreas de especial atención para este caso:**

- El gate "survivability_gate" es CONDITIONAL — evalúa si la justificación es suficiente para no bloquearlo

Recuerda finalizar tu análisis con el bloque JSON MetaReview_v1.
