import unittest

from engine.model_defaults import build_global_updates, build_step_override_updates


def _build_raw_config() -> dict:
    return {
        "version": "2.0.0",
        "model_catalog": {
            "gpt-5.4": {},
            "claude-opus-4.6": {},
            "gemini-3.1-pro-preview": {},
        },
        "pipeline_dag": {
            "PIPELINE": [
                {"step": "PREFETCH", "type": "python"},
                {"step": "BULL", "type": "llm"},
                {"step": "TP_EXTRACTOR_FILING", "type": "llm_per_filing"},
            ]
        },
        "step_overrides": {},
    }


class ModelDefaultsTests(unittest.TestCase):
    def test_build_global_updates_accepts_gpt_5_4(self):
        raw = _build_raw_config()

        patched, errors = build_global_updates(
            raw,
            {
                "pipeline_models": [
                    "gpt-5.4",
                    "claude-opus-4.6",
                    "gemini-3.1-pro-preview",
                ],
                "fusion_model": "claude-opus-4.6",
                "default_single_model": "gpt-5.4",
            },
        )

        self.assertEqual(errors, [])
        self.assertEqual(
            patched["pipeline_models"],
            ["gpt-5.4", "claude-opus-4.6", "gemini-3.1-pro-preview"],
        )
        self.assertEqual(patched["fusion_model"], "claude-opus-4.6")
        self.assertEqual(patched["default_single_model"], "gpt-5.4")

    def test_build_step_override_updates_accepts_gpt_5_4_llm_per_filing(self):
        raw = _build_raw_config()

        patched, errors = build_step_override_updates(
            raw,
            step_name="TP_EXTRACTOR_FILING",
            models=["gpt-5.4"],
            fusion_model=None,
            reset=False,
            is_step_multi=lambda _step: False,
        )

        self.assertEqual(errors, [])
        self.assertEqual(
            patched["step_overrides"]["TP_EXTRACTOR_FILING"]["models"],
            ["gpt-5.4"],
        )

    def test_build_step_override_updates_accepts_gpt_5_4_multi_step_fusion(self):
        raw = _build_raw_config()

        patched, errors = build_step_override_updates(
            raw,
            step_name="BULL",
            models=["gpt-5.4", "claude-opus-4.6"],
            fusion_model="claude-opus-4.6",
            reset=False,
            is_step_multi=lambda step_name: step_name == "BULL",
        )

        self.assertEqual(errors, [])
        self.assertEqual(
            patched["step_overrides"]["BULL"]["models"],
            ["gpt-5.4", "claude-opus-4.6"],
        )
        self.assertEqual(
            patched["step_overrides"]["BULL"]["fusion_model"],
            "claude-opus-4.6",
        )