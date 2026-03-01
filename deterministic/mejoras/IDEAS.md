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

---

### 12. Data Provenance — Trazabilidad completa del origen de cada dato
**PRIORIDAD ALTA para el 4.0 — diseñar desde el inicio, no retrofitear.**

#### El problema
Hoy el pipeline registra `source_filing` (de qué archivo viene el dato), pero no registra la ubicación exacta dentro del filing. Un usuario profesional que ve "revenue = 1,289,897" quiere poder hacer clic y ver exactamente la celda del estado financiero de donde sale ese número. Sin eso, la herramienta no es auditable y pierde la confianza de usuarios financieros serios.

#### Tres niveles de trazabilidad

**Nivel 1 — Filing source (ya implementado):**
`"source_filing": "SRC_001_10-K_FY2024.clean.md"` → identifica el archivo, pero no el punto exacto.

**Nivel 2 — Coordenadas dentro del clean.md:**
Añadir localización precisa: tabla, fila, columna, texto original de la celda.
```json
{
  "value": 1289897,
  "source_filing": "SRC_001_10-K_FY2024.clean.md",
  "provenance": {
    "table_index": 3,
    "table_title": "Consolidated Statements of Operations",
    "row_label": "Net revenues",
    "col_label": "Year Ended December 31, 2024",
    "row": 12,
    "col": 2,
    "raw_text": "1,289,897"
  }
}
```
Esto permite que la interfaz web resalte la celda exacta en el clean.md renderizado.

**Nivel 3 — Vínculo al documento original (SEC/EDGAR):**
Mapear las coordenadas del clean.md de vuelta al HTML o PDF original. Requiere que el converter (HTML → markdown) preserve un mapeo de posiciones durante la conversión. El resultado final sería un deep link tipo:
`https://www.sec.gov/Archives/edgar/data/12345/filing.htm#table3-row12-col2`
O en la web de ELSIAN: el PDF/HTML original con la celda resaltada con CSS/JS.

#### Requisitos de diseño para el 4.0
1. **El converter debe preservar el mapeo.** Durante la conversión HTML → clean.md, guardar un archivo auxiliar (ej: `.source_map.json`) que vincule cada tabla/fila/columna del markdown con su posición en el HTML original.
2. **El extractor debe propagar coordenadas.** Cuando extrae un valor de una tabla, debe anotar las coordenadas, no solo el valor.
3. **El iXBRL extractor ya tiene trazabilidad nativa.** Los tags XBRL incluyen referencia al concepto, periodo, y contexto. Eso es provenance de nivel 2 gratis.
4. **La interfaz web necesita un visor de filings.** Renderizar el HTML original del filing con capacidad de resaltar celdas específicas por coordenadas.

#### Valor comercial
- **Diferenciador competitivo:** Bloomberg y Capital IQ te dan el dato pero no te enseñan de dónde sale. ELSIAN sí.
- **Confianza institucional:** fondos, analistas y auditores necesitan poder verificar cualquier cifra. "Click to source" convierte a ELSIAN en una herramienta auditable.
- **Defensa ante alucinaciones:** en un sistema que usa LLM en capas superiores, poder demostrar que el dato cuantitativo viene directamente del filing es la mejor defensa contra el escepticismo de "la IA se inventa los números".

---

### 13. Visión comercial — La capa de datos con provenance como producto independiente
**REFLEXIÓN ESTRATÉGICA — no es una tarea técnica, es una decisión de negocio.**

#### Insight clave
Lo que se está construyendo en el módulo deterministic + data provenance (idea #12) no es solo un paso previo para el pipeline de análisis. **Es un producto comercial en sí mismo.** Una base de datos financiera global, estructurada, con trazabilidad hasta la celda del filing original, compite directamente con Bloomberg, Capital IQ y FactSet — pero con un diferenciador que ellos no tienen: el "click to source".

#### Por qué ahora
- La confianza es el cuello de botella del mercado, no la inteligencia. Todo el mundo está lanzando chatbots financieros con IA, pero nadie puede demostrar que los datos son correctos.
- La tendencia regulatoria (SEC con iXBRL obligatorio, Europa con ESEF, Japón con EDINET) empuja hacia filings estructurados y machine-readable. ELSIAN surfea esa corriente en vez de luchar contra ella.
- Los incumbentes (Bloomberg ~25.000$/año, FactSet ~12.000$/año) son inaccesibles para la mayoría del mercado: analistas independientes, family offices pequeños, fintech, fondos emergentes, investigadores académicos.

#### Ventaja competitiva: el efecto de red de reglas
Cada ticker que se procesa genera reglas de extracción validadas contra ground truth curado. Esas reglas se acumulan y hacen más fácil y preciso el siguiente ticker. Un competidor que empiece de cero tiene que recorrer el mismo camino. Es un moat de datos propietario que crece con el uso.

#### Cuatro líneas de producto naturales

**Línea 1 — API de datos con provenance.**
Datos financieros estructurados (los 22+ campos canónicos) con trazabilidad completa por ticker. Clientes: quant funds, fintech que necesitan datos limpios para sus modelos, plataformas de inversión. Modelo: suscripción por ticker/mes o por llamada API.

**Línea 2 — Visor de filings inteligente (web).**
Interfaz web donde cualquiera puede ver los estados financieros de una empresa con cada número vinculado al filing original (click to source). Modelo freemium: datos básicos gratis (atrae tráfico, construye marca), provenance completa + histórico = premium. Este producto solo, sin análisis, ya tiene valor.

**Línea 3 — Sistema de análisis completo (Capas 2-4).**
TruthPack, CATALYST, BULL, RED_TEAM, ARBITRO. El producto premium de ELSIAN para inversores que quieren no solo datos sino conclusiones. Se apoya en las Líneas 1-2 como base de datos verificada.

**Línea 4 — Licencia de datos.**
Vender el dataset limpio y estructurado a terceros: otras plataformas fintech, investigación académica, reguladores, auditoras. Los datos con provenance tienen valor para cualquiera que necesite datos financieros verificados.

#### Arquitectura de producto alineada con las capas técnicas
- **Capa 0+1 (Sources + Extracción determinista)** → Líneas 1 y 2. Zero-LLM, auditable, certificable. Vendible a clientes institucionales que desconfían de la IA.
- **Capa 2+3 (Extracción cualitativa + LLM fallback)** → Enriquece Líneas 1-2 con señales cualitativas.
- **Capa 4 (Análisis y decisión)** → Línea 3. Donde entra la inteligencia diferencial de ELSIAN.

#### Implicación para el 4.0
Diseñar el 4.0 sabiendo que las Capas 0+1 deben poder funcionar como producto independiente. Esto significa: API limpia desde el día uno, documentación de cada endpoint, rate limiting, autenticación, y sobre todo — que la capa de datos no dependa de la capa de análisis para tener valor.

---

### 14. Extracción de tablas PDF — Decisiones técnicas y evolución futura

#### Estado actual: pdfplumber (layout=True)
Implementado como reemplazo de pypdf. Usa `extract_text(layout=True)` que preserva columnas alineadas y permite al table parser reconstruir tablas financieras desde PDFs europeos. Funciona bien para tablas con estructura clara.

#### PyMuPDF descartado como motor base
Se evaluó PyMuPDF (pymupdf4llm) como alternativa más rápida, pero tiene un problema de kerning en PDFs con fuentes corporativas europeas que lo hace inviable para tablas financieras:
- Labels rotos: "Operat i ng prof i t" en vez de "Operating profit" — no matchea aliases
- Números rotos: "- 289" en vez de "-289" — rompe parsing numérico
- Columnas pegadas al label en vez de alineadas por espacios

pdfplumber no tiene estos problemas porque usa un approach diferente para reconstruir el layout del texto. **PyMuPDF es más rápido para texto genérico, pero pdfplumber es superior para tablas financieras en PDFs corporativos.**

#### Mejora futura para el 4.0: Table Transformer (TATR)
**Cuando pdfplumber no sea suficiente para tablas complejas.**

Modelo de deep learning de Microsoft (basado en DETR) específicamente entrenado para detectar y estructurar tablas en documentos. En el benchmark comparativo de arXiv (2410.09871), TATR logra F1 de 0.79 para tablas de documentos financieros — muy por encima de cualquier solución basada en reglas (Tabula 0.24, PyMuPDF 0.18, pdfplumber 0.06, Camelot 0.10).

**Cómo se integraría:**
- **Dependencias:** PyTorch + Hugging Face Transformers + modelo pre-entrenado `microsoft/table-transformer-detection` + `microsoft/table-transformer-structure-recognition`
- **Flujo:** PDF página → imagen (renderizada con pdfplumber o Pillow) → TATR detecta bounding boxes de tablas → TATR reconoce estructura (filas, columnas, headers) → extrae texto por celda con coordenadas → genera tabla markdown
- **Bonus para provenance (idea #12):** TATR da bounding boxes exactos de cada celda en coordenadas de página, lo que permite mapear directamente al PDF original para "click to source"

**Estrategia de integración:**
1. **pdfplumber como base** (implementado) — cubre el 80% de los casos
2. **TATR como segundo extractor** — se activa cuando pdfplumber falla o cuando la confianza es baja (pocas columnas detectadas, filas inconsistentes)
3. **Cross-validation** — si ambos extraen la misma tabla, comparar resultados para aumentar confianza
4. Encaja en la arquitectura de clases (idea #10): `PdfPlumberExtractor` y `TableTransformerExtractor` como dos implementaciones de `TableExtractor`, orquestadas por confianza

**Cuándo implementarlo:**
Cuando el volumen de empresas europeas/PDF justifique la inversión. pdfplumber resolverá los primeros 20-30 tickers. Si empezamos a ver fallos sistemáticos en tablas complejas, es el momento de añadir TATR.
