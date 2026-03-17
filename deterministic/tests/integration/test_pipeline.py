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


class TestManualOverrides(unittest.TestCase):
    """Tests for _apply_manual_overrides — last-resort for corrupted PDFs."""

    def test_override_injected_when_extractor_found_nothing(self):
        """Override is applied when the extractor has no value for the field."""
        result = ExtractionResult(ticker="TST", currency="USD")
        result.periods["FY2019"] = PeriodResult(fecha_fin="2019-12-31", tipo_periodo="anual")
        config = {
            "manual_overrides": {
                "FY2019": {
                    "ingresos": {"value": 5355, "note": "KPI p.1"}
                }
            }
        }
        DeterministicPipeline._apply_manual_overrides(config, result)
        self.assertIn("FY2019", result.periods)
        fr = result.periods["FY2019"].fields["ingresos"]
        self.assertEqual(fr.value, 5355.0)
        self.assertEqual(fr.confidence, "manual")
        self.assertEqual(fr.source_filing, "manual_override")
        self.assertIn("KPI p.1", fr.source_location)
        self.assertEqual(result.audit.fields_extracted, 1)

    def test_extractor_wins_when_value_already_present(self):
        """Extractor value is preserved; override is silently skipped."""
        result = ExtractionResult(ticker="TST", currency="USD")
        result.periods["FY2022"] = PeriodResult(fecha_fin="2022-12-31", tipo_periodo="anual")
        result.periods["FY2022"].fields["ingresos"] = FieldResult(
            value=9000.0, scale="millions", confidence="low"
        )
        config = {
            "manual_overrides": {
                "FY2022": {
                    "ingresos": {"value": 8154},
                    "fcf":      {"value": 703},
                }
            }
        }
        DeterministicPipeline._apply_manual_overrides(config, result)
        # Extracted value must not be overwritten
        self.assertEqual(result.periods["FY2022"].fields["ingresos"].value, 9000.0)
        self.assertEqual(result.periods["FY2022"].fields["ingresos"].confidence, "low")
        # Missing field IS injected
        self.assertEqual(result.periods["FY2022"].fields["fcf"].value, 703.0)
        self.assertEqual(result.periods["FY2022"].fields["fcf"].confidence, "manual")
        # Only fcf was injected
        self.assertEqual(result.audit.fields_extracted, 1)

    def test_period_created_when_extractor_missed_it_entirely(self):
        """Period is created from scratch when extractor produced nothing for it."""
        result = ExtractionResult(ticker="TST", currency="USD")
        config = {
            "manual_overrides": {
                "FY2021": {
                    "ingresos":          {"value": 7115},
                    "fcf":               {"value": 661},
                    "dividends_per_share": {"value": 3.30},
                }
            }
        }
        DeterministicPipeline._apply_manual_overrides(config, result)
        self.assertIn("FY2021", result.periods)
        self.assertEqual(result.periods["FY2021"].fecha_fin, "2021-12-31")
        self.assertEqual(result.periods["FY2021"].tipo_periodo, "anual")
        self.assertEqual(len(result.periods["FY2021"].fields), 3)
        self.assertEqual(result.audit.fields_extracted, 3)

    def test_no_crash_on_empty_or_missing_overrides(self):
        """Absent or empty manual_overrides block is handled gracefully."""
        result = ExtractionResult(ticker="TST", currency="USD")
        DeterministicPipeline._apply_manual_overrides({}, result)
        DeterministicPipeline._apply_manual_overrides({"manual_overrides": {}}, result)
        DeterministicPipeline._apply_manual_overrides(
            {"manual_overrides": {"FY2020": {"ingresos": "bad_spec"}}}, result
        )
        self.assertEqual(len(result.periods), 0)


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
