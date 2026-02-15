"""Construye prompts completos inyectando instrucciones + schemas + artefactos."""
from __future__ import annotations
from pathlib import Path

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
    "CATALYST_DETECTION":  ["payloads/CatalystPayload_v1.json"],
    "CATALYST_SCORING":    ["artefactos/AgentReport_v1.json", "payloads/CatalystPayload_v1.json"],
    "FORENSIC_DETECTION":  ["payloads/ForensicPayload_v1.json"],
    "FORENSIC_SCORING":    ["artefactos/AgentReport_v1.json", "payloads/ForensicPayload_v1.json"],
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
                if len(content) > 200_000:
                    content = content[:200_000] + "\n\n... [TRUNCATED]"
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
    """
    parts = []

    # Instructions
    instr_path = instrucciones_dir / INSTRUCTION_MAP["TP_EXTRACTOR_FILING"]
    if instr_path.exists():
        parts.append(f"# INSTRUCCIONES\n\n{instr_path.read_text()}")

    # Filing content
    if filing_path.exists():
        content = filing_path.read_text(errors="replace")
        if len(content) > 300_000:
            content = content[:300_000] + "\n\n... [TRUNCATED]"
        parts.append(f"# FILING CONTENT\n\n```\n{content}\n```")

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


def build_fusion_prompt(
    outputs: dict[str, dict],
    step_name: str,
    instrucciones_dir: Path,
) -> str:
    """
    Prompt para fusión multi-modelo.
    """
    parts = []

    # Instructions
    instr_path = instrucciones_dir / INSTRUCTION_MAP["FUSION"]
    if instr_path.exists():
        parts.append(f"# INSTRUCCIONES DE FUSIÓN\n\n{instr_path.read_text()}")

    # Outputs to fuse
    import json
    for backend_name, output in outputs.items():
        output_str = json.dumps(output, indent=2, ensure_ascii=False)
        if len(output_str) > 100_000:
            output_str = output_str[:100_000] + "\n... [TRUNCATED]"
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
