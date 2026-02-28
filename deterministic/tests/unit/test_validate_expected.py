"""Tests for validate_expected module."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from deterministic.src.validate_expected import validate_expected


class TestValidateExpected(unittest.TestCase):
    """Test expected.json validation rules."""

    def _write_expected(self, data: dict) -> str:
        """Write data to a temp expected.json and return path."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.addCleanup(os.unlink, path)
        return path

    def test_valid_expected_no_restatement(self):
        """A valid expected.json with no restatements should pass."""
        data = {
            "version": "1.0",
            "ticker": "TEST",
            "periods": {
                "FY2024": {
                    "fecha_fin": "2024-12-31",
                    "tipo_periodo": "anual",
                    "fields": {
                        "ingresos": {
                            "value": 1000,
                            "source_filing": "SRC_001_10-K_FY2024.clean.md"
                        },
                        "net_income": {
                            "value": 200,
                            "source_filing": "SRC_001_10-K_FY2024.clean.md"
                        }
                    }
                }
            }
        }
        errors = validate_expected(self._write_expected(data))
        self.assertEqual(errors, [])

    def test_valid_expected_with_restatement(self):
        """A valid restatement with all required fields should pass."""
        data = {
            "version": "1.0",
            "ticker": "TEST",
            "periods": {
                "FY2019": {
                    "fecha_fin": "2019-12-31",
                    "tipo_periodo": "anual",
                    "fields": {
                        "ingresos": {
                            "value": 104925,
                            "source_filing": "SRC_005_10-K_FY2020.clean.md",
                            "restatement": {
                                "applied": True,
                                "trigger": "reclassified",
                                "evidence_filing": "SRC_005_10-K_FY2020.txt",
                                "evidence_text": "Prior periods reclassified.",
                                "original_source_filing": "SRC_006_10-K_FY2019.clean.md",
                                "original_value": 111412
                            }
                        }
                    }
                }
            }
        }
        errors = validate_expected(self._write_expected(data))
        self.assertEqual(errors, [])

    def test_missing_source_filing(self):
        """A field without source_filing should fail."""
        data = {
            "version": "1.0",
            "ticker": "TEST",
            "periods": {
                "FY2024": {
                    "fecha_fin": "2024-12-31",
                    "tipo_periodo": "anual",
                    "fields": {
                        "ingresos": {
                            "value": 1000
                        }
                    }
                }
            }
        }
        errors = validate_expected(self._write_expected(data))
        self.assertEqual(len(errors), 1)
        self.assertIn("missing 'source_filing'", errors[0])

    def test_restatement_incomplete(self):
        """A restatement missing required sub-fields should fail."""
        data = {
            "version": "1.0",
            "ticker": "TEST",
            "periods": {
                "FY2019": {
                    "fecha_fin": "2019-12-31",
                    "tipo_periodo": "anual",
                    "fields": {
                        "ingresos": {
                            "value": 104925,
                            "source_filing": "SRC_005_10-K_FY2020.clean.md",
                            "restatement": {
                                "applied": True,
                                "trigger": "reclassified"
                            }
                        }
                    }
                }
            }
        }
        errors = validate_expected(self._write_expected(data))
        # Should flag missing evidence_filing, evidence_text, original_source_filing, original_value
        self.assertEqual(len(errors), 4)
        self.assertTrue(any("evidence_filing" in e for e in errors))
        self.assertTrue(any("evidence_text" in e for e in errors))
        self.assertTrue(any("original_source_filing" in e for e in errors))
        self.assertTrue(any("original_value" in e for e in errors))

    def test_restatement_original_source_same_as_source(self):
        """original_source_filing == source_filing should fail."""
        data = {
            "version": "1.0",
            "ticker": "TEST",
            "periods": {
                "FY2019": {
                    "fecha_fin": "2019-12-31",
                    "tipo_periodo": "anual",
                    "fields": {
                        "ingresos": {
                            "value": 104925,
                            "source_filing": "SRC_005_10-K_FY2020.clean.md",
                            "restatement": {
                                "applied": True,
                                "trigger": "reclassified",
                                "evidence_filing": "SRC_005_10-K_FY2020.txt",
                                "evidence_text": "Prior periods reclassified.",
                                "original_source_filing": "SRC_005_10-K_FY2020.clean.md",
                                "original_value": 111412
                            }
                        }
                    }
                }
            }
        }
        errors = validate_expected(self._write_expected(data))
        self.assertEqual(len(errors), 1)
        self.assertIn("should differ", errors[0])

    def test_file_not_found(self):
        """Non-existent path should return error."""
        errors = validate_expected("/nonexistent/path/expected.json")
        self.assertEqual(len(errors), 1)
        self.assertIn("File not found", errors[0])

    def test_invalid_json(self):
        """Invalid JSON should return error."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as f:
            f.write("{not valid json")
        self.addCleanup(os.unlink, path)
        errors = validate_expected(path)
        self.assertEqual(len(errors), 1)
        self.assertIn("Invalid JSON", errors[0])


if __name__ == "__main__":
    unittest.main()
