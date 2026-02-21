"""Construye prompts completos inyectando instrucciones + schemas + artefactos."""
from __future__ import annotations
import json
import re
from pathlib import Path

# Default truncation limits (overridable via engine_config.json → truncation_limits)
_DEFAULT_LIMITS = {
    "input_artifact_chars": 200_000,
    "filing_clean_md_chars": 220_000,
    "filing_raw_chars": 300_000,
    "fusion_output_chars": 100_000,
}

# Module-level cache; populated by set_truncation_limits()
_limits: dict[str, int] = dict(_DEFAULT_LIMITS)


def set_truncation_limits(cfg: dict | None) -> None:
    """Called once at engine startup to inject truncation_limits from config."""
    if cfg:
        for key in _DEFAULT_LIMITS:
            if key in cfg:
                _limits[key] = int(cfg[key])

# Mapeo step → fichero de instrucciones
INSTRUCTION_MAP = {
    "SOURCES_COMPILER":    "instrucciones_sources_compiler_V2.md",
    "TP_EXTRACTOR":        "instrucciones_tp_extractor_V1.md",
    "TP_EXTRACTOR_FILING": "instrucciones_tp_extractor_filing_V1.md",
    "TP_CALCULATOR":       "instrucciones_tp_calculator_V1.md",
    "TP_VALIDATOR":        "instrucciones_tp_validator_V1.md",
    "IMPLIED":             "instrucciones_implied_V4.md",
    "CATALYST_DETECTION":  "instrucciones_catalyst_detection_V1.md",
    "CATALYST_SCORING":    "instrucciones_catalyst_scoring_V1.md",
    "FORENSIC_DETECTION":  "instrucciones_forensic_detection_V1.md",
    "FORENSIC_SCORING":    "instrucciones_forensic_scoring_V1.md",
    "BULL":                "instrucciones_bull_V4.md",
    "RED_TEAM":            "instrucciones_red_team_V4.md",
    "ARBITRO":             "instrucciones_arbitro_V6.md",
    "MONITOR":             "instrucciones_monitor_V2.md",
    "SCANNER":             "instrucciones_scanner_V1.md",
    "FUSION":              "instrucciones_fusion_V1.md",
}

# Mapeo step → schema(s) relevantes para inyectar en el prompt
STEP_SCHEMAS = {
    "SOURCES_COMPILER":    ["artefactos/SourcesPack_v1.json"],
    "TP_EXTRACTOR":        ["artefactos/TruthPack_v1.json"],
    "TP_EXTRACTOR_FILING": ["artefactos/TruthPack_v1.json"],
    "IMPLIED":             ["artefactos/ImpliedExpectations_v1.json"],
    "CATALYST_DETECTION":  ["artefactos/CatalystDetection_v1.json"],
    "CATALYST_SCORING":    ["artefactos/AgentReport_v1.json", "artefactos/CatalystDetection_v1.json", "payloads/CatalystPayload_v1.json"],
    "FORENSIC_DETECTION":  ["artefactos/ForensicDetection_v1.json"],
    "FORENSIC_SCORING":    ["artefactos/AgentReport_v1.json", "artefactos/ForensicDetection_v1.json", "payloads/ForensicPayload_v1.json"],
    "BULL":                ["artefactos/AgentReport_v1.json", "payloads/BullPayload_v1.json"],
    "RED_TEAM":            ["artefactos/AgentReport_v1.json", "payloads/RedTeamPayload_v1.json"],
    "ARBITRO":             ["artefactos/DecisionPacket_v2.json"],
    "MONITOR":             ["monitoring/MonitoringUpdate_v1.json"],
    "SCANNER":             ["scanner/ScannerReport_v1.json"],
}


def build_prompt(
    step_name: str,
    ticker: str,
    case_dir: Path,
    instrucciones_dir: Path,
    schemas_dir: Path,
    input_artifacts: dict[str, Path] | None = None,
    extra_context: str = "",
) -> str:
    """
    1. Lee instrucciones del step
    2. Lee schemas relevantes
    3. Lee artefactos de input (JSON files)
    4. Ensambla prompt: instrucciones + schema + datos
    5. Retorna string completo listo para dispatch
    """
    parts = []

    # 1. Instructions
    instruction_file = INSTRUCTION_MAP.get(step_name)
    if instruction_file:
        instr_path = instrucciones_dir / instruction_file
        if instr_path.exists():
            parts.append(f"# INSTRUCCIONES\n\n{instr_path.read_text()}")
        else:
            parts.append(f"# INSTRUCCIONES\n\n[WARNING: {instr_path} not found]")

    # 2. Schemas
    schema_files = STEP_SCHEMAS.get(step_name, [])
    if schema_files:
        schema_parts = []
        for sf in schema_files:
            sp = schemas_dir / sf
            if sp.exists():
                schema_parts.append(f"### {sf}\n```json\n{sp.read_text()}\n```")
        if schema_parts:
            parts.append(f"# SCHEMAS DE OUTPUT\n\n" + "\n\n".join(schema_parts))

    # 3. Input artifacts
    if input_artifacts:
        artifact_parts = []
        for name, path in input_artifacts.items():
            if path.exists():
                content = path.read_text()
                # Truncate very large artifacts to avoid exceeding context
                limit = _limits["input_artifact_chars"]
                if len(content) > limit:
                    content = content[:limit] + f"\n\n... [TRUNCATED at {limit // 1000}k]"
                artifact_parts.append(f"### {name}\n```json\n{content}\n```")
        if artifact_parts:
            parts.append(f"# DATOS DE INPUT\n\n" + "\n\n".join(artifact_parts))

    # 4. Context
    parts.append(f"# CONTEXTO\n\nTicker: {ticker}\nCase directory: {case_dir}\n")
    if extra_context:
        parts.append(extra_context)

    # 5. Final instruction
    parts.append(
        "# INSTRUCCIÓN FINAL\n\n"
        "Ejecuta las tareas descritas arriba. "
        "Responde ÚNICAMENTE con el JSON del artefacto resultante. "
        "No incluyas explicaciones fuera del JSON."
    )

    return "\n\n---\n\n".join(parts)


def build_filing_prompt(
    filing_path: Path,
    source_entry: dict,
    ticker: str,
    instrucciones_dir: Path,
) -> str:
    """
    Prompt para TP_EXTRACTOR por filing individual.

    Strategy:
      1. If .ixbrl.json exists alongside the filing, inject pre-extracted
         authoritative data at the top of the prompt.
      2. For .clean.md files (pre-filtered financial tables), no truncation
         needed — they are already within budget (hard cap 220k).
      3. For .txt/.htm, truncate at 300k chars as safety net.
    """
    parts = []

    # Instructions
    instr_path = instrucciones_dir / INSTRUCTION_MAP["TP_EXTRACTOR_FILING"]
    if instr_path.exists():
        parts.append(f"# INSTRUCCIONES\n\n{instr_path.read_text()}")

    # Try to inject iXBRL pre-extracted data
    ixbrl_path = filing_path.with_suffix(".ixbrl.json")
    # Also try pattern: base.clean.md → base.ixbrl.json
    if not ixbrl_path.exists():
        ixbrl_path = Path(str(filing_path).replace(".clean.md", ".ixbrl.json")
                          .replace(".txt", ".ixbrl.json")
                          .replace(".htm", ".ixbrl.json"))
    # Also look for .ixbrl.json sibling with same stem base
    if not ixbrl_path.exists():
        stem = filing_path.stem
        if stem.endswith(".clean"):
            stem = stem[:-6]
        candidates = list(filing_path.parent.glob(f"{stem}*.ixbrl.json"))
        if candidates:
            ixbrl_path = candidates[0]

    if ixbrl_path.exists():
        try:
            ixbrl_data = json.loads(ixbrl_path.read_text())
            consolidated = ixbrl_data.get("consolidated", {})
            if consolidated:
                ixbrl_section = "# DATOS PRE-EXTRAÍDOS (fuente: iXBRL — AUTORITATIVOS)\n\n"
                ixbrl_section += ("Estos datos fueron extraídos determinísticamente de los tags "
                                  "iXBRL del filing. Son autoritativos: si encuentras datos en "
                                  "el texto que contradigan estos valores, MANTÉN los valores "
                                  "iXBRL y anota la discrepancia.\n\n```json\n")
                ixbrl_section += json.dumps(consolidated, indent=2, ensure_ascii=False)
                ixbrl_section += "\n```\n"
                parts.append(ixbrl_section)
        except Exception:
            pass  # Non-critical — proceed without iXBRL data

    # Filing content — prefer .clean.md over .htm/.txt for financial filings,
    # but only if the .clean.md has actual useful content (semantic quality gate).
    def _clean_md_is_useful(text: str) -> bool:
        """Check if .clean.md has real financial data, not just 'Section not found' stubs."""
        # Criterion 1: must not have ALL 4 sections missing
        if text.count("_Section not found in filing._") >= 4:
            return False
        # Criterion 2: at least 5 table rows with numeric data
        numeric_rows = re.findall(r"^\|.*\d[\d,\.]*.*\|$", text, re.MULTILINE)
        if len(numeric_rows) < 5:
            return False
        # Criterion 3: at least one valid financial section (heading NOT followed by "not found")
        for section in ("INCOME STATEMENT", "BALANCE SHEET", "CASH FLOW"):
            idx = text.find(f"## {section}")
            if idx >= 0:
                after = text[idx:idx + 200]
                if "_Section not found" not in after:
                    return True
        return False

    # ── PDF safety: prefer .txt companion over raw PDF binary ──
    # PDF binaries contain null bytes that crash subprocess.run() when passed
    # as CLI arguments. Prefer the .txt companion if it has real content.
    if filing_path.suffix.lower() == ".pdf":
        txt_candidate = filing_path.with_suffix(".txt")
        if txt_candidate.exists():
            _txt_peek = txt_candidate.read_text(errors="replace")
            if len(_txt_peek) > 200 and not _txt_peek.startswith("[PDF original"):
                filing_path = txt_candidate

    content_path = filing_path
    if not filing_path.name.endswith(".clean.md"):
        clean_candidate = filing_path.parent / (filing_path.stem + ".clean.md")
        if clean_candidate.exists():
            _clean_content = clean_candidate.read_text(errors="replace")
            if _clean_md_is_useful(_clean_content):
                content_path = clean_candidate

    if content_path.exists():
        content = content_path.read_text(errors="replace")
        content = content.replace("\x00", "")  # sanitize null bytes (safety net)
        is_clean_md = content_path.name.endswith(".clean.md")
        if is_clean_md:
            limit = _limits["filing_clean_md_chars"]
            if len(content) > limit:
                content = content[:limit] + f"\n\n... [TRUNCATED at {limit // 1000}k safety cap]"
        else:
            limit = _limits["filing_raw_chars"]
            if len(content) > limit:
                content = content[:limit] + f"\n\n... [TRUNCATED at {limit // 1000}k]"
        parts.append(f"# FILING CONTENT\n\n```\n{content}\n```")

    # Canonical field map — tells the LLM exactly what field names to output
    parts.append(
        "# CANONICAL FIELD MAP\n\n"
        "Use EXACTLY these field names in your JSON output. The downstream normalizer "
        "depends on these exact names. Do NOT invent alternative names.\n\n"
        "## Income Statement (historico_anual / historico_trimestral)\n"
        "- `ingresos_usd` — Total revenue / net revenue\n"
        "- `cogs_usd` — Cost of goods sold / cost of revenues\n"
        "- `gross_profit_usd` — Gross profit\n"
        "- `ebit_usd` — Operating income / income from operations\n"
        "- `net_income_usd` — Net income attributable to company\n"
        "- `rd_usd` — Research & development expense\n"
        "- `sga_usd` — Selling, general & administrative expense\n"
        "- `ga_usd` — General & administrative expense\n"
        "- `interest_expense_usd` — Interest expense\n"
        "- `depreciation_usd` — Depreciation & amortization\n"
        "- `income_tax_usd` — Income tax expense\n\n"
        "## Cash Flow Statement (historico_anual / historico_trimestral)\n"
        "- `cfo_usd` — Net cash from operating activities\n"
        "- `cfi_usd` — Net cash from investing activities (usually negative)\n"
        "- `cff_usd` — Net cash from financing activities\n"
        "- `capex_usd` — Capital expenditures (report as NEGATIVE number)\n"
        "- `delta_cash_usd` — Net increase/decrease in cash and cash equivalents\n"
        "- `fx_effect_cash_usd` — Effect of exchange rates on cash (common in IFRS/non-US)\n"
        "- `otros_ajustes_caja_usd` — Other reconciling adjustments affecting cash movement\n\n"
        "Cash flow reconciliation: `delta_cash_usd = cfo_usd + cfi_usd + cff_usd "
        "+ fx_effect_cash_usd + otros_ajustes_caja_usd`. "
        "If a field is not found in the filing, set it to `null` (do NOT assume 0).\n\n"
        "## Balance Sheet (balance_sheet_ultimo)\n"
        "- `activos_totales_usd` — Total assets\n"
        "- `pasivos_totales_usd` — Total liabilities\n"
        "- `patrimonio_usd` — Total stockholders' equity\n"
        "- `deuda_total_usd` — Total debt (short-term + long-term)\n"
        "- `caja_usd` — Cash and cash equivalents\n"
        "- `cuentas_por_cobrar_usd` — Accounts receivable\n"
        "- `inventarios_usd` — Inventories\n"
        "- `cuentas_por_pagar_usd` — Accounts payable\n\n"
        "IMPORTANT: For each period entry, include `periodo` (format: FY2024 or Q1-2024) "
        "and `fecha_fin` (format: YYYY-MM-DD). Set values to `null` if not found in the filing.\n"
    )

    # Filing metadata
    filing_type = source_entry.get("form_type", source_entry.get("tipo", "UNKNOWN"))
    filing_period = source_entry.get("period", source_entry.get("periodo", "UNKNOWN"))
    parts.append(
        f"# METADATA\n\n"
        f"Ticker: {ticker}\n"
        f"Filing type: {filing_type}\n"
        f"Filing period: {filing_period}\n"
        f"Source ID: {source_entry.get('source_id', 'N/A')}\n"
    )

    parts.append(
        "# INSTRUCCIÓN FINAL\n\n"
        "Extrae los datos crudos de ESTE filing. "
        "Responde ÚNICAMENTE con el JSON parcial TruthPack."
    )

    return "\n\n---\n\n".join(parts)


def _normalize_backend_output(output: dict) -> dict:
    """Extract artifact payload from backend envelope if needed.

    Defensive layer: even after backend fixes, ensures fusion always
    receives clean artifact payloads, not CLI envelopes.
    """
    if not isinstance(output, dict):
        return output

    # Reject error envelopes entirely — these should never reach fusion
    if output.get("is_error") is True:
        return output  # Return as-is; caller should filter errors before fusion

    # Claude Code envelope: {"type": ..., "result": "```json\n{...}\n```", "modelUsage": ...}
    if "result" in output and ("modelUsage" in output or "type" in output):
        result = output["result"]
        if isinstance(result, str):
            # Try direct JSON parse
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
            # Try markdown extraction
            md_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", result, re.DOTALL)
            if md_match:
                try:
                    parsed = json.loads(md_match.group(1))
                    if isinstance(parsed, dict):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass
        elif isinstance(result, dict):
            return result

    # Gemini CLI envelope: {"session_id": ..., "response": "```json\n{...}\n```", "stats": ...}
    if "response" in output and ("session_id" in output or "stats" in output):
        resp = output["response"]
        if isinstance(resp, str):
            try:
                parsed = json.loads(resp)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
            md_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", resp, re.DOTALL)
            if md_match:
                try:
                    parsed = json.loads(md_match.group(1))
                    if isinstance(parsed, dict):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass

    return output


def build_fusion_prompt(
    outputs: dict[str, dict],
    step_name: str,
    instrucciones_dir: Path,
    fusion_instruction_filename: str | None = None,
) -> str:
    """
    Prompt para fusión multi-modelo.
    """
    parts = []

    # Instructions
    instr_file = fusion_instruction_filename or INSTRUCTION_MAP["FUSION"]
    instr_path = instrucciones_dir / instr_file
    if instr_path.exists():
        parts.append(f"# INSTRUCCIONES DE FUSIÓN\n\n{instr_path.read_text()}")

    # Outputs to fuse — normalize to strip any backend envelopes
    for backend_name, output in outputs.items():
        clean_output = _normalize_backend_output(output)
        output_str = json.dumps(clean_output, indent=2, ensure_ascii=False)
        limit = _limits["fusion_output_chars"]
        if len(output_str) > limit:
            output_str = output_str[:limit] + f"\n... [TRUNCATED at {limit // 1000}k]"
        parts.append(f"# OUTPUT DE {backend_name.upper()}\n\n```json\n{output_str}\n```")

    parts.append(
        f"# CONTEXTO\n\nStep fusionado: {step_name}\n"
        f"Modelos: {', '.join(outputs.keys())}\n"
    )

    parts.append(
        "# INSTRUCCIÓN FINAL\n\n"
        "Fusiona los outputs anteriores en un artefacto unificado. "
        "Responde ÚNICAMENTE con el JSON fusionado."
    )

    return "\n\n---\n\n".join(parts)
