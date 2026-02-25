A continuación aplico los criterios del proyecto para auditar la **calidad de la decisión del ARBITRO** (no la "verdad" última del caso), siguiendo los ejes de coherencia, rigor de gates, supuestos críticos, escenarios, sizing, puntos ciegos y coherencia probabilística↔categórica definidos en el marco de Meta-Review. 

## 1) Veredicto meta (alto nivel)

**Mi veredicto meta: CONFIRMA (con condiciones menores).**
La decisión **WATCHLIST con sizing 0%** es prudente y está bien alineada con los principales bloqueadores que el propio DecisionPacket documenta: catalizador central **no confirmado** (normalización de capex), **opacidad contable severa** (EBIT ausente + 84% null trimestral) y **ausencia de covenants/vencimientos** que impide auditar el riesgo financiero de cola. La robustez de liquidez/FCF histórico parece suficiente para justificar que el **survivability_gate sea CONDITIONAL y no FAIL**, y por tanto **no bloquea** la salida "WATCHLIST", pero *sí exige* que el caso permanezca en espera hasta obtener las fuentes ALTA prioridad ya listadas.

Dicho eso, detecto **una inconsistencia numérica interna** en el bloque probabilístico (ver sección 5), y un par de puntos donde el ARBITRO usa PASS de forma algo "optimista" (catalyst_gate) pese a reconocer explícitamente incertidumbre de timing/probabilidad.

---

## 2) Evaluación específica del survivability_gate (área de especial atención)

### Lo que el ARBITRO afirma

En `gates.survivability_gate.status = CONDITIONAL`, el ARBITRO justifica que:

* hay **liquidez robusta** (caja ~US$341M) y **CFO FY2024 ~US$434.6M**, con un "runway" ~24 meses;
* aun incluyendo leases (US$177.7M) el margen de seguridad se reduce, pero no se anula;
* **falta** tabla de vencimientos y covenants → riesgo de refinanciación "no auditable 100%".

Y define condiciones verificables: `headroom >=20%`, `caja > US$200M y FCF TTM positivo`, `no breach/waiver`.

### ¿Es suficiente para **no bloquear** el gate?

**Sí, para el estado WATCHLIST (sizing 0).**
Razonamiento:

1. **CONDITIONAL está bien elegido**: la falta de `maturity ladder` y `covenants` es precisamente el tipo de laguna que impide un PASS limpio (y el propio ARBITRO lo reconoce). En un sistema gateado, el error sería marcar PASS con este nivel de opacidad.

2. **No hay evidencia de estrés de liquidez inmediato** en el propio paquete: el caso se apoya en caja grande, CFO positivo histórico, y no sugiere necesidad de financiación salvadora. Esto encaja con las restricciones del charter ("exigir supervivencia 12-24 meses razonable").

3. **El no-bloqueo es coherente con el "tratamiento"**: el ARBITRO ya impone el freno principal en el sizing (`sizing_final_pct = 0`) y en el estado `EN_ESPERA`, por lo que no está usando CONDITIONAL como "PASS blando para invertir". Aquí el CONDITIONAL funciona como debe: "se puede seguir (watchlist), pero no se puede entrar (invertir) sin datos".

### Donde la justificación es mejorable (pero no invalida)

* El ARBITRO usa un número agregado "**servicio de deuda+leases = US$84.6M/año**" sin mostrar trazabilidad directa a una fuente dentro del propio DecisionPacket (no aparece como evidencia `source_id` en el gate). Esto es **debilidad de evidencia**: el argumento sigue siendo plausible, pero debería anclarse (interest expense + lease payments + amortizaciones obligatorias si existieran).
* **No integra explícitamente decommissioning** en survivability (aunque lo menciona como punto abierto). En offshore E&P este pasivo puede ser material y, si tiene calendario cercano, afecta supervivencia. No digo que exista el problema; digo que *no está incorporado*.

**Conclusión survivability_gate:**

* **Meta-evaluación:** CORRECTO (CONDITIONAL) y **justificación suficiente** para no bloquear *en WATCHLIST*.
* Para **INVERTIR**, este gate seguiría siendo bloqueador hasta extraer: covenants/headroom + maturity ladder + (idealmente) decommissioning schedule.

---

## 3) Rigor y coherencia de los otros gates (visión de comité)

### data_quality_gate = PASS

* **Coherente** con que el pipeline pasó identidades contables y el implied convergió; además el ARBITRO documenta explícitamente faltantes críticos (EBIT, CFO/FCF FY2025 auditado, acciones diluidas, vencimientos/covenants).
* **Pero**: el propio contexto reporta `TP_EXTRACTOR_FILING = 61.1` (bajo), y hay 84% de nulos trimestrales. Esto no exige FAIL (porque hay suficiente para WATCHLIST), pero sí amerita que el pipeline genere "issues/work_orders" formales (hoy `control.issues` está vacío) para remediación.

**Meta:** PASS es aceptable; el sistema está "honesto" sobre limitaciones.

### mispricing_gate = PASS

* Tiene sentido dado EV/FCF ~4.1x y el reverse-DCF extremo; y el ARBITRO reconoce explícitamente que *depende* de reservas y de capex.
* No veo salto lógico: "hay indicio de infravaloración" ≠ "hay que invertir ya".

**Meta:** CORRECTO.

### catalyst_gate = PASS (aquí estoy más crítico)

El ARBITRO dice que hay 3–4 catalizadores medibles, pero también:

* el catalizador #1 (capex) **carece de confirmación directa** (sin guidance) y hay tendencia histórica creciente;
* "se requiere combinación de 2–3 catalizadores" para revertir narrativa.

Eso suena más a **CONDITIONAL** que a PASS. No porque no existan catalizadores, sino porque el "quality/timing confidence" es explícitamente media-baja y el motor de cierre del gap es el mismo supuesto central no resuelto (A-001).

**Meta:** CUESTIONABLE (no invalida la decisión WATCHLIST, pero el label PASS es optimista vs la propia narrativa).

### non_speculative_gate = PASS

* El ARBITRO marca "opacidad_inaceptable: false". Dado que se decide WATCHLIST con sizing 0, no es incoherente: no hay tesis binaria de financiación, hay caja y activos en producción.
* Pero el texto "caja neta positiva y FCF positivo eliminan necesidad de mercados" debería estar formulado **en términos ajustados por leases** (A-005), porque el propio paquete acepta que la "caja neta" reportada era ilusoria sin leases.

**Meta:** CORRECTO pero con matiz de redacción/consistencia.

---

## 4) Supuestos críticos (evaluación individual)

Me centro en los **CRITICO** del assumption_ledger, como exigen las reglas del review. 

### A-001 (Capex FY2026 normaliza a 130–150)

* Evidencia: FY2024 capex ~135 como "nivel pre-ciclo"; FY2025 204 como "pico"; patrón Q3/Q4.
* Problema: el propio paquete reconoce tendencia 4 años **monótonamente creciente** y no hay guidance ni split maintenance vs development. Además, el argumento "capex pico concentrado en Q4" es débil si el año total es 204 y el Q4 citado es 44 (esto no prueba "fin de proyecto").
* Prob 0.58: **ligeramente optimista** para un supuesto "más sensible del caso".

**Meta:** INSUFICIENTE_EVIDENCIA / OPTIMISTA suave → yo bajaría hacia ~0.50 (no por convicción bajista, sino por falta de confirmación).

### A-002 (Ingresos estabilizan >150M trimestral)

* Evidencia disponible es más bien adversa (Q3 164 → Q4 156). No hay descomposición precio/volumen.
* Prob 0.52: me parece **optimista** dado el dato observado y la falta total de drivers cuantificados.

**Meta:** OPTIMISTA → sugerir ~0.45.

### A-003 (FCF FY2025 auditado >100M)

* El ARBITRO hace una inferencia razonable desde CFO margin FY2024 y revenue FY2025.
* El riesgo es que CFO margin no sea estable (costes/uptime/precio realizado), pero el umbral ">100M" no es agresivo.

**Meta:** RAZONABLE → ~0.55–0.60 (no cambiaría mucho).

### A-004 (Caja neta ex-leases positiva o neutra en FY2026)

* Importante: "positiva o neutra" es una meta amplia.
* Aun así, la "caja neta" está muy cerca de cero (341 vs 333.5), por lo que pequeños cambios la vuelven negativa. Con capex alto y revenue en caída, el riesgo de pasar a net debt ex-leases existe.

**Meta:** OPTIMISTA → sugerir ~0.65 (no 0.77).

### A-005 (Leases elevan deuda neta ajustada a ~170)

* Está bien tratado como HECHO y CONFIRMADA, y corrige el sesgo del BULL.
  **Meta:** RAZONABLE.

### A-009 (Reservas vida >7 años; decline <20%)

* No hay evidencia. La prob 0.5 es un "coin flip", correcto como placeholder, pero el problema es que este supuesto es **prueba definitiva** de la tesis run-off y está completamente a oscuras.

**Meta:** INSUFICIENTE_EVIDENCIA (no propongo número alternativo sin dato).

### A-014 (Sin stress de covenants/vencimientos)

* No hay evidencia, solo ausencia de disclosure. Este supuesto debería estar tratado casi como "UNKNOWN".
* Prob 0.55: lo veo demasiado "puntual" para algo no auditable.

**Meta:** INSUFICIENTE_EVIDENCIA → sugerir 0.50 o incluso menos, pero lo importante es **forzar remediación** (extraer covenants y maturity ladder).

---

## 5) Escenarios y coherencia probabilística (y una inconsistencia numérica)

### Escenarios

* Probabilidades: BASE 0.45 + BULL 0.20 + BEAR 0.35 = 1.00 ✅
* Drivers: diferenciados, aunque BASE depende fuerte de A-001 y A-002 (no resueltos), por lo que 0.45 podría ser alta, pero no es absurda dado el enfoque "watchlist".

### Problema detectado (contradicción interna)

En `decision_probabilistica.retorno_esperado_ponderado_pct = 16.2`, pero con los retornos de `escenarios_ponderados` (base 25, bull 70, bear -22) el esperado sería 17.55.
El 16.2 cuadra si BASE fuera 22% (0.45*22 + 0.2*70 + 0.35*-22 = 16.2). Esto sugiere que el paquete mezcla "base 22" y "base 25" en secciones distintas.

**Esto es una contradicción formal** que no cambia la decisión (WATCHLIST), pero sí reduce confianza en la consistencia del bloque probabilístico y debería corregirse en el ARBITRO.

---

## 6) Sizing y Kelly

* El ARBITRO calcula `kelly_ajustado_pct = 12.8` y lo topa a 10% preliminar, pero fija `sizing_final_pct = 0` por decisión WATCHLIST.
  Esto es **metodológicamente correcto** (solo sizing >0 si INVERTIR) y consistente con el mandato no especulativo y la opacidad existente. 

**Meta:** ADECUADO.

---

## 7) Kill criteria: calidad y cobertura del BEAR

Los KC son en general:

* **específicos** (umbrales numéricos),
* **accionables** (SALIR/REDUCIR/CONGELAR),
* cubren los ejes del BEAR: decline de ingresos, FCF colapsado, capex estructural alto, deterioro de liquidez, eventos financieros (breach/waiver) e impairment.

Punto de mejora: KC-003 depende de "incremento de producción >10% YoY", pero el paquete admite que no hay producción por activo hoy; esto requiere asegurar que la fuente de producción sea pública y recurrente (quarterly production report).

---

## 8) Puntos ciegos relevantes (que sí pueden mover el caso)

Además de los ya listados, yo elevaría como **puntos ciegos** para comité:

1. **Decommissioning / ARO** (desmantelamiento offshore): puede ser material y afectar EV económico y/o liquidez si hay calendario cercano.
2. **Términos del lease/FPSO**: duración remanente, indexación, opciones de renovación, penalidades; los leases aquí son "deuda operativa esencial" y merecen tratamiento casi como deuda senior.
3. **Precio realizado y hedging**: sin esto, A-006 (precio vs volumen) es conjetural y también lo es la sensibilidad "US$5/bbl = US$30–50M FCF".
4. **Riesgo operativo offshore**: uptime, incidentes, meteo, huracanes (Golfo), Brasil licensing/regulatorio; puede crear shocks de producción.
5. **Riesgo FX / reporting**: empresa ASX, pero cifras en USD; posibles descalces y sensibilidad (no cuantificada).
6. **Liquidez del activo / microestructura** (ASX): relevante para sizing futuro, aunque hoy es 0%.

---

## 9) Recomendaciones concretas (qué cambiaría en el DecisionPacket)

**ALTA (ARBITRO / PIPELINE)**

* Corregir la **inconsistencia** `retorno_esperado_ponderado_pct` vs `escenarios_ponderados` (base 22 vs 25).
* Re-etiquetar `catalyst_gate` a **CONDITIONAL** o justificar mejor por qué PASS pese a que el catalizador #1 no está confirmado y se requieren 2–3 catalizadores.
* Convertir faltantes críticos en `control.issues/work_orders` (hoy vacío) para forzar remediación: covenants/headroom, maturity ladder, EBIT, reservas, producción, ARO.

**MEDIA**

* En survivability, anclar con evidencia el número "servicio deuda+leases 84.6M/año" o eliminarlo si no se puede trazar.
* Ajustar A-004 (caja neta ex-leases) a una probabilidad menos agresiva o redefinir el enunciado con tolerancia explícita (p.ej., "deuda neta ex-leases < US$150M").

**BAJA**

* Arreglar referencias de claims (p.ej. aparece `CLM_F07` pero el listado Bull llega a CLM_F06): es un problema formal pequeño pero indica riesgo de "drift" al compilar.

---

# Bloque JSON MetaReview_v1 (obligatorio) 

```json
{
  "version_esquema": "MetaReview_v1",
  "caso_id": "CASE_20260222_KAR",
  "fecha_review": "2026-02-24T14:30:00+01:00",
  "reviewer": {
    "modelo": "gpt-5.2-pro",
    "plataforma": "chatgpt",
    "proyecto": "ELSIAN Meta-Review"
  },
  "decision_packet_ref": "DecisionPacket_v2_CASE_20260222_KAR (embebido en el prompt del Meta-Review)",
  "decision_packet_snapshot": {
    "hash_sha256": "NO_EVALUABLE",
    "timestamp_compilacion": "2026-02-24T14:06:44+01:00",
    "revision_num": 1
  },
  "veredicto_meta": {
    "estado": "CONFIRMA",
    "confianza_review_0_1": 0.72,
    "resumen_1_parrafo": "La decisión WATCHLIST con sizing 0% está bien fundamentada: existe señal de mispricing (EV/FCF ~4x) pero el caso depende críticamente de supuestos no confirmados (normalización de capex, estabilización de ingresos, reservas/decline rates) y sufre opacidad material (EBIT ausente, 84% nulos trimestrales) además de falta de covenants/vencimientos. El survivability_gate en CONDITIONAL está correctamente aplicado y suficientemente justificado para no bloquear el estado WATCHLIST, aunque requiere remediación antes de cualquier upgrade a INVERTIR. Se detecta una inconsistencia interna menor en el cálculo de retorno esperado ponderado del bloque probabilístico."
  },
  "evaluacion_gates": [
    {
      "gate": "data_quality_gate",
      "arbitro_dijo": "PASS",
      "meta_evaluacion": "CORRECTO",
      "justificacion": "Para WATCHLIST es aceptable: se documentan explícitamente faltantes críticos (EBIT, covenants/vencimientos, FY2025 auditado) y se evita tomar sizing. No obstante, la incompletitud trimestral y el extractor de filings débil justifican abrir work_orders de remediación.",
      "riesgo_oculto": "El PASS puede inducir complacencia: la ausencia de EBIT y de vencimientos/covenants limita auditoría de riesgos y debería activar issues/work_orders automáticos."
    },
    {
      "gate": "survivability_gate",
      "arbitro_dijo": "CONDITIONAL",
      "meta_evaluacion": "CORRECTO",
      "justificacion": "La etiqueta CONDITIONAL es adecuada: hay caja y CFO histórico material que sugieren supervivencia 12-24 meses, pero sin covenants/maturity ladder el riesgo de cola no es auditable. El no-bloqueo es coherente porque la decisión final es WATCHLIST con sizing 0%.",
      "riesgo_oculto": "Posibles obligaciones de desmantelamiento (decommissioning/ARO) y un posible vencimiento concentrado de deuda podrían cambiar el perfil de supervivencia si aparecen en notas del filing."
    },
    {
      "gate": "mispricing_gate",
      "arbitro_dijo": "PASS",
      "meta_evaluacion": "CORRECTO",
      "justificacion": "La narrativa de mispricing es coherente con múltiplos extremos, pero el propio ARBITRO reconoce que la refutación de 'run-off' depende de reservas/decline rates y de capex. PASS es aceptable para WATCHLIST porque no implica entrada inmediata.",
      "riesgo_oculto": "El mercado puede estar descontando correctamente una vida corta de reservas; sin 2P life/decline rates el mispricing puede ser aparente."
    },
    {
      "gate": "catalyst_gate",
      "arbitro_dijo": "PASS",
      "meta_evaluacion": "CUESTIONABLE",
      "justificacion": "Existen catalizadores medibles (capex, ramp-up, retorno de capital), pero el catalizador principal carece de evidencia confirmatoria (sin guidance FY2026 y tendencia histórica de capex creciente). Esto se parece más a un CONDITIONAL que a un PASS, aunque no invalida WATCHLIST.",
      "riesgo_oculto": "Dependencia conjunta de 2-3 catalizadores reduce probabilidad efectiva; sin producción por activo/uptime la monitorización temprana puede fallar."
    },
    {
      "gate": "non_speculative_gate",
      "arbitro_dijo": "PASS",
      "meta_evaluacion": "CORRECTO",
      "justificacion": "La decisión WATCHLIST y el énfasis en kill criteria reducen el riesgo de tesis binaria; además no hay dependencia explícita de financiación salvadora. La opacidad es alta pero tratada con prudencia (sizing 0%).",
      "riesgo_oculto": "La redacción sobre 'caja neta' puede inducir sesgo si no se usa siempre la métrica ajustada por leases; también falta cuantificación de riesgos offshore (ARO, uptime, eventos operativos)."
    }
  ],
  "evaluacion_supuestos_criticos": [
    {
      "assumption_id": "A-001",
      "enunciado": "El capex FY2025 de US$203.8M es transitorio (ciclo de desarrollo) y se normalizará a US$130-150M en FY2026, liberando US$50-70M de FCF incremental.",
      "arbitro_probabilidad": 0.58,
      "meta_evaluacion": "INSUFICIENTE_EVIDENCIA",
      "justificacion": "Es el supuesto más sensible y no hay guidance FY2026 ni desglose mantenimiento/desarrollo. La evidencia citada (FY2024 como referencia y patrón Q3/Q4) es débil frente a la tendencia de 4 años creciente; la probabilidad parece ligeramente optimista.",
      "sugerencia_probabilidad_0_1": 0.5
    },
    {
      "assumption_id": "A-002",
      "enunciado": "Los ingresos trimestrales se estabilizarán por encima de US$150M en FY2026, deteniendo la tendencia de caída.",
      "arbitro_probabilidad": 0.52,
      "meta_evaluacion": "OPTIMISTA",
      "justificacion": "Los últimos puntos observados (Q3→Q4) son descendentes y no hay descomposición precio/volumen ni KPI operativo que apoye estabilización. La probabilidad debería penalizar más la evidencia adversa y la incertidumbre.",
      "sugerencia_probabilidad_0_1": 0.45
    },
    {
      "assumption_id": "A-003",
      "enunciado": "El FCF FY2025 auditado será positivo y material (>US$100M).",
      "arbitro_probabilidad": 0.6,
      "meta_evaluacion": "RAZONABLE",
      "justificacion": "La inferencia desde CFO margin FY2024 y revenue FY2025 hace que >US$100M sea un umbral plausible, aunque depende de que la conversión a caja no se haya deteriorado materialmente.",
      "sugerencia_probabilidad_0_1": 0.55
    },
    {
      "assumption_id": "A-004",
      "enunciado": "La posición de caja neta (excluyendo leases) se mantendrá positiva o neutra durante FY2026.",
      "arbitro_probabilidad": 0.77,
      "meta_evaluacion": "OPTIMISTA",
      "justificacion": "La caja neta ex-leases está cerca de cero; pequeños cambios en FCF/capex la vuelven negativa. Sin guidance de capex y con ingresos en caída, 0.77 parece alto.",
      "sugerencia_probabilidad_0_1": 0.65
    },
    {
      "assumption_id": "A-005",
      "enunciado": "Los lease liabilities de US$177.7M son obligaciones financieras reales que elevan la deuda neta ajustada a ~US$170M.",
      "arbitro_probabilidad": 0.97,
      "meta_evaluacion": "RAZONABLE",
      "justificacion": "Está tratado como HECHO y confirmado; la inclusión de leases corrige un sesgo importante del caso alcista y mejora el realismo del análisis de solvencia.",
      "sugerencia_probabilidad_0_1": 0.97
    },
    {
      "assumption_id": "A-009",
      "enunciado": "Las reservas 1P/2P de KAR tienen vida útil >7 años con decline rates <20% anuales.",
      "arbitro_probabilidad": 0.5,
      "meta_evaluacion": "INSUFICIENTE_EVIDENCIA",
      "justificacion": "No hay evidencia aportada; es el dato decisivo para refutar o validar la narrativa de run-off. La probabilidad 0.5 es un placeholder razonable pero la situación es no auditable sin el reporte de reservas.",
      "sugerencia_probabilidad_0_1": null
    },
    {
      "assumption_id": "A-014",
      "enunciado": "No existen covenants financieros que se activen con la caída actual, ni vencimientos concentrados de deuda en 12-18 meses.",
      "arbitro_probabilidad": 0.55,
      "meta_evaluacion": "INSUFICIENTE_EVIDENCIA",
      "justificacion": "La ausencia de disclosure no es evidencia positiva; el supuesto debería tratarse como incertidumbre material. La probabilidad debería ser más neutra y el pipeline debería forzar extracción de covenants y maturity ladder.",
      "sugerencia_probabilidad_0_1": 0.5
    }
  ],
  "evaluacion_escenarios": {
    "base": {
      "arbitro_probabilidad": 0.45,
      "arbitro_retorno": 25,
      "meta_evaluacion": "OPTIMISTA",
      "justificacion": "El BASE depende simultáneamente de A-001 y A-002 (no confirmados) y de un rerating; 0.45 puede ser algo alto sin guidance de capex ni datos de reservas/producción."
    },
    "bull": {
      "arbitro_probabilidad": 0.2,
      "arbitro_retorno": 70,
      "meta_evaluacion": "REALISTA",
      "justificacion": "El retorno es alto pero plausible si confluyen 2-3 catalizadores; la probabilidad 0.2 ya refleja esa exigencia conjunta."
    },
    "bear": {
      "arbitro_probabilidad": 0.35,
      "arbitro_retorno": -22,
      "meta_evaluacion": "PESIMISTA",
      "justificacion": "El BEAR podría ser más severo en un shock de commodity o si hay impairment/maturity wall; aun así, el ARBITRO incluye un rango mínimo -45% y la caja amortigua el caso base -22%."
    }
  },
  "evaluacion_sizing": {
    "kelly_ajustado_arbitro": 12.8,
    "sizing_final_arbitro": 0,
    "meta_evaluacion": "ADECUADO",
    "justificacion": "El sizing final 0% es prudente y consistente con WATCHLIST y con los bloqueadores críticos (capex no confirmado, reservas/covenants no auditables, opacidad contable).",
    "sizing_sugerido_0_1": null
  },
  "coherencia_logica": {
    "score_0_10": 7,
    "problemas_detectados": [
      {
        "tipo": "CONTRADICCION",
        "descripcion": "El retorno_esperado_ponderado_pct (16.2) no cuadra con los retornos de escenarios_ponderados (25/70/-22); sugiere mezcla interna (BASE=22 vs BASE=25).",
        "seccion_afectada": "decision_probabilistica.retorno_esperado_ponderado_pct vs decision_probabilistica.escenarios_ponderados",
        "severidad": "MEDIA"
      },
      {
        "tipo": "EVIDENCIA_DEBIL",
        "descripcion": "El argumento de capex 'concentrado en Q4' no prueba transitoriedad dado que FY2025 capex total es 203.8M y el Q4 citado (44M) no explica el total anual.",
        "seccion_afectada": "assumption_ledger.A-001.evidencias + notas_arbitro",
        "severidad": "ALTA"
      },
      {
        "tipo": "SALTO_LOGICO",
        "descripcion": "catalyst_gate marcado PASS pese a reconocer que el catalizador principal carece de confirmación y que se requieren 2-3 catalizadores para revertir narrativa.",
        "seccion_afectada": "gates.catalyst_gate",
        "severidad": "MEDIA"
      },
      {
        "tipo": "OMISION",
        "descripcion": "No se integra explícitamente decommissioning/ARO en la evaluación de supervivencia, pese a que se reconoce como punto abierto material en offshore E&P.",
        "seccion_afectada": "gates.survivability_gate + arbitraje.puntos_abiertos",
        "severidad": "MEDIA"
      },
      {
        "tipo": "CONTRADICCION",
        "descripcion": "Referencias de claim parecen inconsistentes (aparece CLM_F07 en el ledger, pero el listado BULL visible llega a CLM_F06), indicando drift de compilación.",
        "seccion_afectada": "assumption_ledger.A-003.origen",
        "severidad": "BAJA"
      }
    ]
  },
  "puntos_ciegos": [
    {
      "descripcion": "Obligaciones de desmantelamiento offshore (decommissioning/ARO) y su calendario, potencialmente material para liquidez y EV económico.",
      "impacto_potencial": "ALTO",
      "sugerencia": "Extraer ARO y notas de desmantelamiento del annual report; incorporar umbrales (ARO/caja, ARO/CFO) y, si hay calendario cercano, reflejarlo en survivability y BEAR."
    },
    {
      "descripcion": "Maturity ladder y covenants/headroom: sin ellos no se puede auditar riesgo de refinanciación o eventos binarios (waiver/breach).",
      "impacto_potencial": "ALTO",
      "sugerencia": "Work order a TRUTH_PACK para extraer covenants, definiciones, headroom y vencimientos; añadir kill criteria específico a 'maturity wall' si existe."
    },
    {
      "descripcion": "Precio realizado por barril y política de hedging: sin descomposición precio/volumen, la tesis de reversibilidad de ingresos no es evaluable.",
      "impacto_potencial": "MEDIO",
      "sugerencia": "Pedir realized price, volúmenes y coberturas por trimestre; recalibrar A-006 y sensibilidad de FCF a commodity con datos propios del filing."
    },
    {
      "descripcion": "Riesgo operativo offshore (uptime FPSO, incidentes, estacionalidad climática) que puede provocar shocks de producción e ingresos.",
      "impacto_potencial": "MEDIO",
      "sugerencia": "Exigir KPI operativo recurrente (uptime, lifting costs, producción por activo) y enlazarlo a tests confirmatorios de C-002 y KC-003."
    },
    {
      "descripcion": "Riesgo de calidad de earnings (gap NI+D&A vs CFO) sin reconciliación detallada puede ocultar elementos no sostenibles.",
      "impacto_potencial": "MEDIO",
      "sugerencia": "Extraer reconciliación CFO detallada y separar WC, impuestos, partidas no recurrentes; definir umbral de alerta si ajustes no-cash recurrentes > X."
    }
  ],
  "coherencia_probabilistica_categorica": {
    "alineadas": true,
    "incongruencias": [
      "probabilidad_exito_0_1 = 0.65 podría sugerir más convicción, pero se compensa con factor de confianza bajo y sizing_final = 0 por catalizador no confirmado."
    ],
    "justificacion": "La decisión WATCHLIST es coherente con el hecho de que la probabilidad de éxito deriva de escenarios (base+bull) pero el catalizador principal y datos críticos no están confirmados; por mandato no especulativo, el sistema prioriza esperar evidencia antes de asignar capital."
  },
  "recomendaciones": [
    {
      "prioridad": "ALTA",
      "accion": "Corregir inconsistencia interna: retorno_esperado_ponderado_pct debe recalcularse con los mismos retornos de escenarios_ponderados (o alinear BASE=22/25 en todos los campos).",
      "dirigida_a": "ARBITRO"
    },
    {
      "prioridad": "ALTA",
      "accion": "Convertir catalyst_gate a CONDITIONAL o justificar cuantitativamente por qué PASS pese a falta de guidance y dependencia de 2-3 catalizadores; ajustar probabilidad del catalizador C-001 si se mantiene PASS.",
      "dirigida_a": "ARBITRO"
    },
    {
      "prioridad": "ALTA",
      "accion": "Crear issues/work_orders formales para extracción de covenants/headroom, maturity ladder, reservas 2P/decline rates, precio realizado/hedging y ARO/decommissioning; hoy la sección control.issues está vacía pese a faltantes críticos.",
      "dirigida_a": "PIPELINE"
    },
    {
      "prioridad": "MEDIA",
      "accion": "En survivability_gate, anclar con fuente el número 'servicio de deuda+leases' o eliminarlo; mantener CONDITIONAL hasta contar con evidencias trazables.",
      "dirigida_a": "ARBITRO"
    },
    {
      "prioridad": "BAJA",
      "accion": "Arreglar referencias de claim_id en assumption_ledger para evitar drift (p.ej., CLM_F07 inexistente en el extracto mostrado).",
      "dirigida_a": "PIPELINE"
    }
  ],
  "meta_decision": {
    "accion": "APROBAR_CON_CONDICIONES",
    "condiciones": [
      "Antes de cualquier upgrade a INVERTIR: obtener Annual Report FY2025 auditado con CFO/FCF y línea EBIT/Operating Income.",
      "Obtener maturity ladder y covenants con headroom; si no se publica, mantener survivability_gate en CONDITIONAL y no permitir sizing > 0.",
      "Obtener reporte de reservas 2P con vida útil/decline rates y producción por activo; sin ello, mantener A-009 en INSUFICIENTE_EVIDENCIA.",
      "Corregir inconsistencia del retorno esperado ponderado vs retornos de escenarios."
    ],
    "siguiente_paso_sugerido": "MONITOR (modo_evento): disparar revisión en cuanto se publique Annual Report FY2025 y/o guidance FY2026 de capex."
  },
  "evaluacion_calidad_pipeline": [
    {
      "paso": "ARBITRO",
      "score_fusion": 99.9,
      "evaluacion_meta": "ADECUADO",
      "comentario": "Alta consistencia formal; el paquete documenta desacuerdos y faltantes críticos."
    },
    {
      "paso": "BULL",
      "score_fusion": 100.0,
      "evaluacion_meta": "ADECUADO",
      "comentario": "Caso alcista estructurado, pero su claim central depende de A-001 no confirmado."
    },
    {
      "paso": "RED_TEAM",
      "score_fusion": 100.0,
      "evaluacion_meta": "ADECUADO",
      "comentario": "Corrección de leases (A-005) fue crítica y bien incorporada."
    },
    {
      "paso": "FORENSIC_SCORING",
      "score_fusion": 98.8,
      "evaluacion_meta": "ADECUADO",
      "comentario": "Identifica opacidad y ajusta solvencia por leases; faltan covenants/vencimientos."
    },
    {
      "paso": "TP_EXTRACTOR_FILING",
      "score_fusion": 61.1,
      "evaluacion_meta": "PREOCUPANTE",
      "comentario": "Consistente con faltantes críticos (EBIT, trimestrales, covenants); requiere remediación estructural."
    }
  ],
  "desacuerdos_agentes": {
    "resolucion_arbitro_correcta": true,
    "desacuerdos_mal_resueltos": null,
    "comentarios": "El ARBITRO resolvió correctamente leases (adopta métrica ajustada) y convirtió el desacuerdo de capex/value trap en escenarios, evitando falsa certeza."
  },
  "kill_criteria_evaluacion": {
    "completos": true,
    "accionables": true,
    "especificos": true,
    "cubren_bear_scenario": true,
    "comentarios": "Los KC incluyen umbrales numéricos y acciones proporcionales. KC-003 requiere disponer de datos de producción para ser plenamente verificable."
  },
  "_meta": {
    "motor": "ASISTIDO",
    "plataforma": "chatgpt",
    "modelo": "gpt-5.2-pro",
    "proyecto_chatgpt": "ELSIAN Meta-Review",
    "timestamp": "2026-02-24T14:30:00+01:00",
    "version_protocolo": "MetaReview_v1"
  }
}
```
