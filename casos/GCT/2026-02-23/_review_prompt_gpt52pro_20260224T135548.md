# Meta-Review: GCT — 2026-02-23

## Contexto del caso
- Ticker: GCT
- Fecha de análisis: 2026-02-23
- Pipeline completado: 2026-02-24T10:36:30.569471+00:00
- Timestamp de compilación: 20260224T135548
- Modelos utilizados: gemini, codex, claude
- Decisión ARBITRO: WATCHLIST (score: 54/100, confianza: 0.57)

---

## Calidad del pipeline (quality votes)

> **Nota anti-sesgo:** Los scores de calidad son una señal de calidad formal del pipeline (validación de schema, completitud de campos, ratio de nulos). No son indicadores de verdad fundamental ni de calidad del razonamiento. Úsalos como contexto, no como juicio previo.

| Paso | Score fusión | Rango modelos |
|------|-------------|---------------|
| ARBITRO | 100.0 | 100–100 |
| BULL | 100.0 | 98–100 |
| CATALYST_DETECTION | 100.0 | 67–100 |
| CATALYST_SCORING | 99.8 | 98–100 |
| FORENSIC_DETECTION | 99.3 | 98–100 |
| FORENSIC_SCORING | 98.7 | 99–99 |
| IMPLIED | 99.2 | — |
| RED_TEAM | 100.0 | 99–100 |
| TP_EXTRACTOR_FILING | 53.3 | — |

---

## Perspectiva BULL

### Resumen ejecutivo
{"bullets": ["El mercado descuenta un colapso del FCF (-6% a -13% CAGR implícito), pero GCT genera caja récord ($126M YTD Q3-25, +41% YoY) y reduce G&A agresivamente (-44% Q3 YoY), con ingresos en máximos históricos ($333M Q3-2025).", "Cotiza a 8.8x P/FCF y 11.4% FCF yield con ~20% del market cap en caja neta ($260M) y sin deuda financiera material ($256K interest expense FY2024), ofreciendo margen de seguridad profundo.", "La normalización de G&A (de $74M FY2024 a run-rate ~$34M) añade $30-40M al EBIT anual, expandiendo margen operativo de 11.2% hacia 13-15%, lo que refuta la premisa de deterioro operativo del mercado.", "La tesis no requiere crecimiento agresivo: FCF estable (~$140M) con re-rating parcial del múltiplo a 11-12x genera retorno de +20-37% en 12-18 meses; recompras activas (~$58M en 9M-2025) aceleran FCF/share.", "Riesgos reales pero descontados: compresión de margen bruto (23.2% y descendente), lease liabilities ($484M vs patrimonio $405M), opacidad de gobernanza offshore y discrepancia de share count (~27%) requieren verificación en próximos filings."], "veredicto_role_local": "APTO", "confianza_0_1": 0.71}

### Claims principales (CRITICO + IMPORTANTE)
```json
[
  {
    "claim_id": "CLM_BULL_001",
    "enunciado": "La generación de caja operativa se está acelerando (+41% YTD 2025), desmintiendo la tesis de contracción del FCF descontada por el mercado.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_BULL_002",
    "enunciado": "La normalización de G&A es real y sostenida: $14M→$13M→$8.5M en Q1-Q3 2025 (run-rate ~$34M vs $74M FY2024), añadiendo $30-40M al EBIT anual y expandiendo margen operativo de 11.2% hacia 13-15%.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_BULL_003",
    "enunciado": "No hay evidencia de colapso comercial: los ingresos trimestrales de 2025 mantienen tendencia ascendente ($272M→$323M→$333M) con crecimiento YoY de +8-10%, refutando el escenario de contracción que justificaría P/FCF <9x.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_BULL_004",
    "enunciado": "A P/FCF de 8.8x, la tesis no requiere crecimiento para generar retorno: basta con que el FCF se mantenga estable (~$140M) y el múltiplo se normalice mínimamente hacia 11-12x para obtener +25-37%.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_BULL_005",
    "enunciado": "El balance es una fortaleza defensiva: $260M en caja, deuda financiera negligible ($256K interest expense) y >25 meses de cobertura de obligaciones de leasing corrientes eliminan riesgo de supervivencia en el horizonte de inversión.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_BULL_006",
    "enunciado": "Las recompras activas (~$58M CFF negativo en 9M-2025, ~8% market cap anualizado) a P/FCF <9x son potencialmente muy accretivas y aceleran la convergencia del precio hacia valor intrínseco, aunque requieren confirmación documental.",
    "criticidad": "IMPORTANTE"
  },
  {
    "claim_id": "CLM_BULL_007",
    "enunciado": "El descuento de valoración está explicado en gran parte por prima de riesgo cualitativa (gobernanza offshore, opacidad, leases) más que por deterioro operativo demostrado; la persistencia de resultados sólidos debería forzar compresión gradual de este descuento.",
    "criticidad": "IMPORTANTE"
  },
  {
    "claim_id": "CLM_BULL_008",
    "enunciado": "El margen bruto se ha estabilizado en 23-24% en 2025 sin deterioro adicional significativo; aunque no muestra expansión, el EBIT margin mejora por la vía de G&A, desacoplando la tesis de la evolución del margen bruto.",
    "criticidad": "IMPORTANTE"
  },
  {
    "claim_id": "CLM_BULL_009",
    "enunciado": "La adquisición de New Classic ($18M por ~$70M en ingresos, 0.26x ventas) aporta opcionalidad positiva accretiva, aunque no es necesaria para la tesis base.",
    "criticidad": "IMPORTANTE"
  }
]
```
---

## Perspectiva RED_TEAM

### Resumen ejecutivo
{"bullets": ["La compresión del margen bruto es estructural (26.8% FY2023 → 24.6% FY2024 → 23.2% Q3-2025): 360 bps de erosión en 2 años que neutraliza los ahorros en G&A y deja el margen neto estancado o en deterioro. Los tres modelos coinciden en que esto NO es estabilización.", "Las lease liabilities ($484M) superan el patrimonio ($405M) y funcionan como deuda real no reflejada en EV; ajustando, el EV/FCF real sube de 8.8x a ~10.3x, eliminando gran parte del 'descuento' aparente. Unanimidad de los tres modelos.", "La aceleración de CFO (+41% YTD) es frágil: depende de gestión de capital de trabajo (extensión de payables), la caja cayó $28M en H1-2025 pese al CFO, y sin desglose de AR/inventarios no se puede validar sostenibilidad. Coincidencia gemini-claude-codex.", "La discrepancia no resuelta del ~27% en share count (~7.8M acciones) y la estructura opaca offshore sugieren riesgo de dilución masiva y gobernanza deficiente que justifican plenamente el descuento de valoración persistente.", "La tesis de recompras accretivas es NO PROBADA: falta desglose de CFF, variación de acciones = null, y el CFF negativo de $58M puede ser mayoritariamente principal de leases. Unanimidad de los tres modelos.", "Riesgo Principal: VALUE_TRAP por deterioro de fundamentales (margen bruto), apalancamiento operativo oculto (leases), opacidad de gobernanza offshore, y ausencia de catalizadores duros de re-rating."], "veredicto_role_local": "NO_APTO", "confianza_0_1": 0.8}

### Claims principales (CRITICO + IMPORTANTE)
```json
[
  {
    "claim_id": "CLM_RT_001",
    "enunciado": "La compresión del margen bruto es estructural: ha caído de 26.8% (FY2023) a 24.6% (FY2024) a 23.2% (Q3-2025), una tendencia descendente de 360 bps en 2 años que indica pérdida de poder de fijación de precios o aumento de costes, no estabilización.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_RT_002",
    "enunciado": "Las lease liabilities de $484M superan el patrimonio de $405M, constituyendo la mayor obligación financiera de GCT. El ratio lease liabilities/equity de 1.20x indica apalancamiento real masivo invisible en métricas convencionales. El EV ajustado por leases sería ~$1,474M y el EV/FCF ~10.3x, no 8.8x.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_RT_003",
    "enunciado": "La aceleración de CFO (+41% YoY en 9M-2025) es frágil: depende desproporcionadamente de gestión de capital de trabajo (extensión de cuentas por pagar), delta_cash fue negativo en Q1 (-$8M) y Q2 (-$20M), y sin desglose de AR/inventarios no se puede validar calidad recurrente.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_RT_004",
    "enunciado": "La discrepancia de ~7.8M acciones (~27%) entre básicas y diluidas no está explicada y representa un riesgo de dilución material. Si se materializan, el FCF/share cae de $4.89 a ~$3.85 y el P/FCF real sube de 8.8x a ~11.2x. La tesis de recompras accretivas es NO PROBADA (variación_acciones_yoy_pct = null, CFF sin desglose).",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_RT_005",
    "enunciado": "La estructura corporativa offshore combinada con la opacidad sobre composición real de caja, deuda, share count, y la adquisición sospechosamente barata de New Classic ($18M por $70M ingresos = 0.26x ventas) crea un perfil de riesgo de gobernanza que justifica el descuento persistente del mercado.",
    "criticidad": "CRITICO"
  },
  {
    "claim_id": "CLM_RT_006",
    "enunciado": "La normalización de G&A de $74M (FY2024) a run-rate ~$34M puede ser parcialmente ilusoria: el salto de 146% en FY2024 no está explicado, parte puede ser SBC recurrente, y la gestión de una base de almacenes creciente ($452M ROU) requiere G&A creciente, no decreciente.",
    "criticidad": "IMPORTANTE"
  }
]
```
---

## Perspectiva CATALYST

### Resumen ejecutivo
{"bullets": ["Discrepancia extrema entre fundamentales y valoración: mercado descuenta caída de FCF (-6% a -13% CAGR), pero CFO YTD Q3-2025 crece +41% interanual ($126M vs $89M) y G&A se normaliza agresivamente (-44% YoY en Q3).", "Tres catalizadores de alta convicción (prob ≥0.70): normalización de G&A, recompras activas y sostenibilidad del FCF, todos con evidencia confirmada en trimestres recientes de 2025.", "El catalizador de mayor impacto potencial es la mejora de gobernanza (re-rating de +3x a +6x en P/FCF), pero su probabilidad es moderada (0.42) por complejidad estructural offshore y timing incierto.", "Caja neta masiva ($260M) sin deuda financiera material ofrece protección contra tesis bajista, opcionalidad de recompra (~8% market cap anualizado) y margen de seguridad amplio a 8.8x P/FCF.", "La calidad agregada del portafolio es MEDIA-ALTA: 5 de 9 catalizadores tienen probabilidad ≥0.58, pero faltantes críticos (deuda_total, EV, desglose de segmentos) y dependencia de resolución de percepciones cualitativas limitan la confianza total."], "veredicto_role_local": "APTO", "confianza_0_1": 0.68}

---

## Perspectiva FORENSIC

### Resumen ejecutivo
{"bullets": ["Supervivencia 12-24 meses clasificada PASS (score 3/5): caja de $260M, CFO FY2024 de $158M y deuda financiera aparentemente negligible (intereses $256K) proporcionan colchón amplio.", "Tres banderas rojas de severidad ALTA concentran el riesgo: volatilidad extrema EBIT→CFO (rango -78% a +42%), lease liabilities que superan patrimonio ($484M vs $405M) y explosión de G&A (+146% YoY).", "Compresión sostenida de márgenes en periodo de hipercrecimiento (margen bruto -220 bps a 24.6%, margen operativo -440 bps a 11.2%) es atípica para modelo de plataforma y señala posible deterioro de pricing power.", "Opacidad estructural: discrepancia de ~7.8M acciones (27%), transición 20-F→10-K, ausencia de datos clave (AR, inventarios, deuda total, SBC) limitan profundidad del análisis forense.", "Riesgo de 'value trap': múltiplos bajos (P/FCF 8.8x) podrían estar justificados por deterioro de márgenes y gobernanza offshore.", "Veredicto WATCHLIST: la solidez de caja y generación de FCF compensan riesgos estructurales a corto plazo, pero la trayectoria de márgenes, calidad de beneficios y gobernanza requieren monitoreo activo trimestral."], "veredicto_role_local": "WATCHLIST", "confianza_0_1": 0.68}

---

## DecisionPacket completo (ARBITRO)

```json
{
  "version_esquema": "DecisionPacket_v2",
  "backward_compatible_with": "DecisionPacket_v1",
  "caso_id": "CASE_20260223_GCT",
  "fecha_corte": "2026-02-23",
  "empresa": {
    "ticker": "GCT",
    "nombre": "GigaCloud Technology Inc",
    "bolsa": "NASDAQ",
    "pais": "US",
    "sector": "Technology",
    "industria": "Internet Services & Infrastructure"
  },
  "input_refs": {
    "sources_pack_caso_id": "CASE_20260223_GCT",
    "truth_pack_caso_id": "CASE_20260223_GCT",
    "implied_expectations_caso_id": "CASE_20260223_GCT",
    "agent_reports": [
      {
        "agent_role": "CATALYST",
        "agent_nombre": "CATALYST_SCORING_v1",
        "report_ref": "AgentReport_v1",
        "confianza_0_1": 0.68
      },
      {
        "agent_role": "FORENSIC",
        "agent_nombre": "FORENSIC_SCORING_v1",
        "report_ref": "AgentReport_v1",
        "confianza_0_1": 0.68
      },
      {
        "agent_role": "BULL",
        "agent_nombre": "BULL_FUSION_v1",
        "report_ref": "AgentReport_v1",
        "confianza_0_1": 0.71
      },
      {
        "agent_role": "RED_TEAM",
        "agent_nombre": "RED_TEAM_v1",
        "report_ref": "AgentReport_v1",
        "confianza_0_1": 0.8
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
    "confianza_global_0_1": 0.57,
    "racional_5_lineas": [
      "Existe un gap de expectativas: P/FCF ~8.8x con CFO YTD Q3-2025 +41% y G&A en normalización.",
      "Sin embargo, fallan bloqueadores críticos de calidad: deuda/EV no cerrados, desglose CFF incompleto y reconciliación de acciones pendiente.",
      "La compresión de margen bruto (26.8% a 23.2%) y el peso de leases ($484M vs $405M equity) mantienen riesgo material de value trap.",
      "La opacidad offshore y la accesibilidad de caja no verificada impiden convertir la asimetría teórica en sizing ejecutable.",
      "Se mantiene WATCHLIST con 0% hasta remediar datos críticos y re-arbitrar con evidencia de 10-K."
    ],
    "lo_mas_importante_ahora": [
      "Cerrar deuda_total_usd y enterprise_value_usd para validar múltiplos EV-based.",
      "Desglosar CFF 2025 (recompras vs principal de leases vs otros).",
      "Reconciliar acciones básicas/diluidas e instrumentos potencialmente dilutivos.",
      "Extraer AR/inventarios y puente de working capital para auditar la calidad del CFO.",
      "Confirmar accesibilidad de caja y vencimientos de leases 2026-2030."
    ],
    "principales_riesgos": [
      "Compresión estructural de margen bruto hacia niveles <22%.",
      "Dilución real oculta por discrepancia de share count (~27%).",
      "CFF negativo interpretado erróneamente como recompras sin prueba documental.",
      "Leverage operativo por leases elevado frente al patrimonio.",
      "Riesgo de gobernanza/offshore y descuento de múltiplo potencialmente persistente."
    ]
  },
  "decision_probabilistica": {
    "probabilidad_exito_0_1": 0.6,
    "retorno_esperado_ponderado_pct": 9.9,
    "escenarios_ponderados": {
      "base": {
        "probabilidad_0_1": 0.45,
        "retorno_estimado_pct": 18
      },
      "bull": {
        "probabilidad_0_1": 0.15,
        "retorno_estimado_pct": 65
      },
      "bear": {
        "probabilidad_0_1": 0.4,
        "retorno_estimado_pct": -20
      }
    },
    "sizing_kelly": {
      "kelly_crudo_pct": 15.6,
      "factor_ajuste_confianza": 0.4,
      "kelly_ajustado_pct": 6.2,
      "tope_maximo_pct": 10,
      "sizing_preliminar_pct": 6.2,
      "sizing_final_pct": 0,
      "nota": "Kelly preliminar es positivo, pero sizing final se fuerza a 0% por WATCHLIST y bloqueadores de data quality/no-speculative."
    },
    "intervalo_confianza_90_pct": {
      "percentil_5": -24,
      "percentil_50": 10,
      "percentil_95": 52
    },
    "conviccion_0_1": 0.57,
    "ratio_asimetria": 0.9,
    "expected_value_anualizado_pct": 7.9,
    "decision_categorica": "WATCHLIST"
  },
  "analisis_sensibilidad": [
    {
      "assumption_id": "A-003",
      "variable": "margen_bruto_pct",
      "valor_base": 23.5,
      "rango_test": {
        "min": 20,
        "max": 26,
        "paso": 1
      },
      "impacto_en_retorno_pct": {
        "si_min": -35,
        "si_max": 40
      },
      "impacto_en_decision": "Si margen bruto <22% en 2 trimestres consecutivos, pasa a DESCARTAR/SALIR.",
      "nota": "Variable más sensible y principal driver del escenario bear."
    },
    {
      "assumption_id": "A-001",
      "variable": "fcf_anual_usd_millones",
      "valor_base": 140,
      "rango_test": {
        "min": 90,
        "max": 180,
        "paso": 15
      },
      "impacto_en_retorno_pct": {
        "si_min": -30,
        "si_max": 45
      },
      "impacto_en_decision": "Si FCF <110M, se mantiene WATCHLIST/REDUCIR; si >160M con calidad de caja validada, candidato a INVERTIR.",
      "nota": "Sensibilidad directa sobre tesis de mispricing."
    },
    {
      "assumption_id": "A-004",
      "variable": "dilucion_acciones_pct",
      "valor_base": 10,
      "rango_test": {
        "min": 0,
        "max": 27,
        "paso": 5
      },
      "impacto_en_retorno_pct": {
        "si_min": 8,
        "si_max": -15
      },
      "impacto_en_decision": "Si dilución >20%, el descuento per share se erosiona y el caso deriva a DESCARTAR/REDUCIR.",
      "nota": "La discrepancia de 7.8M acciones es bloqueador crítico."
    },
    {
      "assumption_id": "A-006",
      "variable": "lease_liabilities_usd_millones",
      "valor_base": 484,
      "rango_test": {
        "min": 400,
        "max": 560,
        "paso": 40
      },
      "impacto_en_retorno_pct": {
        "si_min": 8,
        "si_max": -12
      },
      "impacto_en_decision": "Si leases >520M con crecimiento de ingresos débil, se refuerza escenario bear.",
      "nota": "Mide rigidez financiera estructural."
    }
  ],
  "gates": {
    "data_quality_gate": {
      "status": "FAIL",
      "por_que": [
        "TruthPack reporta estado PARTIAL y métricas EV-based no cerradas.",
        "Faltan deuda_total_usd y enterprise_value_usd para validar valoración por EV.",
        "No hay desglose line-item de CFF para separar recompras vs leases.",
        "La reconciliación de acciones básicas/diluidas sigue sin cierre.",
        "AR/inventarios y puente WC insuficientes para auditar calidad de CFO."
      ],
      "faltantes_criticos": [
        {
          "item": "deuda_total_usd y enterprise_value_usd",
          "como_resolver": "Extraer short-term y long-term debt del 10-K/10-Q y recomputar EV."
        },
        {
          "item": "desglose_CFF_2025",
          "como_resolver": "Separar recompras, principal de leases y otros usos de financing activities."
        },
        {
          "item": "reconciliacion_acciones",
          "como_resolver": "Cruzar nota EPS/equity del 10-K con DEF14A y rollforward dilutivo."
        },
        {
          "item": "AR_inventarios_wc_bridge",
          "como_resolver": "Extraer balance detallado y puente YoY de working capital."
        }
      ]
    },
    "survivability_gate": {
      "status": "CONDITIONAL",
      "por_que": [
        "Caja de ~260M y CFO FY2024/YTD2025 positivos dan colchón real a 12-24 meses.",
        "Intereses reportados bajos sugieren deuda financiera tradicional limitada.",
        "Leases elevados implican presión estructural si cae margen o se revierte WC."
      ],
      "condiciones_si_conditional": [
        "Mantener caja >150M.",
        "Mantener CFO TTM >120M.",
        "Evitar margen bruto <22% en dos trimestres consecutivos."
      ]
    },
    "mispricing_gate": {
      "status": "PASS",
      "por_que": [
        "P/FCF ~8.8x y FCF yield alta frente a expectativas implícitas de contracción.",
        "CFO y G&A 2025 van en dirección opuesta al pricing extremo.",
        "El pass queda condicionado a cerrar EV y dilución para confirmar el descuento real."
      ]
    },
    "catalyst_gate": {
      "status": "PASS",
      "por_que": [
        "Hay catalizadores no binarios y medibles (G&A, FCF, disclosure).",
        "Existen tests confirmatorios claros en 10-Q/10-K.",
        "El catalizador de re-rating por gobernanza tiene menor probabilidad y mayor incertidumbre temporal."
      ]
    },
    "non_speculative_gate": {
      "status": "FAIL",
      "banderas": {
        "tesis_binaria_detectada": false,
        "dependencia_financiacion_salvadora": false,
        "opacidad_inaceptable": true
      },
      "por_que": [
        "Persisten opacidades materiales en capital structure, CFF y accesibilidad de caja.",
        "La incertidumbre de dilución y disclosure impide perfil no especulativo ejecutable.",
        "Hasta remediar fuentes críticas, el riesgo de error de tesis sigue alto."
      ]
    }
  },
  "scoring_preliminar": {
    "metodo": "Score_0_100",
    "componentes": {
      "S_supervivencia_0_25": 17,
      "M_mispricing_0_25": 15,
      "C_catalizador_0_20": 13,
      "Q_calidad_0_15": 9,
      "R_downside_0_15": 7,
      "V_penalizacion_0_a_menos15": -7
    },
    "total_0_100": 54,
    "nota": "Score medio-bajo: fundamentos operativos sólidos, pero penalizado por calidad de datos, dilución potencial y opacidad."
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
        "enunciado": "La aceleración del CFO (+41% YTD) refleja mejora sostenible y no solo working capital temporal.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.55,
        "confianza_0_1": 0.6,
        "impacto": "ALTO",
        "drivers_afectados": [
          "FCF",
          "CFO"
        ],
        "evidencias": [
          {
            "source_id": "SRC_004",
            "ubicacion": "10-Q Q3-2025",
            "cita_corta": "CFO 9M-2025 126,292K vs 89,660K.",
            "interpretacion": "Aceleración observada y verificable."
          },
          {
            "source_id": "TruthPack_v1",
            "ubicacion": "metricas_derivadas",
            "cita_corta": "WC change con payables elevados.",
            "interpretacion": "Parte del impulso puede no ser estructural."
          }
        ],
        "falsacion": {
          "test": "CFO FY2025 <130M o WC changes >25% del CFO.",
          "ventana_meses": {
            "min": 1,
            "max": 6
          },
          "fuente_prevista": "10-K",
          "accion_si_falla": "REDUCIR_50"
        },
        "dependencias": [
          "A-008"
        ],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "BULL",
            "claim_id": "CLM_BULL_001"
          },
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT_003"
          }
        ],
        "notas_arbitro": "Desacuerdo central no resuelto sin puente WC completo."
      },
      {
        "assumption_id": "A-002",
        "enunciado": "La normalización de G&A en 2025 es sostenible.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.62,
        "confianza_0_1": 0.65,
        "impacto": "ALTO",
        "drivers_afectados": [
          "MARGEN_OPERATIVO",
          "FCF"
        ],
        "evidencias": [
          {
            "source_id": "SRC_004",
            "ubicacion": "10-Q Q3-2025",
            "cita_corta": "G&A -44% YoY.",
            "interpretacion": "Tendencia favorable clara."
          },
          {
            "source_id": "SRC_005",
            "ubicacion": "10-Q Q2-2025",
            "cita_corta": "G&A también cae en Q2.",
            "interpretacion": "Refuerza persistencia del patrón."
          }
        ],
        "falsacion": {
          "test": "G&A >15M en dos trimestres consecutivos.",
          "ventana_meses": {
            "min": 3,
            "max": 12
          },
          "fuente_prevista": "10-Q",
          "accion_si_falla": "REVISAR_COMITE"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "CATALYST",
            "claim_id": "CLM_FUSED_002"
          },
          {
            "agent_role": "BULL",
            "claim_id": "CLM_BULL_002"
          }
        ],
        "notas_arbitro": "Catalizador fuerte, pero aún requiere validación anual completa."
      },
      {
        "assumption_id": "A-003",
        "enunciado": "El margen bruto se estabiliza en >=22% y evita deterioro estructural.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.55,
        "confianza_0_1": 0.58,
        "impacto": "ALTO",
        "drivers_afectados": [
          "MARGEN_OPERATIVO",
          "FCF"
        ],
        "evidencias": [
          {
            "source_id": "SRC_001",
            "ubicacion": "10-K FY2024 + series",
            "cita_corta": "26.8% -> 24.6% -> 23.2%.",
            "interpretacion": "Tendencia descendente multianual."
          },
          {
            "source_id": "SRC_004",
            "ubicacion": "10-Q Q3-2025",
            "cita_corta": "GM Q3-2025 en 23.2%.",
            "interpretacion": "Nivel cercano al umbral de invalidación."
          }
        ],
        "falsacion": {
          "test": "Margen bruto <22% en 2 trimestres consecutivos.",
          "ventana_meses": {
            "min": 3,
            "max": 12
          },
          "fuente_prevista": "10-Q",
          "accion_si_falla": "SALIR"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT_001"
          },
          {
            "agent_role": "FORENSIC",
            "claim_id": "CLM_005"
          }
        ],
        "notas_arbitro": "Principal driver del bear case."
      },
      {
        "assumption_id": "A-004",
        "enunciado": "La discrepancia de acciones (~7.8M, ~27%) se resolverá sin dilución destructiva.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.5,
        "confianza_0_1": 0.4,
        "impacto": "ALTO",
        "drivers_afectados": [
          "EPS",
          "FCF_PER_SHARE"
        ],
        "evidencias": [
          {
            "source_id": "SRC_001",
            "ubicacion": "EPS/Market Data",
            "cita_corta": "Gap material entre metodologías de share count.",
            "interpretacion": "Bloqueador de valoración per-share."
          },
          {
            "source_id": "TruthPack_v1",
            "ubicacion": "metricas_derivadas",
            "cita_corta": "variacion_acciones_yoy_pct null.",
            "interpretacion": "No hay trazabilidad cerrada."
          }
        ],
        "falsacion": {
          "test": "Diluted shares >35M o crecimiento >5% YoY sin justificación estratégica.",
          "ventana_meses": {
            "min": 1,
            "max": 6
          },
          "fuente_prevista": "10-K",
          "accion_si_falla": "SALIR"
        },
        "dependencias": [
          "A-008"
        ],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "FORENSIC",
            "claim_id": "CLM_004"
          },
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT_004"
          }
        ],
        "notas_arbitro": "Sin reconciliación, el upside por acción no es verificable."
      },
      {
        "assumption_id": "A-005",
        "enunciado": "El CFF negativo de 2025 corresponde mayoritariamente a recompras accretivas.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.4,
        "confianza_0_1": 0.3,
        "impacto": "MEDIO",
        "drivers_afectados": [
          "FCF_PER_SHARE",
          "CAPITAL_ALLOCATION"
        ],
        "evidencias": [
          {
            "source_id": "SRC_004",
            "ubicacion": "10-Q Q3-2025",
            "cita_corta": "CFF 9M-2025 = -57,657K sin desglose completo.",
            "interpretacion": "No se puede probar composición."
          }
        ],
        "falsacion": {
          "test": "10-K muestra >50% de CFF en principal de leases y sin reducción de shares.",
          "ventana_meses": {
            "min": 1,
            "max": 6
          },
          "fuente_prevista": "10-K",
          "accion_si_falla": "CONGELAR_COMPRAS"
        },
        "dependencias": [
          "A-004",
          "A-008"
        ],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "BULL",
            "claim_id": "CLM_BULL_006"
          },
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT_004"
          }
        ],
        "notas_arbitro": "Supuesto no probado; requiere evidencia documental."
      },
      {
        "assumption_id": "A-006",
        "enunciado": "Las lease liabilities son manejables con caja y CFO actuales.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.72,
        "confianza_0_1": 0.75,
        "impacto": "ALTO",
        "drivers_afectados": [
          "LIQUIDEZ",
          "FCF"
        ],
        "evidencias": [
          {
            "source_id": "SRC_001",
            "ubicacion": "10-K FY2024",
            "cita_corta": "Lease liabilities 484M; corrientes ~89M; caja ~260M.",
            "interpretacion": "Cobertura de corto plazo existe, pero rigidez estructural es alta."
          }
        ],
        "falsacion": {
          "test": "Leases >520M y ratio CFO/lease_corrientes <1.5x.",
          "ventana_meses": {
            "min": 6,
            "max": 18
          },
          "fuente_prevista": "10-K",
          "accion_si_falla": "REDUCIR_50"
        },
        "dependencias": [
          "A-003"
        ],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT_002"
          },
          {
            "agent_role": "FORENSIC",
            "claim_id": "CLM_001"
          }
        ],
        "notas_arbitro": "Riesgo material pero no existencial en el corto plazo."
      },
      {
        "assumption_id": "A-007",
        "enunciado": "No ocurrirá evento material de gobernanza/contabilidad en 12-24 meses.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.75,
        "confianza_0_1": 0.55,
        "impacto": "ALTO",
        "drivers_afectados": [
          "MULTIPLO",
          "RIESGO_COLA"
        ],
        "evidencias": [
          {
            "source_id": "SRC_001",
            "ubicacion": "10-K FY2024",
            "cita_corta": "Filings regulares; transición a 10-K completada.",
            "interpretacion": "Señal positiva, pero no elimina riesgo de cola."
          }
        ],
        "falsacion": {
          "test": "Restatement, investigación SEC formal o cambio inesperado de auditor.",
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
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT_005"
          },
          {
            "agent_role": "FORENSIC",
            "claim_id": "CLM_010"
          }
        ],
        "notas_arbitro": "Riesgo de baja frecuencia y alto impacto."
      },
      {
        "assumption_id": "A-008",
        "enunciado": "Los faltantes críticos de datos se cerrarán en el loop de remediación actual.",
        "tipo": "HIPOTESIS",
        "criticidad": "CRITICO",
        "probabilidad_0_1": 0.72,
        "confianza_0_1": 0.8,
        "impacto": "ALTO",
        "drivers_afectados": [
          "DATA_QUALITY",
          "VALORACION",
          "SIZING"
        ],
        "evidencias": [
          {
            "source_id": "TruthPack_v1",
            "ubicacion": "data_quality",
            "cita_corta": "overall_status PARTIAL.",
            "interpretacion": "Gate no pasa sin remediación."
          },
          {
            "source_id": "ImpliedExpectations_v1",
            "ubicacion": "snapshot_mercado",
            "cita_corta": "deuda_total_usd y enterprise_value_usd en null.",
            "interpretacion": "No hay base EV robusta."
          }
        ],
        "falsacion": {
          "test": "Tras remediación persisten null en deuda_total_usd, EV, CFF o reconciliación de acciones.",
          "ventana_meses": {
            "min": 1,
            "max": 2
          },
          "fuente_prevista": "filing",
          "accion_si_falla": "CONGELAR_COMPRAS"
        },
        "dependencias": [],
        "estado": "ABIERTA",
        "origen": [
          {
            "agent_role": "CATALYST",
            "claim_id": "CLM_FUSED_005"
          },
          {
            "agent_role": "RED_TEAM",
            "claim_id": "CLM_RT_005"
          }
        ],
        "notas_arbitro": "Condición operativa para salir de WATCHLIST."
      }
    ]
  },
  "evidence_graph": {
    "version": "EvidenceGraph_v1",
    "nodos": [
      {
        "node_id": "E-001",
        "tipo": "EVIDENCIA",
        "label": "CFO YTD Q3-2025 +41%",
        "ref": {
          "source_id": "SRC_004"
        }
      },
      {
        "node_id": "E-002",
        "tipo": "EVIDENCIA",
        "label": "Margen bruto 26.8% -> 23.2%",
        "ref": {
          "source_id": "SRC_001"
        }
      },
      {
        "node_id": "E-003",
        "tipo": "EVIDENCIA",
        "label": "Leases 484M vs equity 405M",
        "ref": {
          "source_id": "SRC_001"
        }
      },
      {
        "node_id": "E-004",
        "tipo": "EVIDENCIA",
        "label": "TruthPack data_quality PARTIAL",
        "ref": {
          "source_id": "TruthPack_v1"
        }
      },
      {
        "node_id": "E-005",
        "tipo": "EVIDENCIA",
        "label": "Discrepancia de acciones ~27%",
        "ref": {
          "source_id": "SRC_001"
        }
      },
      {
        "node_id": "A-001",
        "tipo": "SUPUESTO",
        "label": "Calidad CFO sostenible",
        "ref": {
          "assumption_id": "A-001"
        }
      },
      {
        "node_id": "A-003",
        "tipo": "SUPUESTO",
        "label": "Margen bruto >=22%",
        "ref": {
          "assumption_id": "A-003"
        }
      },
      {
        "node_id": "A-008",
        "tipo": "SUPUESTO",
        "label": "Cierre de faltantes críticos",
        "ref": {
          "assumption_id": "A-008"
        }
      },
      {
        "node_id": "D-001",
        "tipo": "DECISION",
        "label": "WATCHLIST (0%)",
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
        "peso_0_1": 0.75,
        "nota": "CFO YTD respalda mejora operativa."
      },
      {
        "from": "E-002",
        "to": "A-003",
        "relacion": "DEBILITA",
        "peso_0_1": 0.8,
        "nota": "Compresión de márgenes aumenta riesgo de value trap."
      },
      {
        "from": "E-003",
        "to": "D-001",
        "relacion": "INFORMA",
        "peso_0_1": 0.7,
        "nota": "Leases altos elevan prudencia en sizing."
      },
      {
        "from": "E-004",
        "to": "A-008",
        "relacion": "SOPORTA",
        "peso_0_1": 0.95,
        "nota": "Data quality incompleta activa remediación."
      },
      {
        "from": "E-005",
        "to": "D-001",
        "relacion": "DETERMINA",
        "peso_0_1": 0.9,
        "nota": "Riesgo de dilución bloquea inversión."
      },
      {
        "from": "A-008",
        "to": "D-001",
        "relacion": "INFORMA",
        "peso_0_1": 0.92,
        "nota": "Sin remediación no hay salida de WATCHLIST."
      }
    ],
    "validacion_grafo": {
      "ids_unicos": true,
      "aristas_referencian_nodos_existentes": true,
      "supuestos_criticos_tienen_falsacion": true,
      "detalle": "Grafo consistente y trazable."
    }
  },
  "catalizadores_consolidados": [
    {
      "catalyst_id": "CAT-001",
      "nombre": "Normalización de G&A",
      "es_no_binario": true,
      "ventana_meses": {
        "min": 3,
        "probable": 9,
        "max": 18
      },
      "probabilidad_0_1": 0.78,
      "mecanismo_cierre_gap": "Sostener G&A bajo mejora EBIT/FCF y reduce el descuento por eficiencia operativa.",
      "supuestos_afectados": [
        "A-002",
        "A-001"
      ],
      "tests_confirmatorios": [
        {
          "descripcion": "G&A trimestral <12M en 3 de 4 trimestres",
          "fuente_prevista": "10-Q",
          "ventana_meses": {
            "min": 3,
            "max": 12
          }
        }
      ]
    },
    {
      "catalyst_id": "CAT-002",
      "nombre": "Validación de FCF y calidad de caja",
      "es_no_binario": true,
      "ventana_meses": {
        "min": 3,
        "probable": 12,
        "max": 24
      },
      "probabilidad_0_1": 0.65,
      "mecanismo_cierre_gap": "FCF >=130M con puente WC sano refuta la contracción implícita y mejora confianza en valoración.",
      "supuestos_afectados": [
        "A-001",
        "A-005",
        "A-008"
      ],
      "tests_confirmatorios": [
        {
          "descripcion": "FCF FY2025 >=130M",
          "fuente_prevista": "10-K",
          "ventana_meses": {
            "min": 1,
            "max": 6
          }
        },
        {
          "descripcion": "WC changes <=25% del CFO anual",
          "fuente_prevista": "10-K",
          "ventana_meses": {
            "min": 1,
            "max": 6
          }
        }
      ]
    },
    {
      "catalyst_id": "CAT-003",
      "nombre": "Compresión de prima de riesgo por disclosure/gobernanza",
      "es_no_binario": true,
      "ventana_meses": {
        "min": 6,
        "probable": 18,
        "max": 30
      },
      "probabilidad_0_1": 0.42,
      "mecanismo_cierre_gap": "Mejor transparencia en deuda/CFF/shares/caja reduce prima de riesgo estructural.",
      "supuestos_afectados": [
        "A-007",
        "A-008"
      ],
      "tests_confirmatorios": [
        {
          "descripcion": "Filings en tiempo sin restatements por 4 trimestres",
          "fuente_prevista": "filing",
          "ventana_meses": {
            "min": 6,
            "max": 18
          }
        },
        {
          "descripcion": "Reconciliación completa de acciones y CFF en 10-K",
          "fuente_prevista": "10-K",
          "ventana_meses": {
            "min": 1,
            "max": 6
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
      "descripcion": "FCF se estabiliza en 130-155M, G&A se mantiene baja y margen bruto en 22.5-24%. Se cierran bloqueadores de datos y hay re-rating moderado.",
      "drivers_clave": [
        "A-001",
        "A-002",
        "A-003",
        "A-008"
      ],
      "retorno_12_24m_pct_rango": {
        "min": 8,
        "base": 18,
        "max": 30
      },
      "nota_valoracion": "Upside moderado condicionado a remediación documental."
    },
    {
      "scenario_id": "BULL",
      "probabilidad_0_1": 0.15,
      "ventana_meses": {
        "min": 12,
        "probable": 21,
        "max": 30
      },
      "descripcion": "FCF escala a 155-190M, dilución controlada y mejora de percepción de gobernanza habilitan re-rating fuerte.",
      "drivers_clave": [
        "A-001",
        "A-002",
        "A-004",
        "A-007"
      ],
      "retorno_12_24m_pct_rango": {
        "min": 45,
        "base": 65,
        "max": 100
      },
      "nota_valoracion": "Escenario de baja probabilidad por requerir cierre simultáneo de riesgos."
    },
    {
      "scenario_id": "BEAR",
      "probabilidad_0_1": 0.4,
      "ventana_meses": {
        "min": 3,
        "probable": 12,
        "max": 24
      },
      "descripcion": "Margen bruto cae a 21-22%, FCF sostenible baja a 95-115M, dilución se materializa y el descuento persiste.",
      "drivers_clave": [
        "A-003",
        "A-004",
        "A-005",
        "A-006"
      ],
      "retorno_12_24m_pct_rango": {
        "min": -35,
        "base": -20,
        "max": -5
      },
      "nota_valoracion": "Value trap confirmado si no se resuelven datos y calidad de beneficios."
    }
  ],
  "kill_criteria_final": [
    {
      "kc_id": "KC-001",
      "relacionado_con_assumption_id": "A-003",
      "definicion": "Margen bruto <22% durante dos trimestres consecutivos.",
      "ventana_meses": {
        "min": 1,
        "max": 12
      },
      "fuente_prevista": "10-Q",
      "accion": "SALIR",
      "severidad": "ALTA",
      "por_que": "Confirma deterioro estructural del modelo."
    },
    {
      "kc_id": "KC-002",
      "relacionado_con_assumption_id": "A-007",
      "definicion": "Restatement material, investigación SEC formal, o cambio inesperado de auditor.",
      "ventana_meses": {
        "min": 1,
        "max": 24
      },
      "fuente_prevista": "filing",
      "accion": "SALIR",
      "severidad": "ALTA",
      "por_que": "Riesgo de cola no compensable por valoración."
    },
    {
      "kc_id": "KC-003",
      "relacionado_con_assumption_id": "A-001",
      "definicion": "CFO TTM <80M o dos trimestres consecutivos con CFO negativo.",
      "ventana_meses": {
        "min": 3,
        "max": 18
      },
      "fuente_prevista": "filing",
      "accion": "SALIR",
      "severidad": "ALTA",
      "por_que": "Rompe cobertura de obligaciones fijas y tesis de caja."
    },
    {
      "kc_id": "KC-004",
      "relacionado_con_assumption_id": "A-004",
      "definicion": "Acciones diluidas >35M o crecimiento >5% YoY sin adquisición estratégica equivalente.",
      "ventana_meses": {
        "min": 1,
        "max": 12
      },
      "fuente_prevista": "10-K",
      "accion": "REVISAR_COMITE",
      "severidad": "MEDIA",
      "por_que": "Erosiona fuertemente retorno por acción."
    },
    {
      "kc_id": "KC-005",
      "relacionado_con_assumption_id": "A-008",
      "definicion": "10-K FY2025 no aclara deuda/EV, desglose CFF o reconciliación de acciones.",
      "ventana_meses": {
        "min": 1,
        "max": 6
      },
      "fuente_prevista": "10-K",
      "accion": "CONGELAR_COMPRAS",
      "severidad": "MEDIA",
      "por_que": "Impide pasar de WATCHLIST a inversión ejecutable."
    },
    {
      "kc_id": "KC-006",
      "relacionado_con_assumption_id": "A-001",
      "definicion": "FCF FY2025 <110M.",
      "ventana_meses": {
        "min": 1,
        "max": 6
      },
      "fuente_prevista": "10-K",
      "accion": "REDUCIR_50",
      "severidad": "ALTA",
      "por_que": "Valida contracción estructural de caja."
    }
  ],
  "plan_monitorizacion": {
    "frecuencias": {
      "pulso_diario": {
        "activo": true,
        "que_mirar": [
          "Filings nuevos (8-K/10-Q/10-K/NT)",
          "Noticias regulatorias y short reports",
          "Precio vs caídas anómalas"
        ]
      },
      "revision_semanal": {
        "activo": true,
        "que_mirar": [
          "Estado de supuestos críticos",
          "Progreso de remediación de datos",
          "Riesgo de margen y dilución"
        ]
      },
      "modo_evento": {
        "activo": true,
        "que_mirar": [
          "10-K FY2025",
          "Earnings call transcript",
          "Notas de deuda, CFF, EPS y leases"
        ]
      }
    },
    "lista_de_checks_por_supuesto": [
      {
        "assumption_id": "A-001",
        "indicadores": [
          "CFO trimestral",
          "WC changes",
          "CFO/EBIT"
        ],
        "fuente": "10-Q",
        "frecuencia": "TRIMESTRAL"
      },
      {
        "assumption_id": "A-003",
        "indicadores": [
          "Margen bruto",
          "COGS/Revenue"
        ],
        "fuente": "10-Q",
        "frecuencia": "TRIMESTRAL"
      },
      {
        "assumption_id": "A-004",
        "indicadores": [
          "Shares básicas",
          "Shares diluidas",
          "Instrumentos dilutivos"
        ],
        "fuente": "10-K",
        "frecuencia": "TRIMESTRAL"
      },
      {
        "assumption_id": "A-005",
        "indicadores": [
          "CFF buybacks",
          "CFF lease principal",
          "CFF otros"
        ],
        "fuente": "10-K",
        "frecuencia": "TRIMESTRAL"
      },
      {
        "assumption_id": "A-006",
        "indicadores": [
          "Lease liabilities total/corrientes",
          "CFO/lease_corrientes"
        ],
        "fuente": "10-K",
        "frecuencia": "ANUAL"
      },
      {
        "assumption_id": "A-008",
        "indicadores": [
          "deuda_total_usd",
          "enterprise_value_usd",
          "estado data quality"
        ],
        "fuente": "filing",
        "frecuencia": "EVENTO"
      }
    ],
    "umbrales_alerta": [
      {
        "tipo": "PRECIO",
        "condicion": "Caída >20% en 20 días sin evento exógeno sectorial",
        "accion": "REVISAR_COMITE",
        "severidad": "MEDIA"
      },
      {
        "tipo": "FUNDAMENTAL",
        "condicion": "Margen bruto <22.5% en cualquier trimestre",
        "accion": "REVISAR_COMITE",
        "severidad": "ALTA"
      },
      {
        "tipo": "DISCLOSURE",
        "condicion": "NT filing, restatement o cambio inesperado de auditor",
        "accion": "SALIR",
        "severidad": "ALTA"
      },
      {
        "tipo": "FUNDAMENTAL",
        "condicion": "CFO trimestral negativo",
        "accion": "REVISAR_COMITE",
        "severidad": "ALTA"
      }
    ]
  },
  "predicciones_para_calibracion_consolidadas": [
    {
      "pred_id": "CP-001",
      "descripcion": "Ingresos FY2025 superarán 1,280M USD.",
      "probabilidad_0_1": 0.77,
      "ventana_meses": {
        "min": 1,
        "max": 4
      },
      "criterio_validacion": "Revenue anual en 10-K FY2025 > 1,280,000,000.",
      "fuente_prevista": "10-K",
      "origen": [
        {
          "agent_role": "BULL",
          "pred_id": "PRED_BULL_001"
        },
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_FUSED_001"
        }
      ]
    },
    {
      "pred_id": "CP-002",
      "descripcion": "FCF FY2025 será >=130M USD.",
      "probabilidad_0_1": 0.68,
      "ventana_meses": {
        "min": 1,
        "max": 6
      },
      "criterio_validacion": "FCF FY2025 (CFO - |CAPEX|) >= 130,000,000.",
      "fuente_prevista": "10-K",
      "origen": [
        {
          "agent_role": "BULL",
          "pred_id": "PRED_BULL_002"
        },
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_FUSED_004"
        }
      ]
    },
    {
      "pred_id": "CP-003",
      "descripcion": "G&A FY2025 será <45M USD.",
      "probabilidad_0_1": 0.7,
      "ventana_meses": {
        "min": 1,
        "max": 6
      },
      "criterio_validacion": "G&A total FY2025 < 45,000,000.",
      "fuente_prevista": "10-K",
      "origen": [
        {
          "agent_role": "BULL",
          "pred_id": "PRED_BULL_003"
        },
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_FUSED_002"
        }
      ]
    },
    {
      "pred_id": "CP-004",
      "descripcion": "Margen bruto FY2025 cerrará en <=24.0%.",
      "probabilidad_0_1": 0.67,
      "ventana_meses": {
        "min": 1,
        "max": 6
      },
      "criterio_validacion": "Gross profit FY2025 / Revenue FY2025 <= 0.240.",
      "fuente_prevista": "10-K",
      "origen": [
        {
          "agent_role": "RED_TEAM",
          "pred_id": "PRED_RT_001"
        }
      ]
    },
    {
      "pred_id": "CP-005",
      "descripcion": "La reducción de acciones diluidas en FY2025 será <2% (o nula).",
      "probabilidad_0_1": 0.72,
      "ventana_meses": {
        "min": 1,
        "max": 9
      },
      "criterio_validacion": "Diluted shares FY2025 > 0.98 x diluted shares FY2024.",
      "fuente_prevista": "10-K",
      "origen": [
        {
          "agent_role": "RED_TEAM",
          "pred_id": "PRED_RT_004"
        }
      ]
    },
    {
      "pred_id": "CP-006",
      "descripcion": "No habrá restatement material ni investigación SEC formal en 12-18 meses.",
      "probabilidad_0_1": 0.65,
      "ventana_meses": {
        "min": 6,
        "max": 18
      },
      "criterio_validacion": "Ausencia de 8-K/10-K con restatement material o investigación formal.",
      "fuente_prevista": "filing",
      "origen": [
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_FUSED_009"
        },
        {
          "agent_role": "FORENSIC",
          "pred_id": "PRED_009"
        }
      ]
    },
    {
      "pred_id": "CP-007",
      "descripcion": "CFO anual FY2025 superará 160M USD.",
      "probabilidad_0_1": 0.73,
      "ventana_meses": {
        "min": 1,
        "max": 3
      },
      "criterio_validacion": "10-K reporta Net Cash from Operating Activities > 160,000,000.",
      "fuente_prevista": "10-K",
      "origen": [
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_FUSED_003"
        }
      ]
    },
    {
      "pred_id": "CP-008",
      "descripcion": "P/FCF alcanzará >=10.5x en 18 meses si FCF TTM >=120M.",
      "probabilidad_0_1": 0.45,
      "ventana_meses": {
        "min": 6,
        "max": 18
      },
      "criterio_validacion": "Market cap / FCF TTM >= 10.5 con FCF TTM >=120M.",
      "fuente_prevista": "precio",
      "origen": [
        {
          "agent_role": "BULL",
          "pred_id": "PRED_BULL_006"
        },
        {
          "agent_role": "CATALYST",
          "pred_id": "PRED_FUSED_010"
        }
      ]
    }
  ],
  "arbitraje": {
    "notas_arbitro": [
      "La decisión final fusionada es WATCHLIST con sizing 0%, no BLOQUEADO, pero con next_step=REMEDIATE.",
      "Se priorizó criterio conservador en gates: data_quality y non_speculative quedan en FAIL por bloqueadores no cerrados.",
      "Se preserva la tesis de mispricing/catalizadores como válida condicionalmente, sujeta a evidencia documental en 10-K.",
      "La resolución de deuda/EV, CFF, shares y WC determina promoción a INVERTIR o degradación a DESCARTAR."
    ],
    "desacuerdos_detectados": [
      {
        "tema": "Decisión categórica (WATCHLIST vs BLOQUEADO)",
        "agentes": [
          {
            "agent_role": "GEMINI",
            "posicion": "WATCHLIST",
            "confianza_0_1": 0.72
          },
          {
            "agent_role": "CODEX",
            "posicion": "BLOQUEADO",
            "confianza_0_1": 0.57
          },
          {
            "agent_role": "CLAUDE",
            "posicion": "WATCHLIST",
            "confianza_0_1": 0.57
          }
        ],
        "resolucion_arbitro": {
          "estado": "RESUELTO",
          "decision": "watchlist_con_remediation_obligatoria",
          "por_que": "Mayoría WATCHLIST y evidencia de supervivencia/mispricing, manteniendo bloqueadores críticos como condición dura.",
          "accion": "Sostener 0% de tamaño hasta cierre de remediación."
        }
      },
      {
        "tema": "Data quality gate (PASS condicional vs FAIL)",
        "agentes": [
          {
            "agent_role": "CLAUDE",
            "posicion": "PASS condicional",
            "confianza_0_1": 0.57
          },
          {
            "agent_role": "GEMINI",
            "posicion": "FAIL",
            "confianza_0_1": 0.72
          },
          {
            "agent_role": "CODEX",
            "posicion": "FAIL",
            "confianza_0_1": 0.57
          }
        ],
        "resolucion_arbitro": {
          "estado": "RESUELTO",
          "decision": "FAIL",
          "por_que": "Faltantes de deuda/EV, CFF y shares impiden validación de valoración robusta.",
          "accion": "Ejecutar work orders de extracción y recálculo."
        }
      },
      {
        "tema": "Calidad del CFO (mejora estructural vs efecto WC)",
        "agentes": [
          {
            "agent_role": "BULL",
            "posicion": "Mejora operativa sostenible",
            "confianza_0_1": 0.88
          },
          {
            "agent_role": "RED_TEAM",
            "posicion": "Inflado por working capital",
            "confianza_0_1": 0.78
          }
        ],
        "resolucion_arbitro": {
          "estado": "NO_RESUELTO",
          "decision": "pedir_fuente",
          "por_que": "Sin AR/inventarios y puente WC no hay cierre causal.",
          "accion": "Mantener hipótesis A-001 abierta y sensible."
        }
      },
      {
        "tema": "Non-speculative gate (opacidad tratable vs opacidad inaceptable)",
        "agentes": [
          {
            "agent_role": "GEMINI",
            "posicion": "FAIL por opacidad inaceptable",
            "confianza_0_1": 0.72
          },
          {
            "agent_role": "CODEX",
            "posicion": "PASS (opacidad tratable)",
            "confianza_0_1": 0.57
          },
          {
            "agent_role": "CLAUDE",
            "posicion": "PASS (opacidad alta pero analizable)",
            "confianza_0_1": 0.57
          }
        ],
        "resolucion_arbitro": {
          "estado": "RESUELTO",
          "decision": "FAIL_temporal",
          "por_que": "El incumplimiento de disclosure crítico mantiene perfil especulativo operativo hasta remediación.",
          "accion": "Reevaluar gate tras 10-K."
        }
      }
    ],
    "puntos_abiertos": [
      "Deuda financiera total y EV definitivo.",
      "Composición exacta de CFF 2025.",
      "Reconciliación completa de shares diluidas e instrumentos.",
      "Accesibilidad geográfica de la caja y restricciones de repatriación.",
      "Puente de working capital (AR/inventarios/payables).",
      "Causa estructural de la compresión de margen bruto."
    ]
  },
  "peticiones_de_fuentes": [
    {
      "prioridad": "ALTA",
      "item": "Deuda financiera total (short-term + long-term debt) y deuda neta",
      "por_que_importa": "Sin deuda no hay EV robusto ni comparables EV-based.",
      "como_obtenerlo": "10-K/10-Q nota de deuda y current maturities."
    },
    {
      "prioridad": "ALTA",
      "item": "Desglose detallado de CFF 2025",
      "por_que_importa": "Separar recompras accretivas de pagos de leases.",
      "como_obtenerlo": "Financing activities line-item en 10-K y 10-Q."
    },
    {
      "prioridad": "ALTA",
      "item": "Reconciliación de acciones básicas/diluidas e instrumentos dilutivos",
      "por_que_importa": "Resolver discrepancia de ~27% y retorno por acción.",
      "como_obtenerlo": "10-K nota EPS/equity + DEF14A + rollforward de instrumentos."
    },
    {
      "prioridad": "ALTA",
      "item": "AR, inventarios y puente detallado de working capital",
      "por_que_importa": "Validar sostenibilidad del CFO y calidad de beneficios.",
      "como_obtenerlo": "Balance detallado y notas de activos corrientes en 10-K."
    },
    {
      "prioridad": "ALTA",
      "item": "Caja por jurisdicción y restricciones de repatriación",
      "por_que_importa": "Confirmar accesibilidad real del colchón de caja.",
      "como_obtenerlo": "10-K nota de liquidez/cash equivalents y MD&A."
    },
    {
      "prioridad": "MEDIA",
      "item": "Tabla de vencimientos de leases 2026-2030",
      "por_que_importa": "Cuantificar presión de caja estructural.",
      "como_obtenerlo": "10-K nota ASC 842."
    },
    {
      "prioridad": "MEDIA",
      "item": "Desglose de ingresos por mix/segmento",
      "por_que_importa": "Diagnosticar reversibilidad de la compresión de margen.",
      "como_obtenerlo": "Revenue disaggregation ASC 606 y MD&A."
    }
  ],
  "salida_para_siguiente_agente": {
    "monitor_input_recomendado": "Ejecutar RemediationPlan y re-arbitrar este DecisionPacket_v2 con datos cerrados de 10-K.",
    "estado_caso": "EN_ESPERA",
    "proxima_revision_sugerida": "2026-03-10"
  },
  "log": {
    "autochequeos": {
      "decision_respeta_gates": true,
      "supuestos_criticos_tienen_evidencia": true,
      "supuestos_criticos_tienen_falsacion": true,
      "kill_criteria_mapeados_a_supuestos": true,
      "salida_solo_json": true,
      "probabilidades_escenarios_suman_1": true,
      "kelly_sizing_dentro_de_tope": true,
      "intervalo_confianza_coherente_con_escenarios": true,
      "decision_categorica_coherente_con_probabilistica": true,
      "sizing_final_igual_preliminar_si_invertir": true,
      "sensibilidad_cubre_supuestos_criticos": true
    },
    "limitaciones": [
      "EV no verificable sin deuda_total_usd explícita.",
      "CFF 2025 sin desglose definitivo.",
      "Discrepancia de acciones sin reconciliación oficial.",
      "Datos AR/inventarios incompletos para auditoría de CFO.",
      "Accesibilidad de caja por jurisdicción pendiente."
    ],
    "revision": {
      "es_revision": false,
      "revision_num": 1,
      "decision_packet_anterior_caso_id": null,
      "monitoring_updates_usados": [],
      "resumen_cambios": [
        "Fusión multi-modelo (gemini, codex, claude) en schema DecisionPacket_v2.",
        "Decisión consolidada WATCHLIST con next_step=REMEDIATE por bloqueadores críticos.",
        "Se incorporan issues/work_orders priorizados para cierre de data quality."
      ]
    }
  },
  "control": {
    "estado_flujo": "ARBITRATE",
    "next_step": "REMEDIATE",
    "next_agent_role": "TRUTH_PACK",
    "loop_budget_max": 2,
    "loop_budget_restante": 2,
    "issues": [
      {
        "issue_id": "ISS-001",
        "issue_code": "DEBT_EV_MISSING",
        "gate_afectado": "data_quality_gate",
        "severidad": "ALTA",
        "resoluble": true,
        "owner_agent_role": "TRUTH_PACK",
        "descripcion": "Faltan deuda_total_usd, deuda_neta_usd y enterprise_value_usd.",
        "criterio_aceptacion": {
          "required_fields": [
            "deuda_total_usd",
            "deuda_neta_usd",
            "enterprise_value_usd"
          ],
          "notes": "Cada campo con source_ref verificable."
        }
      },
      {
        "issue_id": "ISS-002",
        "issue_code": "WC_COMPONENTS_MISSING",
        "gate_afectado": "data_quality_gate",
        "severidad": "ALTA",
        "resoluble": true,
        "owner_agent_role": "TRUTH_PACK",
        "descripcion": "Faltan AR/inventarios y puente detallado de working capital.",
        "criterio_aceptacion": {
          "required_fields": [
            "cuentas_por_cobrar_usd",
            "inventarios_usd",
            "wc_bridge_detallado"
          ],
          "notes": "Debe reconciliar con el CFO reportado."
        }
      },
      {
        "issue_id": "ISS-003",
        "issue_code": "CFF_BREAKDOWN_MISSING",
        "gate_afectado": "data_quality_gate",
        "severidad": "ALTA",
        "resoluble": true,
        "owner_agent_role": "SOURCES",
        "descripcion": "No se distingue recompras vs principal de leases en CFF.",
        "criterio_aceptacion": {
          "required_fields": [
            "cff_buybacks_usd",
            "cff_lease_principal_usd",
            "cff_other_financing_usd"
          ],
          "notes": "Las partidas deben reconciliar contra cff_usd."
        }
      },
      {
        "issue_id": "ISS-004",
        "issue_code": "SHARE_RECON_MISSING",
        "gate_afectado": "data_quality_gate",
        "severidad": "ALTA",
        "resoluble": true,
        "owner_agent_role": "SOURCES",
        "descripcion": "Reconciliación de basic/diluted shares e instrumentos dilutivos pendiente.",
        "criterio_aceptacion": {
          "required_fields": [
            "shares_basic",
            "shares_diluted",
            "dilutive_instruments_rollforward"
          ],
          "notes": "Incluir options, RSUs, warrants y convertibles."
        }
      },
      {
        "issue_id": "ISS-005",
        "issue_code": "CASH_ACCESS_AND_LEASE_MATURITY_MISSING",
        "gate_afectado": "non_speculative_gate",
        "severidad": "MEDIA",
        "resoluble": true,
        "owner_agent_role": "SOURCES",
        "descripcion": "Falta accesibilidad de caja por jurisdicción y maturity schedule de leases.",
        "criterio_aceptacion": {
          "required_fields": [
            "cash_by_jurisdiction",
            "cash_repatriation_restrictions",
            "lease_maturity_schedule_2026_2030"
          ],
          "notes": "Necesario para validar supervivencia no especulativa."
        }
      }
    ],
    "work_orders": [
      {
        "wo_id": "WO-001",
        "agent_role": "TRUTH_PACK",
        "tipo": "EXTRACT_FIELDS",
        "issue_refs": [
          "ISS-001"
        ],
        "targets": {
          "fields": [
            "deuda_total_usd",
            "deuda_neta_usd",
            "enterprise_value_usd"
          ],
          "notes": "Calcular EV = mcap + deuda_total - caja."
        },
        "acceptance": {
          "required_fields": [
            "deuda_total_usd",
            "enterprise_value_usd"
          ],
          "pass_if_present": true
        },
        "depends_on": []
      },
      {
        "wo_id": "WO-002",
        "agent_role": "TRUTH_PACK",
        "tipo": "EXTRACT_FIELDS",
        "issue_refs": [
          "ISS-002"
        ],
        "targets": {
          "fields": [
            "cuentas_por_cobrar_usd",
            "inventarios_usd",
            "wc_bridge_detallado"
          ],
          "notes": "Auditar calidad del CFO."
        },
        "acceptance": {
          "required_fields": [
            "cuentas_por_cobrar_usd",
            "inventarios_usd"
          ],
          "pass_if_present": true
        },
        "depends_on": []
      },
      {
        "wo_id": "WO-003",
        "agent_role": "SOURCES",
        "tipo": "EXTRACT_FIELDS",
        "issue_refs": [
          "ISS-003"
        ],
        "targets": {
          "fields": [
            "cff_buybacks_usd",
            "cff_lease_principal_usd",
            "cff_other_financing_usd"
          ],
          "notes": "Reconstruir composición del CFF 2025."
        },
        "acceptance": {
          "required_fields": [
            "cff_buybacks_usd",
            "cff_lease_principal_usd"
          ],
          "pass_if_present": true
        },
        "depends_on": []
      },
      {
        "wo_id": "WO-004",
        "agent_role": "SOURCES",
        "tipo": "EXTRACT_FIELDS",
        "issue_refs": [
          "ISS-004"
        ],
        "targets": {
          "fields": [
            "shares_basic",
            "shares_diluted",
            "dilutive_instruments_rollforward"
          ],
          "notes": "Resolver discrepancia de share count."
        },
        "acceptance": {
          "required_fields": [
            "shares_diluted",
            "dilutive_instruments_rollforward"
          ],
          "pass_if_present": true
        },
        "depends_on": []
      },
      {
        "wo_id": "WO-005",
        "agent_role": "SOURCES",
        "tipo": "EXTRACT_FIELDS",
        "issue_refs": [
          "ISS-005"
        ],
        "targets": {
          "fields": [
            "cash_by_jurisdiction",
            "cash_repatriation_restrictions",
            "lease_maturity_schedule_2026_2030"
          ],
          "notes": "Completar validación de liquidez y opacidad offshore."
        },
        "acceptance": {
          "required_fields": [
            "cash_by_jurisdiction",
            "lease_maturity_schedule_2026_2030"
          ],
          "pass_if_present": true
        },
        "depends_on": []
      },
      {
        "wo_id": "WO-006",
        "agent_role": "IMPLIED",
        "tipo": "RECALC_EXPECTATIONS",
        "issue_refs": [
          "ISS-001",
          "ISS-002",
          "ISS-003",
          "ISS-004"
        ],
        "targets": {
          "fields": [
            "reverse_dcf_fcf_actualizado",
            "ev_ebit",
            "ev_fcf",
            "sensibilidades_actualizadas"
          ],
          "notes": "Recalcular expectativas implícitas con EV y shares reconciliadas."
        },
        "acceptance": {
          "required_fields": [
            "ev_fcf",
            "reverse_dcf_fcf_actualizado"
          ],
          "pass_if_present": true
        },
        "depends_on": [
          "WO-001",
          "WO-002",
          "WO-003",
          "WO-004"
        ]
      }
    ],
    "dispatch_queue": [
      {
        "step": 1,
        "agent_role": "TRUTH_PACK",
        "wo_ids": [
          "WO-001",
          "WO-002"
        ]
      },
      {
        "step": 2,
        "agent_role": "SOURCES",
        "wo_ids": [
          "WO-003",
          "WO-004",
          "WO-005"
        ]
      },
      {
        "step": 3,
        "agent_role": "IMPLIED",
        "wo_ids": [
          "WO-006"
        ]
      }
    ]
  },
  "_meta": {
    "fusion": {
      "step_name": "ARBITRO",
      "schema_objetivo": "DecisionPacket_v2",
      "modelos_usados": [
        "gemini",
        "codex",
        "claude"
      ],
      "criterios_resolucion": [
        "Selección de schema por mayoría y compatibilidad estructural (DecisionPacket_v2).",
        "Datos cuantitativos: prioridad al valor más evidenciado; en conflicto material, sesgo conservador de riesgo.",
        "Claims textuales: unión de perspectivas no duplicadas con trazabilidad de bloqueadores.",
        "Scores/probabilidades: registro de rango [min,max] inter-modelo y valor recomendado.",
        "No se descartaron warnings críticos de ningún modelo; se trasladaron a gates, issues y work_orders."
      ],
      "rangos_modelos": {
        "confianza_global_0_1": {
          "min": 0.57,
          "max": 0.72,
          "recomendado": 0.57
        },
        "probabilidad_exito_0_1": {
          "min": 0.56,
          "max": 0.73,
          "recomendado": 0.6
        },
        "retorno_esperado_ponderado_pct": {
          "min": 9.82,
          "max": 26.5,
          "recomendado": 9.9
        },
        "ratio_asimetria": {
          "min": 0.9,
          "max": 1.14,
          "recomendado": 0.9
        },
        "scoring_total_0_100": {
          "min": 54,
          "max": 69,
          "recomendado": 54
        },
        "escenarios_probabilidad": {
          "base": {
            "min": 0.38,
            "max": 0.5,
            "recomendado": 0.45
          },
          "bull": {
            "min": 0.15,
            "max": 0.23,
            "recomendado": 0.15
          },
          "bear": {
            "min": 0.27,
            "max": 0.44,
            "recomendado": 0.4
          }
        }
      },
      "conflictos_detectados": [
        {
          "campo": "resumen_ejecutivo.decision",
          "valores_modelo": {
            "gemini": "WATCHLIST",
            "codex": "BLOQUEADO",
            "claude": "WATCHLIST"
          },
          "resolucion": "WATCHLIST con next_step=REMEDIATE y tamaño 0%."
        },
        {
          "campo": "gates.data_quality_gate.status",
          "valores_modelo": {
            "gemini": "FAIL",
            "codex": "FAIL",
            "claude": "PASS"
          },
          "resolucion": "FAIL por faltantes críticos no resueltos (deuda/EV, CFF, shares, WC)."
        },
        {
          "campo": "gates.non_speculative_gate.status",
          "valores_modelo": {
            "gemini": "FAIL",
            "codex": "PASS",
            "claude": "PASS"
          },
          "resolucion": "FAIL temporal por opacidad crítica pendiente de remediación."
        },
        {
          "campo": "decision_probabilistica.probabilidad_exito_0_1",
          "valores_modelo": {
            "gemini": 0.73,
            "codex": 0.56,
            "claude": 0.6
          },
          "resolucion": "0.60 por consistencia con escenario WATCHLIST conservador y riesgo de calidad."
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
