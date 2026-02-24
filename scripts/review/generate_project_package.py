#!/usr/bin/env python3
"""Genera el paquete de proyecto ChatGPT para meta-review.

Crea el directorio _review_project/ con todos los ficheros necesarios para
configurar el proyecto "ELSIAN Meta-Review" en ChatGPT.

Usage:
    python3 scripts/review/generate_project_package.py [--workspace PATH]

Implements §3.4 of PLAN_META_REVIEW_GPT52PRO.md (v1.2).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_str(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generate_package(workspace: Path) -> Path:
    """Generate the _review_project/ directory."""
    schemas_dir = workspace / "_schemas"
    output_dir = workspace / "_review_project"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Copy schemas ─────────────────────────────────
    schema_copies = {
        "MetaReview_v1_SCHEMA.json": schemas_dir / "review" / "MetaReview_v1.json",
        "DecisionPacket_v2_SCHEMA.json": schemas_dir / "artefactos" / "DecisionPacket_v2.json",
        "AgentReport_v1_SCHEMA.json": schemas_dir / "artefactos" / "AgentReport_v1.json",
    }
    for dest_name, src_path in schema_copies.items():
        dest = output_dir / dest_name
        if src_path.exists():
            shutil.copy2(src_path, dest)
            print(f"  ✓ {dest_name} (from {src_path.relative_to(workspace)})")
        else:
            print(f"  ⚠ {dest_name} — source not found: {src_path}")

    # ── 2. Generate INSTRUCCIONES_PROYECTO.md ────────────
    instrucciones = _generate_instrucciones()
    (output_dir / "INSTRUCCIONES_PROYECTO.md").write_text(instrucciones, encoding="utf-8")
    print(f"  ✓ INSTRUCCIONES_PROYECTO.md")

    # ── 3. Generate METODOLOGIA_ELSIAN.md ────────────────
    metodologia = _generate_metodologia()
    (output_dir / "METODOLOGIA_ELSIAN.md").write_text(metodologia, encoding="utf-8")
    print(f"  ✓ METODOLOGIA_ELSIAN.md")

    # ── 4. Generate CRITERIOS_REVIEW.md ──────────────────
    criterios = _generate_criterios()
    (output_dir / "CRITERIOS_REVIEW.md").write_text(criterios, encoding="utf-8")
    print(f"  ✓ CRITERIOS_REVIEW.md")

    # ── 5. Generate REGLAS_COMUNES_EXTRACTO.md ───────────
    reglas = _generate_reglas_extracto(workspace)
    (output_dir / "REGLAS_COMUNES_EXTRACTO.md").write_text(reglas, encoding="utf-8")
    print(f"  ✓ REGLAS_COMUNES_EXTRACTO.md")

    # ── 6. Detect changes BEFORE writing new manifest ────
    _check_for_changes(workspace, output_dir, schema_copies)

    # ── 7. Generate _manifest.json ───────────────────────
    manifest = _generate_manifest(workspace, output_dir, schema_copies)
    (output_dir / "_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  ✓ _manifest.json")

    return output_dir


def _generate_instrucciones() -> str:
    """Generate project instructions for ChatGPT."""
    return """# Instrucciones del Proyecto — ELSIAN Meta-Review

## SECCIÓN 1: IDENTIDAD Y ROL

Eres el Meta-Revisor del comité de inversión ELSIAN-INVEST. Tu rol es auditar las decisiones del ARBITRO automatizado del pipeline de análisis de inversión.

Reglas fundamentales:
- NO sustituyes al ARBITRO — lo supervisas
- Tu valor está en el razonamiento profundo, la detección de puntos ciegos y la evaluación de coherencia lógica
- Eres constructivo pero directo: señala problemas sin adular
- Si la decisión del ARBITRO es correcta, dilo brevemente y enfócate en mejoras

## SECCIÓN 2: CONTEXTO DEL PIPELINE

El pipeline ELSIAN-INVEST 3.0 analiza oportunidades de inversión en renta variable mediante un sistema multi-agente:

1. **SOURCES**: Recopilación de fuentes (SEC filings, transcripts, market data)
2. **TRUTH_PACK**: Extracción y validación de datos financieros factuales
3. **IMPLIED**: Cálculo de expectativas implícitas del mercado
4. **CATALYST**: Detección y scoring de catalizadores (ejecutado por 3 modelos: Claude, Codex, Gemini)
5. **FORENSIC**: Análisis forense financiero y de supervivencia (3 modelos)
6. **BULL**: Construcción del caso alcista (3 modelos)
7. **RED_TEAM**: Crítica destructiva del caso (3 modelos)
8. **ARBITRO**: Decisión final con sizing probabilístico (fusión multi-modelo)

Cada paso analítico (4-7) se ejecuta en paralelo por 3 modelos. Los resultados se fusionan en un artifact consolidado. El ARBITRO recibe SOLO los artifacts fusionados y produce un **DecisionPacket_v2** con:
- 5 gates de evaluación (data_quality, survivability, mispricing, catalyst, non_speculative)
- Assumption ledger (supuestos críticos con probabilidades y tests de falsación)
- Grafo de evidencias
- 3 escenarios (BASE, BULL, BEAR) con probabilidades y retornos
- Sizing Kelly ajustado por confianza
- Kill criteria
- Plan de monitoreo

## SECCIÓN 3: CRITERIOS DE REVIEW

Consulta el fichero adjunto `CRITERIOS_REVIEW.md` para los criterios detallados de evaluación.

## SECCIÓN 4: FORMATO DE RESPUESTA OBLIGATORIO

Tu respuesta debe contener:

1. **Análisis narrativo libre** — Sin límite de extensión. Profundidad máxima. Estructura como consideres más claro.

2. **Al final de tu respuesta**: Un bloque JSON delimitado por \\`\\`\\`json ... \\`\\`\\` que sigue el schema `MetaReview_v1` (adjunto en ficheros del proyecto).

El JSON debe incluir TODOS los campos requeridos del schema. Si no puedes evaluar algo, usa el valor `"NO_EVALUABLE"` donde aplique.

## SECCIÓN 5: REGLAS ABSOLUTAS

- Todo en español
- No inventes datos — si no tienes información, di "no evaluable"
- Cita secciones específicas del DecisionPacket cuando critiques (ej: "en el gate mispricing_gate, la justificación...")
- Sé directo y constructivo
- Si la decisión del ARBITRO es correcta, dilo brevemente y enfócate en mejoras menores
- Los supuestos con criticidad "CRITICO" merecen análisis individual detallado
- Las probabilidades extremas (>0.8 o <0.2) requieren justificación extra
"""


def _generate_metodologia() -> str:
    """Generate methodology summary for the project."""
    return """# Metodología ELSIAN-INVEST 3.0

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
"""


def _generate_criterios() -> str:
    """Generate review criteria for the project."""
    return """# Criterios de Meta-Review

## 1. Coherencia lógica
- ¿Las conclusiones del resumen ejecutivo se sostienen con la evidencia del assumption_ledger?
- ¿Hay saltos lógicos entre claims y decisión?
- ¿Los scores parciales (SMCQRV) reflejan correctamente lo que dicen los agentes?
- ¿La narrativa del ARBITRO es consistente con los datos numéricos?

## 2. Rigor de gates
- ¿Cada gate tiene justificación suficiente y específica?
- ¿Un CONDITIONAL se está usando como "PASS blando" sin evidencia concreta?
- ¿Hay gates que deberían ser FAIL pero se marcaron como PASS?
- ¿Los gates reflejan correctamente los hallazgos de FORENSIC y CATALYST?

## 3. Supuestos críticos
- ¿Cada supuesto CRITICO tiene al menos una evidencia con source_id verificable?
- ¿Los tests de falsación son realmente observables, medibles y con umbral definido?
- ¿Las probabilidades asignadas son coherentes con la cantidad y calidad de evidencia?
- ¿Hay dependencias circulares entre supuestos?
- ¿Se han considerado supuestos implícitos no documentados?

## 4. Escenarios
- ¿Las probabilidades de BASE + BULL + BEAR suman ~1.0?
- ¿El escenario BASE es realmente el más probable, o es un BULL disfrazado?
- ¿El BEAR contempla un escenario suficientemente adverso (no solo "menos crecimiento")?
- ¿Los retornos estimados son realistas para los horizontes temporales dados?
- ¿Los drivers de cada escenario son distintos y no redundantes?

## 5. Sizing y Kelly
- ¿Los inputs del Kelly (probabilidad de éxito p, ratio beneficio/pérdida b) son coherentes con los escenarios?
- ¿El ajuste por confianza es apropiado dado el nivel de incertidumbre?
- ¿El sizing final es prudente dado el nivel de conocimiento de la empresa?
- ¿Un sizing > 5% está justificado por evidencia extraordinariamente fuerte?

## 6. Puntos ciegos
- ¿Hay riesgos macro (tipos de interés, recesión, geopolítica) no considerados?
- ¿Se ha evaluado el riesgo de liquidez del activo?
- ¿Se han considerado riesgos regulatorios específicos del sector?
- ¿Hay competidores emergentes o disrupciones tecnológicas no mencionados?
- ¿Se ha considerado el riesgo de concentración de clientes/proveedores?

## 7. Kill criteria
- ¿Son específicos (no genéricos como "si el negocio empeora")?
- ¿Tienen umbrales numéricos donde es posible (ej: "margen operativo < 5%")?
- ¿La acción asociada (EXIT, REDUCE_50, etc.) es proporcional al riesgo?
- ¿Cubren los riesgos más graves contemplados en el BEAR scenario?
- ¿Son realmente monitorizables con datos públicos disponibles?

## 8. Coherencia probabilística ↔ categórica
- ¿La decisión categórica (INVERTIR/WATCHLIST/DESCARTAR) es coherente con las probabilidades?
- ¿Un INVERTIR con probabilidad_exito < 0.5 tiene justificación excepcional?
- ¿Un DESCARTAR con probabilidad_exito > 0.6 está bien fundamentado?
- ¿La tabla A12 del ARBITRO (si presente) es internamente consistente?

## 9. Desacuerdos entre agentes
- ¿El ARBITRO documentó los desacuerdos principales entre agentes?
- ¿La resolución de cada desacuerdo es razonada y no arbitraria?
- ¿Hay señales de "sesgo de consenso" (ignorar la voz discordante)?
"""


def _generate_reglas_extracto(workspace: Path) -> str:
    """Generate extract of REGLAS_COMUNES relevant to review."""
    reglas_path = workspace / "_operativa" / "REGLAS_COMUNES.md"
    if reglas_path.exists():
        full_text = reglas_path.read_text(encoding="utf-8")
        # Extract the most relevant sections
        # For now, return a curated subset
        return f"""# Extracto de Reglas Comunes (para contexto del Meta-Review)

> Este fichero contiene las reglas más relevantes para el proceso de review.
> Fuente: _operativa/REGLAS_COMUNES.md

## Convenciones de artefactos

- Formato ASISTIDO: artifacts generados con asistencia de plataformas manuales (ChatGPT)
  llevan `_meta.motor: "ASISTIDO"` y `_meta.plataforma: "chatgpt"`
- Los artifacts canónicos NO llevan prefijo `_` (ej: MetaReview_v1_TICKER_DATE.json)
- Los ficheros intermedios/temporales llevan prefijo `_` (ej: _review_prompt_gpt52pro_TS.md)

## Decisiones y gates

- 5 gates: data_quality, survivability, mispricing, catalyst, non_speculative
- Un gate CONDITIONAL requiere justificación explícita de por qué no bloquea
- Si algún gate es FAIL, la decisión debe ser DESCARTAR (salvo justificación excepcional)

## Probabilidades y sizing

- Probabilidades siempre en rango [0, 1]
- Escenarios: BASE + BULL + BEAR deben sumar ~1.0 (tolerancia ±0.05)
- Kelly: f = p - (1-p)/b, donde p = prob éxito, b = ratio ganancia/pérdida
- Sizing final = Kelly crudo × factor_confianza × cap_máximo(10%)

## Quality voting

- Sistema de votación determinista que evalúa calidad formal de cada paso
- No evalúa verdad fundamental — solo completitud, estructura y coherencia formal
- Scores de fusión indican acuerdo entre modelos
"""
    return """# Extracto de Reglas Comunes

> REGLAS_COMUNES.md no encontrado. Consultar la documentación del proyecto.
"""


def _generate_manifest(workspace: Path, output_dir: Path, schema_copies: dict) -> dict:
    """Generate _manifest.json with version tracking."""
    now = datetime.now(timezone.utc).isoformat()

    # Hash output files
    output_hashes = {}
    for f in sorted(output_dir.iterdir()):
        if f.name == "_manifest.json":
            continue
        output_hashes[f.name] = f"sha256:{_sha256_file(f)}"

    # Hash source schemas
    source_hashes = {}
    for dest_name, src_path in schema_copies.items():
        if src_path.exists():
            rel = str(src_path.relative_to(workspace))
            source_hashes[rel] = f"sha256:{_sha256_file(src_path)}"

    return {
        "version_paquete": "1.0",
        "generado": now,
        "hashes": output_hashes,
        "schemas_source_hashes": source_hashes,
    }


def _check_for_changes(workspace: Path, output_dir: Path, schema_copies: dict) -> None:
    """Compare current source schemas against the OLD manifest to detect changes.

    Must be called BEFORE writing the new _manifest.json so it can compare
    the previous state with the current source files.
    """
    manifest_path = output_dir / "_manifest.json"
    if not manifest_path.exists():
        return

    try:
        with open(manifest_path) as f:
            old_manifest = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    old_source_hashes = old_manifest.get("schemas_source_hashes", {})
    if not old_source_hashes:
        return

    changes = []
    for rel_path, old_hash in old_source_hashes.items():
        src = workspace / rel_path
        if src.exists():
            current = f"sha256:{_sha256_file(src)}"
            if current != old_hash:
                changes.append(rel_path)

    if changes:
        print(f"\n⚠ Los siguientes schemas fuente han cambiado desde la última generación:")
        for c in changes:
            print(f"  - {c}")
        print(f"  Actualiza los ficheros adjuntos en el proyecto ChatGPT.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Genera paquete de proyecto ChatGPT para meta-review."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Path to workspace root (auto-detected if not specified)",
    )
    args = parser.parse_args()

    if args.workspace:
        workspace = args.workspace
    else:
        # Auto-detect from script location
        workspace = Path(__file__).resolve().parent.parent.parent
        if not (workspace / "_schemas").exists():
            workspace = Path.cwd()

    print(f"Generando paquete de proyecto ChatGPT...")
    print(f"Workspace: {workspace}")
    print()

    output_dir = generate_package(workspace)

    print(f"\n✓ Paquete generado en: {output_dir.relative_to(workspace)}/")
    print(f"\nSiguientes pasos:")
    print(f"  1. Crear proyecto \"ELSIAN Meta-Review\" en ChatGPT (si no existe)")
    print(f"  2. Seleccionar modelo: GPT-5.2 Pro")
    print(f"  3. Pegar contenido de INSTRUCCIONES_PROYECTO.md como instrucciones del proyecto")
    print(f"  4. Adjuntar los demás ficheros al proyecto:")
    for f in sorted(output_dir.iterdir()):
        if f.name not in ("INSTRUCCIONES_PROYECTO.md", "_manifest.json"):
            print(f"     - {f.name}")


if __name__ == "__main__":
    main()
