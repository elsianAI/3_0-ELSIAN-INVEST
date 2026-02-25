import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.prompt_builder import build_filing_prompt
from scripts.runners.clean_md_pipeline import generate_clean_md
from scripts.runners.sources_compiler_runner import compile_sources


class CleanMdPipelineTests(unittest.TestCase):
    def test_generate_clean_md_html_table_ok(self):
        with tempfile.TemporaryDirectory() as td:
            html_path = Path(td) / "sample.htm"
            html_path.write_text(
                """
                <html><body>
                <h2>Consolidated Balance Sheets</h2>
                <table>
                  <tr><th>Item</th><th>2024</th><th>2023</th></tr>
                  <tr><td>Total assets</td><td>1000</td><td>900</td></tr>
                  <tr><td>Total liabilities</td><td>600</td><td>520</td></tr>
                  <tr><td>Total equity</td><td>400</td><td>380</td></tr>
                  <tr><td>Cash and cash equivalents</td><td>120</td><td>100</td></tr>
                  <tr><td>Total debt</td><td>250</td><td>240</td></tr>
                </table>
                </body></html>
                """,
                encoding="utf-8",
            )
            clean_text, meta = generate_clean_md(
                source_path=html_path,
                txt_content="",
                filing_type="10-K",
                source_id="SRC_TEST_001",
            )
            self.assertIsNotNone(clean_text)
            self.assertEqual(meta.get("mode"), "html_table")
            self.assertEqual(meta.get("status"), "GENERATED")
            self.assertIn("_Extractor mode: html_table_", clean_text)

    def test_generate_clean_md_pdf_text_ok(self):
        text = (
            ("Revenue profit income cash flow assets liabilities equity ebitda capex operating activities investing activities financing activities\n" * 120)
            + "Consolidated Balance Sheets\n"
            + ("Total assets 1000 Total liabilities 600 Total equity 400 cash 120 debt 250\n" * 220)
            + "Statement of Cash Flows\n"
            + ("Net cash provided by operating activities 150 investing activities -40 financing activities -60\n" * 220)
            + "Income Statement\n"
            + ("Revenue 2000 net income 210 ebit 300 ebitda 420\n" * 220)
        )
        clean_text, meta = generate_clean_md(
            source_path=Path("sample.pdf"),
            txt_content=text,
            filing_type="ANNUAL_REPORT",
            source_id="SRC_TEST_002",
        )
        self.assertIsNotNone(clean_text)
        self.assertEqual(meta.get("mode"), "pdf_text")
        self.assertEqual(meta.get("status"), "GENERATED")
        self.assertIn("## BALANCE SHEET", clean_text)
        self.assertIn("_Extractor mode: pdf_text_", clean_text)

    def test_generate_clean_md_pdf_text_low_signal(self):
        text = ("lorem ipsum dolor sit amet 12345\n" * 1000).strip()
        clean_text, meta = generate_clean_md(
            source_path=Path("sample.pdf"),
            txt_content=text,
            filing_type="ANNUAL_REPORT",
            source_id="SRC_TEST_003",
        )
        self.assertIsNone(clean_text)
        self.assertEqual(meta.get("status"), "REJECTED_QUALITY")
        self.assertEqual(meta.get("reason"), "LOW_SIGNAL")

    def test_generate_clean_md_pdf_text_low_text(self):
        text = (
            "Revenue 100 assets 200 liabilities 80 cash flow 10 equity 120 "
            "profit 20 income 25 ebit 30 capex 5"
        )
        clean_text, meta = generate_clean_md(
            source_path=Path("sample.pdf"),
            txt_content=text,
            filing_type="ANNUAL_REPORT",
            source_id="SRC_TEST_004",
        )
        self.assertIsNone(clean_text)
        self.assertEqual(meta.get("status"), "REJECTED_QUALITY")
        self.assertEqual(meta.get("reason"), "LOW_TEXT")

    def test_prompt_builder_prefers_pdf_text_clean_md(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            txt_path = work / "SRC_001_ANNUAL_REPORT_2024-12-31.txt"
            txt_path.write_text("RAW-TXT-SHOULD-NOT-BE-USED", encoding="utf-8")
            clean_path = work / "SRC_001_ANNUAL_REPORT_2024-12-31.clean.md"
            clean_path.write_text(
                "# FINANCIAL STATEMENTS — SRC_001\n"
                "_Extracted from: SRC_001.pdf_\n"
                "_Extractor mode: pdf_text_\n\n"
                "## INCOME STATEMENT\n\n"
                + ("Revenue 1000 net income 120 ebit 180\n" * 180)
                + "\n## BALANCE SHEET\n\n"
                + ("Total assets 2000 total liabilities 1100 total equity 900\n" * 180)
                + "\n## CASH FLOW\n\n"
                + ("Operating activities 300 investing activities -100 financing activities -80\n" * 180),
                encoding="utf-8",
            )

            prompt, meta = build_filing_prompt(
                filing_path=txt_path,
                source_entry={"tipo": "ANNUAL_REPORT", "source_id": "SRC_001"},
                ticker="TST",
                instrucciones_dir=work,
            )
            self.assertEqual(meta.get("mode"), "clean_md")
            self.assertTrue(str(meta.get("input_path", "")).endswith(".clean.md"))
            self.assertIn("FINANCIAL STATEMENTS", prompt)
            self.assertNotIn("RAW-TXT-SHOULD-NOT-BE-USED", prompt)

    def test_sources_compiler_regen_prefers_primary_over_txt(self):
        base_tmp = ROOT / "tmp"
        base_tmp.mkdir(parents=True, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix="test_sources_compiler_v4_", dir=base_tmp)
        try:
            case_dir = Path(temp_dir) / "TST" / "2026-02-24_TEST"
            raw_dir = case_dir.parent / "_raw_filings"
            case_dir.mkdir(parents=True, exist_ok=True)
            raw_dir.mkdir(parents=True, exist_ok=True)

            txt_file = raw_dir / "SRC_001_ANNUAL_REPORT_2024-12-31.txt"
            txt_file.write_text("placeholder weak text", encoding="utf-8")
            html_file = raw_dir / "SRC_001_ANNUAL_REPORT_2024-12-31.htm"
            html_file.write_text(
                """
                <html><body>
                <h2>Consolidated Balance Sheets</h2>
                <table>
                  <tr><th>Item</th><th>2024</th><th>2023</th></tr>
                  <tr><td>Total assets</td><td>1200</td><td>1100</td></tr>
                  <tr><td>Total liabilities</td><td>700</td><td>650</td></tr>
                  <tr><td>Total equity</td><td>500</td><td>450</td></tr>
                  <tr><td>Cash and cash equivalents</td><td>160</td><td>130</td></tr>
                  <tr><td>Total debt</td><td>320</td><td>300</td></tr>
                </table>
                </body></html>
                """,
                encoding="utf-8",
            )

            sec_payload = {
                "empresa": {"ticker": "TST", "nombre": "TestCo", "bolsa": "EPA", "pais": "FR"},
                "fuentes": [
                    {
                        "source_id": "SRC_SEC_001",
                        "tipo": "ANNUAL_REPORT",
                        "titulo": "Annual Report 2024",
                        "url": "https://example.com/annual-report.pdf",
                        "local_path": str(txt_file.relative_to(ROOT)),
                        "fecha_publicacion": "2024-12-31",
                    }
                ],
                "faltantes": [],
            }
            (case_dir / "_sec_fetcher_output.json").write_text(
                json.dumps(sec_payload, ensure_ascii=False),
                encoding="utf-8",
            )
            (case_dir / "_market_data_output.json").write_text(
                json.dumps({"empresa": {"ticker": "TST"}, "fuentes": [], "faltantes": []}),
                encoding="utf-8",
            )
            (case_dir / "_transcript_finder_output.json").write_text(
                json.dumps({"empresa": {"ticker": "TST"}, "fuentes": [], "faltantes": []}),
                encoding="utf-8",
            )

            out_path = compile_sources("TST", case_dir)
            compiled = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(len(compiled.get("fuentes", [])), 1)
            local_path = compiled["fuentes"][0].get("local_path", "")
            self.assertTrue(local_path.endswith(".clean.md"))
            clean_abs = ROOT / local_path
            self.assertTrue(clean_abs.exists())
            content = clean_abs.read_text(encoding="utf-8")
            self.assertIn("_Extractor mode: html_table_", content)
            self.assertIn("|", content)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sources_compiler_promotes_urd_presentation_to_annual(self):
        base_tmp = ROOT / "tmp"
        base_tmp.mkdir(parents=True, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix="test_sources_compiler_promote_", dir=base_tmp)
        try:
            case_dir = Path(temp_dir) / "TST" / "2026-02-24_TEST"
            raw_dir = case_dir.parent / "_raw_filings"
            case_dir.mkdir(parents=True, exist_ok=True)
            raw_dir.mkdir(parents=True, exist_ok=True)

            txt_file = raw_dir / "SRC_PR_001_PRESENTATION_2024.txt"
            txt_file.write_text(
                "Universal registration document annual report integrated report revenue assets liabilities equity",
                encoding="utf-8",
            )
            pdf_file = raw_dir / "SRC_PR_001_PRESENTATION_2024.pdf"
            pdf_file.write_bytes(b"%PDF-1.4\n%fake\n")

            sec_payload = {
                "empresa": {"ticker": "TST", "nombre": "TestCo", "bolsa": "EPA", "pais": "FR"},
                "fuentes": [],
                "faltantes": [],
            }
            tr_payload = {
                "empresa": {"ticker": "TST"},
                "fuentes": [
                    {
                        "source_id": "SRC_PR_001",
                        "tipo": "INVESTOR_PRESENTATION",
                        "titulo": "tp-2024-urd",
                        "url": "https://example.com/media/tp-2024-urd.pdf",
                        "local_path": str(txt_file.relative_to(ROOT)),
                        "fecha_publicacion": "2024-12-31",
                        "extractor": "pypdf",
                        "extraction_status": "OK",
                        "text_chars": 9000,
                    }
                ],
                "faltantes": [],
            }
            (case_dir / "_sec_fetcher_output.json").write_text(
                json.dumps(sec_payload, ensure_ascii=False),
                encoding="utf-8",
            )
            (case_dir / "_market_data_output.json").write_text(
                json.dumps({"empresa": {"ticker": "TST"}, "fuentes": [], "faltantes": []}),
                encoding="utf-8",
            )
            (case_dir / "_transcript_finder_output.json").write_text(
                json.dumps(tr_payload, ensure_ascii=False),
                encoding="utf-8",
            )

            out_path = compile_sources("TST", case_dir)
            compiled = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(len(compiled.get("fuentes", [])), 1)
            src = compiled["fuentes"][0]
            self.assertEqual(src.get("tipo"), "ANNUAL_REPORT")
            limits = (compiled.get("log") or {}).get("limitaciones") or []
            self.assertTrue(any("promotion_reason" in str(x) for x in limits))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
