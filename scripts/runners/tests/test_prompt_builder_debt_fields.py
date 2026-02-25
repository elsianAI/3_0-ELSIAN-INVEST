import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.prompt_builder import build_filing_prompt


class PromptBuilderDebtFieldsTests(unittest.TestCase):
    def test_prompt_includes_debt_components_and_no_lease_rule(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            instrucciones = tmp / "instrucciones"
            instrucciones.mkdir(parents=True, exist_ok=True)
            (instrucciones / "instrucciones_tp_extractor_filing_V1.md").write_text(
                "test instructions", encoding="utf-8"
            )

            filing = tmp / "sample.txt"
            filing.write_text("dummy filing content", encoding="utf-8")
            source_entry = {
                "source_id": "SRC_001",
                "tipo": "ANNUAL_REPORT",
                "form_type": "ANNUAL_REPORT",
                "period": "FY2024",
            }
            prompt, _meta = build_filing_prompt(
                filing_path=filing,
                source_entry=source_entry,
                ticker="TEP",
                instrucciones_dir=instrucciones,
            )

            self.assertIn("deuda_largo_plazo_usd", prompt)
            self.assertIn("deuda_corto_plazo_usd", prompt)
            self.assertIn("Do NOT include lease liabilities in debt fields.", prompt)


if __name__ == "__main__":
    unittest.main()
