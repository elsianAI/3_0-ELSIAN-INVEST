import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from engine.backends.base import DispatchResult
from engine.dispatcher import (
    _resolve_tp_filing_model_roles,
    _run_cross_layer_reconciliation,
    dispatch_parallel_filings,
)


class _DummyTransport:
    def __init__(self, name: str):
        self.transport_name = name


class _DummySpec:
    def __init__(self, transport_name: str):
        transport = _DummyTransport(transport_name)
        self.transports = [transport]
        self.primary_transport = transport


class _DummyConfig:
    def __init__(self):
        self.is_v2 = True
        self.default_single_model = "gpt-5.3-codex"
        self.fusion_model = "gpt-5.3-codex"
        self.timeouts = {"tp_extractor_per_filing": 5}
        self.execution = {
            "max_parallel_filings": 1,
            "tp_extractor_chunked_enabled": True,
            "tp_extractor_chunking": {
                "target_tokens_haiku": 12000,
                "target_tokens_flash": 16000,
                "max_chunk_tokens": 18000,
                "overlap_tokens": 1000,
                "max_chunks_per_filing": 8,
                "fusion_model": "gpt-5.3-codex",
                "cross_layer_reconciliation_enabled": True,
                "cross_layer_arbitration_enabled": False,
                "cross_layer_max_arbitrations": 0,
            },
        }
        self.raw = {
            "step_overrides": {
                "TP_EXTRACTOR_FILING": {
                    "models": ["gpt-5.3-codex"],
                    "chunk_models": ["claude-haiku-4.5"],
                    "chunk_fusion_model": "gpt-5.3-codex",
                    "reconciliation_model": "claude-opus-4.6",
                }
            }
        }
        self._specs = {
            "gpt-5.3-codex": _DummySpec("codex"),
            "claude-haiku-4.5": _DummySpec("claude"),
            "claude-opus-4.6": _DummySpec("claude"),
        }

    def get_model_spec(self, model_name: str):
        return self._specs.get(model_name)


class DispatcherPhase2Tests(unittest.TestCase):
    def test_model_roles_keep_primary_and_separate_chunk(self):
        cfg = _DummyConfig()
        roles = _resolve_tp_filing_model_roles(
            cfg,
            step_cfg={"models": ["gpt-5.3-codex"]},
            chunking_enabled=True,
        )
        self.assertEqual(roles["primary_model"], "gpt-5.3-codex")
        self.assertEqual(roles["chunk_model"], "claude-haiku-4.5")
        self.assertEqual(roles["chunk_fusion_model"], "gpt-5.3-codex")
        self.assertEqual(roles["reconciliation_model"], "claude-opus-4.6")

    def test_cross_layer_reconciliation_can_fill_from_deterministic(self):
        llm_output = {
            "version_esquema": "TruthPack_v1",
            "historico_anual": [{"periodo": "FY2024", "ingresos_usd": 1200.0}],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {},
        }
        deterministic_hints = {
            "best_by_field": {
                "activos_totales_usd": {
                    "field": "activos_totales_usd",
                    "value": 1230000000.0,
                    "section": "balance_sheet",
                    "line": 41,
                    "unit_applied": 1000000.0,
                    "confidence": "high",
                }
            }
        }
        out, meta, field_prov = _run_cross_layer_reconciliation(
            config=SimpleNamespace(),
            case_dir=Path("."),
            timeout=5,
            llm_output=llm_output,
            deterministic_hints=deterministic_hints,
            source_content="Total assets 1,230",
            currency="EUR",
            reconciliation_model="claude-opus-4.6",
            arbitration_enabled=False,
            max_arbitrations=0,
        )
        self.assertEqual(out["balance_sheet_ultimo"]["activos_totales_usd"], 1230000000.0)
        self.assertTrue(meta["enabled"])
        self.assertEqual(meta["confidence_by_field"]["activos_totales_usd"]["status"], "deterministic_fill")
        self.assertEqual(field_prov[0]["selected_source"], "deterministic")

    def test_cross_layer_reconciliation_marks_material_conflict(self):
        llm_output = {
            "version_esquema": "TruthPack_v1",
            "historico_anual": [],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {"activos_totales_usd": 1_500_000_000.0},
        }
        deterministic_hints = {
            "best_by_field": {
                "activos_totales_usd": {
                    "field": "activos_totales_usd",
                    "value": 900_000_000.0,
                    "section": "balance_sheet",
                    "line": 99,
                    "unit_applied": 1.0,
                    "confidence": "high",
                }
            }
        }
        out, meta, field_prov = _run_cross_layer_reconciliation(
            config=SimpleNamespace(),
            case_dir=Path("."),
            timeout=5,
            llm_output=llm_output,
            deterministic_hints=deterministic_hints,
            source_content="",
            currency="USD",
            reconciliation_model="claude-opus-4.6",
            arbitration_enabled=False,
            max_arbitrations=0,
        )
        self.assertEqual(out["balance_sheet_ultimo"]["activos_totales_usd"], 1_500_000_000.0)
        self.assertEqual(meta["conflicts"], 1)
        self.assertEqual(meta["entries"][0]["status"], "material_conflict")
        self.assertTrue(field_prov[0]["material_conflict"])

    def test_cross_layer_arbiter_selects_deterministic_value(self):
        llm_value = 1_500_000_000.0
        det_value = 900_000_000.0
        llm_output = {
            "version_esquema": "TruthPack_v1",
            "historico_anual": [],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {"activos_totales_usd": llm_value},
        }
        deterministic_hints = {
            "best_by_field": {
                "activos_totales_usd": {
                    "field": "activos_totales_usd",
                    "value": det_value,
                    "section": "balance_sheet",
                    "line": 99,
                    "unit_applied": 1.0,
                    "confidence": "high",
                }
            }
        }

        arbiter_result = DispatchResult(
            True,
            {
                "selected_source": "deterministic",
                "selected_value": det_value,
                "confidence": "high",
                "reason": "table match",
            },
            "",
            "claude-opus-4.6",
            "claude",
            0.1,
            model_profile="claude-opus-4.6",
            transport="claude",
        )

        with patch("engine.dispatcher._dispatch_model_with_retry", return_value=arbiter_result) as mocked_dispatch:
            out, meta, field_prov = _run_cross_layer_reconciliation(
                config=SimpleNamespace(),
                case_dir=Path("."),
                timeout=5,
                llm_output=llm_output,
                deterministic_hints=deterministic_hints,
                source_content="Total assets 900",
                currency="USD",
                reconciliation_model="claude-opus-4.6",
                arbitration_enabled=True,
                max_arbitrations=1,
            )

        mocked_dispatch.assert_called_once()
        self.assertEqual(out["balance_sheet_ultimo"]["activos_totales_usd"], det_value)
        self.assertEqual(meta["entries"][0]["status"], "resolved_by_arbiter")
        self.assertEqual(meta["arbitrations"], 1)
        self.assertEqual(meta["entries"][0]["selected_method"], "arbiter")
        self.assertEqual(field_prov[0]["selected_method"], "arbiter")
        self.assertEqual(field_prov[0]["selected_source"], "deterministic")

    def test_cross_layer_arbiter_selects_llm_value(self):
        llm_value = 1_500_000_000.0
        det_value = 900_000_000.0
        llm_output = {
            "version_esquema": "TruthPack_v1",
            "historico_anual": [],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {"activos_totales_usd": llm_value},
        }
        deterministic_hints = {
            "best_by_field": {
                "activos_totales_usd": {
                    "field": "activos_totales_usd",
                    "value": det_value,
                    "section": "balance_sheet",
                    "line": 99,
                    "unit_applied": 1.0,
                    "confidence": "high",
                }
            }
        }

        arbiter_result = DispatchResult(
            True,
            {
                "selected_source": "llm",
                "selected_value": llm_value,
                "confidence": "medium",
                "reason": "period alignment",
            },
            "",
            "claude-opus-4.6",
            "claude",
            0.1,
            model_profile="claude-opus-4.6",
            transport="claude",
        )

        with patch("engine.dispatcher._dispatch_model_with_retry", return_value=arbiter_result) as mocked_dispatch:
            out, meta, field_prov = _run_cross_layer_reconciliation(
                config=SimpleNamespace(),
                case_dir=Path("."),
                timeout=5,
                llm_output=llm_output,
                deterministic_hints=deterministic_hints,
                source_content="Total assets 1500",
                currency="USD",
                reconciliation_model="claude-opus-4.6",
                arbitration_enabled=True,
                max_arbitrations=1,
            )

        mocked_dispatch.assert_called_once()
        self.assertEqual(out["balance_sheet_ultimo"]["activos_totales_usd"], llm_value)
        self.assertEqual(meta["entries"][0]["status"], "resolved_by_arbiter")
        self.assertEqual(meta["arbitrations"], 1)
        self.assertEqual(meta["entries"][0]["selected_method"], "arbiter")
        self.assertEqual(field_prov[0]["selected_method"], "arbiter")
        self.assertEqual(field_prov[0]["selected_source"], "llm")

    def test_cross_layer_arbitration_budget_guard(self):
        llm_value = 1_500_000_000.0
        det_value = 900_000_000.0
        llm_output = {
            "version_esquema": "TruthPack_v1",
            "historico_anual": [],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {"activos_totales_usd": llm_value},
        }
        deterministic_hints = {
            "best_by_field": {
                "activos_totales_usd": {
                    "field": "activos_totales_usd",
                    "value": det_value,
                    "section": "balance_sheet",
                    "line": 99,
                    "unit_applied": 1.0,
                    "confidence": "high",
                }
            }
        }

        with patch("engine.dispatcher._dispatch_model_with_retry") as mocked_dispatch:
            out, meta, field_prov = _run_cross_layer_reconciliation(
                config=SimpleNamespace(),
                case_dir=Path("."),
                timeout=5,
                llm_output=llm_output,
                deterministic_hints=deterministic_hints,
                source_content="Total assets 1500",
                currency="USD",
                reconciliation_model="claude-opus-4.6",
                arbitration_enabled=True,
                max_arbitrations=0,
            )

        mocked_dispatch.assert_not_called()
        self.assertEqual(out["balance_sheet_ultimo"]["activos_totales_usd"], llm_value)
        self.assertEqual(meta["entries"][0]["status"], "material_conflict")
        self.assertEqual(meta["entries"][0]["selected_method"], "llm_conflict_default")
        self.assertEqual(field_prov[0]["selected_method"], "llm_conflict_default")
        self.assertEqual(meta["arbitrations"], 0)

    def test_chunk_fallback_uses_primary_model_not_chunk_model(self):
        cfg = _DummyConfig()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_dir = root / "a" / "b" / "c"
            case_dir.mkdir(parents=True, exist_ok=True)
            filing_path = root / "sample_filing.md"
            filing_path.write_text("## INCOME STATEMENT\nRevenue 100\n", encoding="utf-8")
            filings = [{"local_path": "sample_filing.md", "ticker": "TST", "source_id": "SRC_1"}]

            models_used: list[str] = []

            def _fake_dispatch(*args, **kwargs):
                model_profile = args[1]
                models_used.append(model_profile)
                return DispatchResult(
                    True,
                    {
                        "version_esquema": "TruthPack_v1",
                        "historico_anual": [{"periodo": "FY2024", "ingresos_usd": 100.0}],
                        "historico_trimestral": [],
                        "balance_sheet_ultimo": {},
                    },
                    "",
                    model_profile,
                    "codex",
                    0.1,
                    model_profile=model_profile,
                    transport="codex",
                )

            with patch("engine.dispatcher.get_step_config", return_value={"models": ["gpt-5.3-codex"], "backends": ["codex"]}), \
                patch("engine.dispatcher._instantiate_transport", return_value=SimpleNamespace(check_available=lambda: True)), \
                patch("scripts.runners.deterministic_extractor.split_semantic_chunks", return_value=[]), \
                patch("scripts.runners.deterministic_extractor.extract_deterministic_facts", return_value={"entries": [], "best_by_field": {}, "stats": {}}), \
                patch("engine.dispatcher.build_filing_prompt", return_value=("prompt", {"mode": "full"})), \
                patch("engine.dispatcher._append_prompt_excerpt_meta"), \
                patch("engine.dispatcher._dispatch_model_with_retry", side_effect=_fake_dispatch):
                results = dispatch_parallel_filings(
                    config=cfg,
                    filings=filings,
                    instrucciones_dir=Path("."),
                    case_dir=case_dir,
                )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)
        self.assertEqual(models_used, ["gpt-5.3-codex"])


if __name__ == "__main__":
    unittest.main()
