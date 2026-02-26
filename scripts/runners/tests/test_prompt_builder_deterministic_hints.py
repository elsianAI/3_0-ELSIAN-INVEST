import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.prompt_builder import build_filing_prompt


class PromptBuilderDeterministicHintsTests(unittest.TestCase):
    def test_includes_deterministic_hints_and_chunk_override(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            instrucciones = tmp / "instrucciones"
            instrucciones.mkdir(parents=True, exist_ok=True)
            (instrucciones / "instrucciones_tp_extractor_filing_V1.md").write_text(
                "test instructions", encoding="utf-8"
            )

            filing = tmp / "sample.txt"
            filing.write_text("fallback content", encoding="utf-8")
            source_entry = {
                "source_id": "SRC_001",
                "tipo": "ANNUAL_REPORT",
                "form_type": "ANNUAL_REPORT",
                "period": "FY2024",
            }
            deterministic_hints = {
                "entries": [],
                "best_by_field": {
                    "ingresos_usd": {
                        "value": 10280000000,
                        "section": "income_statement",
                        "line": 10,
                        "confidence": "high",
                    }
                },
            }

            prompt, excerpt_meta = build_filing_prompt(
                filing_path=filing,
                source_entry=source_entry,
                ticker="TEP",
                instrucciones_dir=instrucciones,
                deterministic_hints=deterministic_hints,
                content_override="## INCOME STATEMENT\nTotal revenue 10,280",
                chunk_context={"chunk_id": 1, "chunk_label": "income_statement"},
                include_ixbrl=False,
            )

            self.assertIn("DATOS PRE-EXTRAIDOS (CAPA 1 DETERMINISTA)", prompt)
            self.assertIn("ingresos_usd", prompt)
            self.assertEqual(excerpt_meta.get("mode"), "chunk_override")
            self.assertIn("chunk_context", excerpt_meta)
            self.assertIn("deterministic_hints", excerpt_meta)


if __name__ == "__main__":
    unittest.main()

