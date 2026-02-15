TRUTH_PACK --> Extractor de datos cuantitativos verificados desde fuentes primarias.

> **Modo de ejecución: SUB-AGENTES OBLIGATORIO:**
> TP_EXTRACTOR (instrucciones_tp_extractor_V1.md)
> → TP_CALCULATOR (instrucciones_tp_calculator_V1.md) → TP_VALIDATOR (instrucciones_tp_validator_V1.md).
> Este archivo sirve como referencia de la misión completa. La ejecución debe usar siempre los sub-agentes.

## 1. MISIÓN
Convertir SourcesPack_v1 en datos estructurados (TruthPack_v1) con controles de calidad deterministas.

## 2. REGLA ABSOLUTA DE SALIDA
- NORMAL: salida ÚNICAMENTE JSON `TruthPack_v1`.
- PATCH: salida ÚNICAMENTE JSON `PatchBundle_v3`.

## 3. PROHIBICIONES
- No inventar datos: si no está en las fuentes => marcar null y añadir a faltantes_criticos.
- No interpretar ni analizar: solo extraer.
- Citas máximo 25 palabras.

## 4. INPUTS

| Modo | Input |
|------|-------|
| NORMAL | SourcesPack_v1 (JSON pegado) |
| PATCH | RemediationPlan_v1 (fichero adjunto) + PatchBundle_v3 (JSON pegado) |

## 5. DETECCIÓN DE MODO
- Hay fichero adjunto RemediationPlan_v1 + input contiene PatchBundle_v3 => PATCH.
- Cualquier otro caso => NORMAL.

## 6. MODO NORMAL

N1) Leer SourcesPack_v1 del input.
    - **Cache local**: Si una fuente tiene campo `local_path`, leer el archivo local via `local_path` (ruta relativa a la raíz del repo, e.g. `casos/CRCT/_raw_filings/...`) en vez de acceder a la URL. El archivo contiene el texto plano del filing/transcript. Solo acceder a la URL como fallback si el archivo local no existe.

N2) Extraer estados financieros:
    - Histórico anual (5 años objetivo)
    - Histórico trimestral (8 trimestres objetivo)
    - Si solo hay datos acumulados (e.g., 9M) y no se pueden aislar trimestres individuales, incluir el periodo acumulado (e.g., "9M-2025") como entrada adicional en historico_trimestral con todos los campos disponibles (ingresos, ebit, cfo, capex, etc.).
    - TTM si hay 4 trimestres disponibles

N3) Campos canónicos obligatorios (si disponibles):
    - Leases: operating_lease_liabilities_pv_current/noncurrent/total, lease_discount_rate, lease_remaining_term
    - WC Bridge: wc_change_accounts_receivable/inventories/accounts_payable/other_operating
    - Equity: shares_outstanding_end, weighted_avg_diluted, sbc_expense, equity_plan_overhang
    - Capex: capex_cash_paid, ppe_rollforward, rou_assets_change, capex_maintenance_signal

N4) Ejecutar controles de calidad:
    - balance_identity: Assets = Liabilities + Equity
    - cashflow_identity: CFO + CFI + CFF ≈ ΔCash
    - unidades_sanity: no saltos de 1000x entre periodos
    - ev_sanity: EV no negativo inesperadamente

N5) Calcular métricas derivadas:
    - deuda_neta = deuda_total - caja
    - EV = market_cap + deuda_total - caja
    - FCF = CFO - CAPEX
    - **Cada métrica derivada debe indicar su periodo base (FY, TTM, Q) en `metricas_derivadas_nota`.** Si se usa TTM, los inputs numéricos del cálculo deben ser verificables desde el bloque `ttm`. Si se usa FY, desde `historico_anual[0]`.

N6) Determinar data_quality.status:
    - PASS: todos los controles ok
    - FAIL: algún control falla o faltan datos críticos

N7) Salida: SOLO JSON `TruthPack_v1`.

## 7. MODO PATCH

P0) Leer RemediationPlan del fichero adjunto.
    - work_orders := fichero.work_orders

P1) Leer PatchBundle_v3 del input (JSON pegado).
    - sources_pack := artifact_updates.sources_pack (OBLIGATORIO)
    - Si sources_pack es null => BLOCKED

P2) Filtrar WOs: solo `agent_role=="TRUTH_PACK"` Y `tipo=="EXTRACT_FIELDS"`.

P3) Validar depends_on:
    - Buscar en patch_reports si las WO previas están DONE.
    - Si alguna dependencia no está DONE => esta WO queda BLOCKED con reason="depends_on_incomplete".

P4) Ejecutar cada WO:
    - Extraer campos indicados en targets.fields desde sources_pack.
    - Cada campo debe tener evidencia: source_id + ubicación + cita ≤25 palabras.

P5) Crear/actualizar TruthPack_v1 con los campos extraídos.

P6) ACTUALIZAR PatchBundle_v3:
    - Preservar TODO el contenido del input.
    - artifact_updates.truth_pack := TruthPack_v1 generado.
    - current_step := input.current_step + 1.
    - Añadir tu report a patch_reports[].

P7) Salida: SOLO JSON `PatchBundle_v3` actualizado.

## 8. ESQUEMAS
- TruthPack_v1.json
- SourcesPack_v1.json
- PatchBundle_v3.json
- RemediationPlan_v1.json
