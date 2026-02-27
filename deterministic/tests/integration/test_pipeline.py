"""Integration tests for the deterministic pipeline.

Tests the full extract + evaluate flow using test fixtures.
"""

import json
import tempfile
import unittest
from pathlib import Path

from deterministic.src.pipeline import DeterministicPipeline
from deterministic.src.schemas import ExtractionResult, FieldResult, PeriodResult
from deterministic.src.evaluate import evaluate


class TestPipelineExtractFromFixtures(unittest.TestCase):
    """Test extract using the table fixture as a simulated filing."""

    def setUp(self):
        self.pipeline = DeterministicPipeline()
        self.tmpdir = tempfile.mkdtemp()
        self.case_dir = Path(self.tmpdir) / "TEST"
        self.case_dir.mkdir()
        filings_dir = self.case_dir / "filings"
        filings_dir.mkdir()

        # Write case.json
        case_config = {
            "ticker": "TEST",
            "exchange": "NASDAQ",
            "country": "US",
            "currency": "USD",
            "source_hint": "sec",
        }
        (self.case_dir / "case.json").write_text(
            json.dumps(case_config), encoding="utf-8"
        )

        # Copy fixture as a filing
        fixture_path = (
            Path(__file__).parent.parent
            / "fixtures"
            / "table_10k_sample.md"
        )
        if fixture_path.exists():
            text = fixture_path.read_text(encoding="utf-8")
            (filings_dir / "SRC_001_10-K_FY2024.clean.md").write_text(
                text, encoding="utf-8"
            )

    def test_extract_produces_results(self):
        result = self.pipeline.extract(str(self.case_dir))
        self.assertIsInstance(result, ExtractionResult)
        self.assertEqual(result.ticker, "TEST")
        self.assertEqual(result.currency, "USD")
        # Should have extracted some periods and fields
        self.assertTrue(len(result.periods) > 0, "Should extract at least 1 period")

    def test_extract_finds_revenue(self):
        result = self.pipeline.extract(str(self.case_dir))
        # Check if revenue was found in any period
        found_revenue = False
        for period_key, period in result.periods.items():
            if "ingresos" in period.fields:
                found_revenue = True
                break
        self.assertTrue(found_revenue, "Should extract revenue (ingresos)")

    def test_to_dict_valid(self):
        result = self.pipeline.extract(str(self.case_dir))
        d = result.to_dict()
        self.assertEqual(d["schema_version"], "1.0")
        self.assertEqual(d["ticker"], "TEST")
        self.assertIn("periods", d)
        self.assertIn("audit", d)


class TestEvaluate(unittest.TestCase):
    """Test the evaluate function with a known extraction and expected."""

    def test_perfect_match(self):
        extraction = ExtractionResult(
            ticker="TEST",
            currency="USD",
        )
        extraction.periods["FY2024"] = PeriodResult(
            fecha_fin="2024-12-31",
            tipo_periodo="anual",
            fields={
                "ingresos": FieldResult(value=100.0, scale="millions"),
                "net_income": FieldResult(value=25.0, scale="millions"),
            },
        )

        # Write expected.json
        tmpdir = tempfile.mkdtemp()
        expected_path = Path(tmpdir) / "expected.json"
        expected_data = {
            "version": "1.0",
            "ticker": "TEST",
            "currency": "USD",
            "scale": "millions",
            "periods": {
                "FY2024": {
                    "fecha_fin": "2024-12-31",
                    "tipo_periodo": "anual",
                    "fields": {
                        "ingresos": {"value": 100.0},
                        "net_income": {"value": 25.0},
                    },
                }
            },
        }
        expected_path.write_text(
            json.dumps(expected_data), encoding="utf-8"
        )

        report = evaluate(extraction, str(expected_path))
        self.assertEqual(report.total_expected, 2)
        self.assertEqual(report.matched, 2)
        self.assertEqual(report.score, 100.0)

    def test_partial_match(self):
        extraction = ExtractionResult(ticker="TEST", currency="USD")
        extraction.periods["FY2024"] = PeriodResult(
            fields={
                "ingresos": FieldResult(value=100.0),
            },
        )

        tmpdir = tempfile.mkdtemp()
        expected_path = Path(tmpdir) / "expected.json"
        expected_data = {
            "periods": {
                "FY2024": {
                    "fields": {
                        "ingresos": {"value": 100.0},
                        "net_income": {"value": 25.0},
                    },
                }
            },
        }
        expected_path.write_text(json.dumps(expected_data), encoding="utf-8")

        report = evaluate(extraction, str(expected_path))
        self.assertEqual(report.total_expected, 2)
        self.assertEqual(report.matched, 1)
        self.assertEqual(report.missed, 1)
        self.assertEqual(report.score, 50.0)

    def test_wrong_value(self):
        extraction = ExtractionResult(ticker="TEST", currency="USD")
        extraction.periods["FY2024"] = PeriodResult(
            fields={
                "ingresos": FieldResult(value=200.0),  # Wrong!
            },
        )

        tmpdir = tempfile.mkdtemp()
        expected_path = Path(tmpdir) / "expected.json"
        expected_data = {
            "periods": {
                "FY2024": {
                    "fields": {
                        "ingresos": {"value": 100.0},
                    },
                }
            },
        }
        expected_path.write_text(json.dumps(expected_data), encoding="utf-8")

        report = evaluate(extraction, str(expected_path))
        self.assertEqual(report.wrong, 1)
        self.assertEqual(report.matched, 0)

    def test_tolerance(self):
        """Values within 1% should match."""
        extraction = ExtractionResult(ticker="TEST", currency="USD")
        extraction.periods["FY2024"] = PeriodResult(
            fields={
                "ingresos": FieldResult(value=100.5),  # 0.5% off
            },
        )

        tmpdir = tempfile.mkdtemp()
        expected_path = Path(tmpdir) / "expected.json"
        expected_data = {
            "periods": {
                "FY2024": {
                    "fields": {
                        "ingresos": {"value": 100.0},
                    },
                }
            },
        }
        expected_path.write_text(json.dumps(expected_data), encoding="utf-8")

        report = evaluate(extraction, str(expected_path))
        self.assertEqual(report.matched, 1)


if __name__ == "__main__":
    unittest.main()
