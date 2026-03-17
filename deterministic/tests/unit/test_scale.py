"""Tests for deterministic.src.normalize.scale"""

import unittest

from deterministic.src.normalize.scale import (
    normalize_to_millions,
    infer_scale_cascade,
    resolve_scale_for_field,
    validate_scale_sanity,
)


class TestNormalizeToMillions(unittest.TestCase):
    def test_raw(self):
        val, scale = normalize_to_millions(100, "raw")
        self.assertEqual(val, 100)
        self.assertEqual(scale, "millions")

    def test_thousands(self):
        val, scale = normalize_to_millions(100_000, "thousands")
        self.assertAlmostEqual(val, 100.0)
        self.assertEqual(scale, "millions")

    def test_millions(self):
        val, scale = normalize_to_millions(100, "millions")
        self.assertEqual(val, 100)
        self.assertEqual(scale, "millions")

    def test_billions(self):
        val, scale = normalize_to_millions(1.5, "billions")
        self.assertAlmostEqual(val, 1500.0)
        self.assertEqual(scale, "millions")


class TestInferScaleCascade(unittest.TestCase):
    def test_raw_notes_priority(self):
        scale, conf = infer_scale_cascade("millions", "thousands", "raw", None)
        self.assertEqual(scale, "millions")
        self.assertEqual(conf, "high")

    def test_header_fallback(self):
        scale, conf = infer_scale_cascade("raw", "thousands", "raw", None)
        self.assertEqual(scale, "thousands")
        self.assertEqual(conf, "high")

    def test_preflight_fallback(self):
        scale, conf = infer_scale_cascade("raw", "raw", "millions", None)
        self.assertEqual(scale, "millions")
        self.assertEqual(conf, "medium")

    def test_uncertainty(self):
        scale, conf = infer_scale_cascade("raw", "raw", "raw", None)
        self.assertEqual(scale, "raw")
        self.assertEqual(conf, "low")

    def test_share_fields_are_locked_to_raw(self):
        scale, conf = resolve_scale_for_field(
            "weighted_avg_diluted", "millions", "millions", "millions", None
        )
        self.assertEqual(scale, "raw")
        self.assertEqual(conf, "high")

    def test_per_share_fields_are_locked_to_raw(self):
        scale, conf = resolve_scale_for_field(
            "eps_diluted", "millions", "millions", "millions", None
        )
        self.assertEqual(scale, "raw")
        self.assertEqual(conf, "high")


class TestValidateScaleSanity(unittest.TestCase):
    def test_normal_revenue(self):
        self.assertTrue(validate_scale_sanity(185.2, "ingresos", "millions"))

    def test_tiny_revenue_fails(self):
        self.assertFalse(validate_scale_sanity(0.001, "ingresos", "millions"))

    def test_huge_eps_fails(self):
        self.assertFalse(validate_scale_sanity(50000, "eps_basic", "millions"))

    def test_normal_eps(self):
        self.assertTrue(validate_scale_sanity(4.25, "eps_basic", "raw"))

    def test_raw_always_ok(self):
        self.assertTrue(validate_scale_sanity(0.001, "ingresos", "raw"))


if __name__ == "__main__":
    unittest.main()
