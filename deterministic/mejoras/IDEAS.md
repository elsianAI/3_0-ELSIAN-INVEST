# Ideas de Mejora — Módulo Deterministic

Backlog informal de ideas descubiertas durante el desarrollo. No son tareas planificadas, solo semillas para evaluar cuando toque.

---

### 1. iXBRL como fuente primaria de extracción
Ya existe `scripts/runners/ixbrl_extractor.py` que genera `.ixbrl.json` con datos estructurados (tags GAAP, periodos, escala, segmento vs consolidado). El módulo deterministic podría consumir estos JSON como fuente primaria y usar el parsing de tablas HTML solo como fallback para filings sin iXBRL (8-K, pre-2019, europeos). Eliminaría de raíz la mayoría de bugs de escala, alias y confusión segmento/consolidado.

### 2. Descarga de Exhibit 99 en 6-K
Los 6-K de foreign private issuers (ej: GCT pre-2023) son wrappers vacíos — el contenido financiero está en el Exhibit 99.1 adjunto. `sec_edgar.py` descarga la portada pero no el exhibit. Mejorar el fetcher para seguir el índice del filing y descargar también los exhibits con datos financieros.

### 3. Validación cruzada iXBRL vs tablas HTML
Usar ambas fuentes en paralelo para detectar inconsistencias: si el iXBRL dice revenue=1,289,897 y la tabla HTML dice 1,289,897, confianza alta. Si difieren, flag para revisión. Esto convertiría el extractor de tablas en un verificador en vez de fuente primaria.

### 4. Capa 2 — Extracción de señales cualitativas de filings
Los 10-K/10-Q ya descargados contienen MD&A (Management Discussion & Analysis) y Risk Factors con información cualitativa muy valiosa que hoy no procesamos. Ideas concretas: comparar risk factors entre periodos (qué apareció nuevo, qué desapareció), detectar cambios de tono en el MD&A, extraer guidance cuantitativa ("we expect revenue in the range of..."), detectar cambios en políticas contables, litigios nuevos. Esto requiere LLM pero con trazabilidad al párrafo exacto del filing. Los datos ya están descargados — solo falta procesarlos.

### 5. Arquitectura de producción: deterministic + LLM fallback
En producción no habrá ground truth curado. El pipeline debería funcionar en dos fases: primero la extracción determinista (iXBRL + tablas) saca todo lo que puede con confianza alta; después un LLM revisa lo que falta o tiene confianza baja y lo completa. El GT solo existe en fase de entrenamiento para validar que las reglas deterministas son correctas.

### 6. Cobertura iXBRL: limitaciones geográficas
iXBRL es obligatorio para toda empresa que file con la SEC (incluidas micro-caps y small-caps), así que cubre cualquier empresa americana o foreign private issuer. Para empresas europeas existe ESEF (European Single Electronic Format) con iXBRL obligatorio desde 2021. Para empresas asiáticas u otros mercados, la cobertura es irregular. El pipeline deberá tener fallbacks distintos según la geografía.

### 7. Fuentes no descargadas actualmente
Cosas que podrían aportar valor cualitativo pero que hoy no descargamos: DEF14A/proxy statements (compensación ejecutiva, governance, votaciones), investor presentations (no están en EDGAR, están en webs de IR — no hay API estándar), audio de earnings calls (speech-to-text para análisis de tono de voz del management). Prioridad: DEF14A > presentaciones > audio. Los transcripts de earnings calls ya se descargan en el pipeline principal.

### 8. Cobertura iXBRL global — mapa por región
No existe un "EDGAR global". Cada región tiene su propio sistema: USA → SEC EDGAR (API gratis, cobertura total), Europa → ESEF vía OAMs nacionales (CNMV, AMF, BaFin...) + índice agregado en filings.xbrl.org (~23k filings, 27 países), Japón → EDINET (bueno), China → CNINFO (difícil acceso externo), India → MCA V3 (modernizado recientemente). Para el pipeline global habrá que construir fetchers por regulador. El formato iXBRL es estándar pero el acceso no.

### 9. Estrategia de implementación: HTML/PDF primero, iXBRL después
Decisión de diseño: perfeccionar primero el extractor HTML/PDF (tablas + narrativas) hasta que sea robusto contra múltiples tickers y geografías. Este extractor siempre será necesario como fallback universal (filings sin iXBRL, 8-K earnings, empresas de mercados sin mandato XBRL, PDFs de informes anuales europeos). Una vez estable, añadir iXBRL como módulo independiente que, donde esté disponible, actúa como fuente primaria de mayor confianza. La capa de evaluación y trazabilidad sirve para ambas fuentes sin cambios.

### 10. Refactor a arquitectura basada en clases
**PRIORIDAD ALTA — hacer antes de añadir el primer módulo nuevo (iXBRL o segundo regulador).**

La estructura actual (funciones sueltas orquestadas por un facade) no escala. Cada fase del pipeline debe ser una clase con interfaz tipada (`run(context) -> result`), permitiendo múltiples implementaciones intercambiables por fase.

Diseño objetivo:
- `PipelinePhase` (clase base): contrato `run(PipelineContext) -> PhaseResult`.
- `AcquirePhase`: recibe lista de `Fetcher` (SecEdgarFetcher, EsefFetcher, ManualFetcher...). Elige según `source_hint` del case.json.
- `ExtractPhase`: recibe lista de `Extractor` (IxbrlExtractor, TableExtractor, NarrativeExtractor). Prioriza iXBRL si existe, fallback a tablas.
- `NormalizePhase`: alias + scale + audit (se mantiene similar pero encapsulado).
- `MergePhase`: merge multi-filing actual + futuro merge multi-fuente (iXBRL vs HTML vs LLM).
- `EvaluatePhase`: comparación vs expected.json (solo en desarrollo/testing).
- `DeterministicPipeline`: orquestador que encadena fases. No contiene lógica de negocio.
- `PipelineContext`: objeto compartido que lleva trazabilidad, audit log, confianza por dato.

Ventajas: añadir un nuevo fetcher o extractor = crear una clase y registrarla. Testear = mockear una fase y probar las demás aisladas. El pipeline se configura por composición, no por if/else.

Momento del refactor: cuando TZOO y GCT estén estables y antes de integrar iXBRL o un segundo regulador. Así se refactoriza con conocimiento real de lo que necesitan las clases.

---

### 11. ELSIAN-INVEST 4.0 — Rediseño completo del sistema
**DECISIÓN ESTRATÉGICA. No es una mejora del 3.0 — es su reemplazo.**

#### Contexto
El 3.0 está congelado. Ninguno de los tickers que contiene tenía los datos financieros correctamente extraídos — esa fue precisamente la razón de crear el módulo `deterministic`. El 3.0 sirvió como laboratorio para descubrir qué funciona y qué no: qué fuentes de datos existen, cómo se estructuran los filings, qué reglas de extracción son necesarias, cómo evaluar calidad, cómo manejar restatements. Todo ese conocimiento se porta al 4.0, pero no el código tal cual.

#### Qué es el 4.0
Un sistema de inversión completo, construido desde cero con arquitectura de clases Python, que integra bajo un mismo diseño todo lo que en el 3.0 estaba fragmentado entre `engine/`, `scripts/runners/`, y `deterministic/`.

#### Principios fundacionales
1. **Arquitectura de clases desde el día uno.** Cada módulo del sistema es una clase con interfaz tipada. No hay funciones sueltas ni facades monolíticos. El sistema se configura por composición (inyección de dependencias), no por if/else.
2. **Un solo pipeline de extracción financiera.** Se acabó la duplicación entre `engine/` y `deterministic/`. Hay un único sistema de extracción con múltiples fuentes (iXBRL, tablas HTML, PDF, narrativas) orquestadas por prioridad y confianza.
3. **Separación clara entre capas:**
   - **Capa 0 — Sources**: descarga y almacenamiento de filings (fetchers por regulador: SEC, ESEF, EDINET...), transcripts, market data.
   - **Capa 1 — Extracción cuantitativa (zero-LLM)**: iXBRL como fuente primaria, HTML/PDF como fallback. Determinista, reproducible, auditable.
   - **Capa 2 — Extracción cualitativa (LLM-assisted)**: MD&A, risk factors, guidance, cambios entre periodos. Trazabilidad al párrafo del filing.
   - **Capa 3 — LLM fallback de datos cuantitativos**: revisa lo que la Capa 1 no pudo extraer o tiene confianza baja y lo completa.
   - **Capa 4 — Análisis y decisión**: TruthPack, métricas derivadas, IMPLIED, CATALYST, BULL, RED_TEAM, ARBITRO. Consume las capas anteriores.
4. **Cobertura global.** Fetchers pluggables por regulador. Cada mercado nuevo = una clase Fetcher nueva, sin tocar el resto del pipeline.
5. **Testing como ciudadano de primera.** Framework de regresión que corre todos los casos existentes ante cualquier cambio. Fixtures por regulador. Mocks de APIs externas. El `eval --all` actual evoluciona a un CI/CD real.
6. **Configuración sobre código.** Aliases, prioridades de filing, pesos de sección, reglas de selección — todo en archivos de configuración con override por caso/mercado.

#### Qué se porta del 3.0
- Reglas de extracción validadas en `deterministic/` (aliases, scale cascade, selection rules).
- `ixbrl_extractor.py` y `sec_edgar.py` como base de los fetchers/extractors.
- Framework de evaluación (`evaluate.py`, expected.json, política de restatement).
- Casos de prueba (TZOO, GCT, y los que se añadan) con sus expected.json como suite de regresión.
- Conocimiento acumulado en `mejoras/IDEAS.md` y `PHASE2_OPERATIONS_LOG.md`.

#### Qué NO se porta
- La estructura de `engine/` con sus runners y prompt builders acoplados.
- La duplicación de funcionalidad entre módulos.
- El facade monolítico de `pipeline.py`.
- Cualquier código que no tenga tests o trazabilidad.

#### Cuándo arrancarlo
Cuando `deterministic` esté estable en TZOO y GCT (extractor HTML/PDF robusto, selection rules configurables, validador de expected). Ese es el punto donde tenemos suficiente conocimiento validado para diseñar las clases con confianza.
