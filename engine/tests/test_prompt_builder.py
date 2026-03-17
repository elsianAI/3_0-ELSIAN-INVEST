import json
import tempfile
import unittest
from pathlib import Path

from engine.prompt_builder import build_prompt


class PromptBuilderTests(unittest.TestCase):
    def test_arbitro_compacts_large_input_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            instrucciones_dir = root / "instrucciones"
            schemas_dir = root / "schemas"
            case_dir = root / "caso"
            instrucciones_dir.mkdir(parents=True, exist_ok=True)
            (schemas_dir / "artefactos").mkdir(parents=True, exist_ok=True)
            case_dir.mkdir(parents=True, exist_ok=True)

            (instrucciones_dir / "instrucciones_arbitro_V6.md").write_text(
                "Instrucciones ARBITRO",
                encoding="utf-8",
            )
            (schemas_dir / "artefactos" / "DecisionPacket_v2.json").write_text(
                json.dumps({"version_esquema": "DecisionPacket_v2", "type": "object"}),
                encoding="utf-8",
            )

            large_truthpack = {
                "version_esquema": "TruthPack_v1",
                "ticker": "ACLS",
                "historico_anual": [
                    {"periodo": f"FY{idx}", "texto": "X" * 5000, "valor": idx}
                    for idx in range(40)
                ],
            }
            large_bull = {
                "version_esquema": "AgentReport_v1",
                "resumen_ejecutivo": {"bullets": ["Y" * 4000 for _ in range(8)]},
                "claims": [{"claim_id": f"C{idx}", "texto": "Z" * 3000} for idx in range(20)],
            }

            truthpack_path = case_dir / "TruthPack_v1_ACLS.json"
            bull_path = case_dir / "AgentReport_v1_BULL_ACLS.json"
            truthpack_path.write_text(json.dumps(large_truthpack, ensure_ascii=False), encoding="utf-8")
            bull_path.write_text(json.dumps(large_bull, ensure_ascii=False), encoding="utf-8")

            prompt = build_prompt(
                step_name="ARBITRO",
                ticker="ACLS",
                case_dir=case_dir,
                instrucciones_dir=instrucciones_dir,
                schemas_dir=schemas_dir,
                input_artifacts={
                    "TruthPack_v1": truthpack_path,
                    "AgentReport_v1_BULL": bull_path,
                },
            )

        self.assertIn("TruthPack_v1 [COMPACTADO_PARA_PROMPT]", prompt)
        self.assertIn("AgentReport_v1_BULL [COMPACTADO_PARA_PROMPT]", prompt)
        self.assertIn('"version_esquema": "TruthPack_v1"', prompt)
        self.assertLess(len(prompt), len(json.dumps(large_truthpack)) + len(json.dumps(large_bull)))


if __name__ == "__main__":
    unittest.main()