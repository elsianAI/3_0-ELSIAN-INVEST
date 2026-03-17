#!/usr/bin/env python3
"""Tests for legacy truth_pack import bootstrap."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.state import get_next_step, load_state
from engine.truthpack_import import (
    convert_legacy_truthpack,
    diagnose_legacy_truthpack_payload,
    import_truthpack_case,
    normalize_legacy_truthpack_payload,
)


class TruthPackImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.case_dir = self.tmp_path / "casos" / "TST" / "2026-03-08"
        self.input_path = self.case_dir / "truth_pack.json"
        self.market_output_path = self.case_dir / "_market_data_output.json"
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self.payload = {
            "schema_version": "TruthPack_v1",
            "ticker": "TST",
            "currency": "USD",
            "assembly_date": "2026-03-08",
            "sources": {
                "extraction_result": "extraction_result.json",
                "case_config": "case.json",
            },
            "financial_data": {
                "FY2024": {
                    "fecha_fin": "2024-12-31",
                    "tipo_periodo": "anual",
                    "fields": {
                        "ingresos": {
                            "value": 1200.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:income",
                            "row_label": "Revenue",
                        },
                        "ebit": {
                            "value": 150.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:ebit",
                            "row_label": "Operating income",
                        },
                        "net_income": {
                            "value": 100.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:net-income",
                            "row_label": "Net income",
                        },
                        "cfo": {
                            "value": 180.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:cfo",
                            "row_label": "Net cash from operating activities",
                        },
                        "capex": {
                            "value": -25.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:capex",
                            "row_label": "Capex",
                        },
                        "gross_profit": {
                            "value": 600.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:gross-profit",
                            "row_label": "Gross profit",
                        },
                        "cost_of_revenue": {
                            "value": 600.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:cogs",
                            "row_label": "Cost of revenue",
                        },
                        "total_assets": {
                            "value": 2500.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:assets",
                            "row_label": "Assets",
                        },
                        "total_liabilities": {
                            "value": 900.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:liabilities",
                            "row_label": "Liabilities",
                        },
                        "total_equity": {
                            "value": 1600.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:equity",
                            "row_label": "Equity",
                        },
                        "cash_and_equivalents": {
                            "value": 300.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:cash",
                            "row_label": "Cash",
                        },
                        "shares_outstanding": {
                            "value": 20.0,
                            "scale": "thousands",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:shares",
                            "row_label": "Weighted average shares",
                        },
                        "eps_diluted": {
                            "value": 5.0,
                            "scale": "raw",
                            "source_filing": "SRC_001_10-K_FY2024.clean.md",
                            "source_location": "SRC_001:eps-diluted",
                            "row_label": "Diluted EPS",
                        },
                    },
                },
                "Q1-2025": {
                    "fecha_fin": "2025-03-31",
                    "tipo_periodo": "trimestral",
                    "fields": {
                        "ingresos": {
                            "value": 350.0,
                            "scale": "thousands",
                            "source_filing": "SRC_002_10-Q_Q1-2025.clean.md",
                            "source_location": "SRC_002:income",
                            "row_label": "Revenue",
                        },
                        "ebit": {
                            "value": 42.0,
                            "scale": "thousands",
                            "source_filing": "SRC_002_10-Q_Q1-2025.clean.md",
                            "source_location": "SRC_002:ebit",
                            "row_label": "Operating income",
                        },
                        "net_income": {
                            "value": 30.0,
                            "scale": "thousands",
                            "source_filing": "SRC_002_10-Q_Q1-2025.clean.md",
                            "source_location": "SRC_002:net-income",
                            "row_label": "Net income",
                        },
                        "shares_outstanding": {
                            "value": 21000.0,
                            "scale": "raw",
                            "source_filing": "SRC_002_10-Q_Q1-2025.clean.md",
                            "source_location": "SRC_002:shares",
                            "row_label": "Weighted average shares",
                        },
                    },
                },
                "9M-2025": {
                    "fecha_fin": "2025-09-30",
                    "tipo_periodo": "unknown",
                    "fields": {
                        "cfo": {
                            "value": 260.0,
                            "scale": "thousands",
                            "source_filing": "SRC_003_10-Q_Q3-2025.clean.md",
                            "source_location": "SRC_003:cfo",
                            "row_label": "Net cash from operating activities",
                        }
                    },
                },
            },
            "derived_metrics": {
                "ttm": {
                    "ingresos": 1500.0,
                    "ebit": 180.0,
                    "cfo": 300.0,
                    "capex": -40.0,
                    "metodo": "suma_4_trimestres",
                    "fecha_fin": "2025-12-31",
                    "nota": "Legacy TTM",
                },
                "fcf": 260.0,
                "margins": {
                    "gross_margin_pct": 50.0,
                    "operating_margin_pct": 12.0,
                    "fcf_margin_pct": 17.3,
                },
                "multiples": {
                    "ev_ebit": None,
                    "ev_fcf": None,
                    "fcf_yield_pct": None,
                },
                "periodo_base": "suma_4_trimestres",
            },
            "quality": {
                "validation_status": "PASS",
                "confidence_score": 88.0,
            },
            "metadata": {
                "total_periods": 3,
                "source_hint": "sec",
            },
        }
        self.input_path.write_text(json.dumps(self.payload), encoding="utf-8")
        self.market_output_path.write_text(
            json.dumps(
                {
                    "version_esquema": "SourcesPack_v1",
                    "caso_id": "CASE_20260308_TST",
                    "fecha_corte": "2026-03-08",
                    "empresa": {"ticker": "TST"},
                    "fuentes": [
                        {
                            "source_id": "SRC_MKT_001",
                            "tipo": "MARKET_DATA",
                            "datos": {
                                "precio_cierre": 12.5,
                                "market_cap_millones": 250.0,
                                "shares_outstanding_millones": 20.0,
                            },
                        }
                    ],
                    "faltantes": [],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_convert_legacy_truthpack_maps_core_fields(self) -> None:
        converted = convert_legacy_truthpack(
            self.payload,
            ticker="TST",
            date_str="2026-03-08",
            exchange="NASDAQ",
            country="US",
            source_path=self.input_path,
        )

        self.assertEqual(converted["version_esquema"], "TruthPack_v1")
        self.assertEqual(converted["caso_id"], "CASE_20260308_TST")
        self.assertEqual(converted["empresa"]["bolsa"], "NASDAQ")
        self.assertEqual(converted["historico_anual"][0]["ingresos_usd"], 1_200_000.0)
        self.assertEqual(converted["historico_trimestral"][0]["acciones_diluidas"], 21_000.0)
        self.assertEqual(converted["balance_sheet_ultimo"]["activos_totales_usd"], 2_500_000.0)
        self.assertEqual(converted["data_quality"]["status"], "PASS")
        self.assertEqual(converted["recomendacion_siguiente_paso"]["puede_pasar_a_implied_expectations"], True)

    def test_convert_legacy_truthpack_locks_share_and_per_share_unit_family(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["financial_data"]["FY2024"]["fields"]["shares_outstanding"]["value"] = 41_098_514.0
        payload["financial_data"]["FY2024"]["fields"]["shares_outstanding"]["scale"] = "millions"
        payload["financial_data"]["FY2024"]["fields"]["eps_diluted"]["value"] = 1.15
        payload["financial_data"]["FY2024"]["fields"]["eps_diluted"]["scale"] = "millions"

        converted = convert_legacy_truthpack(
            payload,
            ticker="TST",
            date_str="2026-03-08",
            exchange="NASDAQ",
            country="US",
            source_path=self.input_path,
        )

        fy2024 = next(entry for entry in converted["historico_anual"] if entry["periodo"] == "FY2024")
        self.assertEqual(fy2024["acciones_diluidas"], 41_098_514.0)
        self.assertEqual(fy2024["eps_diluted"], 1.15)
        self.assertLess(converted["data_quality"]["confidence_score"], 89.0)
        self.assertIn("legacy_import_policy", converted["data_quality"])

    def test_import_truthpack_case_bootstraps_state(self) -> None:
        output_path = import_truthpack_case(
            case_dir=self.case_dir,
            ticker="TST",
            date_str="2026-03-08",
            input_path=self.input_path,
            exchange="NASDAQ",
            country="US",
            web_ir="https://example.com/ir",
            overwrite=True,
        )

        self.assertTrue(output_path.exists())
        state = load_state(self.case_dir)
        self.assertEqual(state["pipeline"]["TRUTH_PACK"]["estado"], "DONE")
        self.assertEqual(state["pipeline"]["TRUTH_PACK"]["artefacto"], output_path.name)
        self.assertEqual(get_next_step(self.case_dir), "IMPLIED")
        for sub_step in ("TP_EXTRACTOR_FILING", "TP_EXTRACTOR_MERGER", "TP_CALCULATOR", "TP_VALIDATOR"):
            self.assertEqual(state["sub_steps"][sub_step]["status"], "DONE")

    def test_import_truthpack_case_uses_market_sidecar_when_legacy_market_data_missing(self) -> None:
        output_path = import_truthpack_case(
            case_dir=self.case_dir,
            ticker="TST",
            date_str="2026-03-08",
            input_path=self.input_path,
            exchange="NASDAQ",
            country="US",
            overwrite=True,
        )

        converted = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(converted["mercado"]["precio"]["valor"], 12.5)
        self.assertEqual(converted["mercado"]["market_cap_usd"], 250_000_000.0)
        self.assertEqual(converted["mercado"]["acciones_diluidas"]["valor"], 20_000_000.0)

    def test_diagnose_legacy_truthpack_payload_detects_reparable_issues(self) -> None:
        reparable = json.loads(json.dumps(self.payload))
        reparable["sources"]["extraction_result"] = "extraction_result.json"
        reparable["sources"]["market_data"] = "_market_data_output.json"
        reparable["market_data"] = {
            "company_name": "Test Corp",
            "exchange": "NASDAQ",
            "country": "US",
            "sector": "Technology",
            "industry": "Software",
            "price": 12.5,
            "market_cap": 250.0,
            "shares_outstanding": 20.0,
        }
        reparable["financial_data"]["9M-2025"]["fecha_fin"] = None
        reparable["financial_data"]["9M-2025"]["tipo_periodo"] = "unknown"

        diagnosis = diagnose_legacy_truthpack_payload(reparable)

        self.assertEqual(diagnosis["status"], "reparable")
        self.assertIn("lift_root_metadata:company_name", diagnosis["auto_fixable"])
        self.assertIn("infer_fecha_fin:9M-2025", diagnosis["auto_fixable"])
        self.assertIn("normalize_market_data_units", diagnosis["auto_fixable"])

    def test_normalize_legacy_truthpack_payload_applies_safe_repairs(self) -> None:
        reparable = json.loads(json.dumps(self.payload))
        reparable["sources"]["extraction_result"] = "extraction_result.json"
        reparable["sources"]["market_data"] = "_market_data_output.json"
        reparable["market_data"] = {
            "company_name": "Test Corp",
            "exchange": "NASDAQ",
            "country": "US",
            "sector": "Technology",
            "industry": "Software",
            "price": 12.5,
            "market_cap": 250.0,
            "shares_outstanding": 20.0,
        }
        reparable["financial_data"]["9M-2025"]["fecha_fin"] = None
        reparable["financial_data"]["9M-2025"]["tipo_periodo"] = "unknown"

        normalized, meta = normalize_legacy_truthpack_payload(reparable)

        self.assertEqual(normalized["company_name"], "Test Corp")
        self.assertEqual(normalized["exchange"], "NASDAQ")
        self.assertEqual(normalized["financial_data"]["9M-2025"]["fecha_fin"], "2025-09-30")
        self.assertEqual(normalized["financial_data"]["9M-2025"]["tipo_periodo"], "nine_months")
        self.assertEqual(normalized["sources"]["extraction_result"], "embedded:financial_data")
        self.assertEqual(normalized["sources"]["market_data"], "embedded:market_data")
        self.assertEqual(normalized["market_data"]["market_cap"], 250_000_000.0)
        self.assertEqual(normalized["market_data"]["shares_outstanding"], 20_000_000.0)
        self.assertIn("lift_root_metadata:company_name", meta["applied_fixes"])

    def test_diagnose_legacy_truthpack_payload_blocks_missing_financial_data(self) -> None:
        blocked_payload = {
            "schema_version": "TruthPack_v1",
            "ticker": "BAD",
            "currency": "USD",
            "assembly_date": "2026-03-08",
            "financial_data": {},
        }

        diagnosis = diagnose_legacy_truthpack_payload(blocked_payload)

        self.assertEqual(diagnosis["status"], "blocked")
        self.assertIn("financial_data con al menos un periodo y fields extraíbles", diagnosis["required_upstream_data"])

    def test_import_truthpack_case_auto_normalizes_reparable_payload(self) -> None:
        reparable = json.loads(json.dumps(self.payload))
        reparable["sources"]["extraction_result"] = "extraction_result.json"
        reparable["sources"]["market_data"] = "_market_data_output.json"
        reparable["market_data"] = {
            "company_name": "Test Corp",
            "exchange": "NASDAQ",
            "country": "US",
            "sector": "Technology",
            "industry": "Software",
            "price": 12.5,
            "market_cap": 250.0,
            "shares_outstanding": 20.0,
        }
        reparable["financial_data"]["9M-2025"]["fecha_fin"] = None
        reparable["financial_data"]["9M-2025"]["tipo_periodo"] = "unknown"
        self.input_path.write_text(json.dumps(reparable), encoding="utf-8")

        output_path = import_truthpack_case(
            case_dir=self.case_dir,
            ticker="TST",
            date_str="2026-03-08",
            input_path=self.input_path,
            overwrite=True,
        )

        converted = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(converted["empresa"]["nombre"], "Test Corp")
        self.assertEqual(converted["empresa"]["bolsa"], "NASDAQ")
        nine_month_period = next(entry for entry in converted["historico_trimestral"] if entry["periodo"] == "9M-2025")
        self.assertEqual(nine_month_period["fecha_fin"], "2025-09-30")
        self.assertEqual(nine_month_period["tipo_periodo"], "nine_months")


if __name__ == "__main__":
    unittest.main()
