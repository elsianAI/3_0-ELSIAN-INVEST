import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.router import _select_filings


class _Cfg:
    def __init__(self, raw):
        self.raw = raw


class RouterFilingSelectionTests(unittest.TestCase):
    def test_select_filings_prefers_generated_clean_md_within_type_limit(self):
        filings = [
            {
                "source_id": "SRC_A",
                "tipo": "ANNUAL_REPORT",
                "fecha_publicacion": "2025-12-31",
                "fecha_publicacion_estimated": False,
                "selection_score": 1.0,
                "local_path": "casos/TST/_raw_filings/SRC_A_ANNUAL_REPORT_2025.txt",
                "clean_md_status": "REJECTED_QUALITY",
                "extraction_status": "OK",
            },
            {
                "source_id": "SRC_B",
                "tipo": "ANNUAL_REPORT",
                "fecha_publicacion": "2024-12-31",
                "fecha_publicacion_estimated": False,
                "selection_score": 1.0,
                "local_path": "casos/TST/_raw_filings/SRC_B_ANNUAL_REPORT_2024.txt",
                "clean_md_status": "REJECTED_QUALITY",
                "extraction_status": "OK",
            },
            {
                "source_id": "SRC_C",
                "tipo": "ANNUAL_REPORT",
                "fecha_publicacion": "2023-12-31",
                "fecha_publicacion_estimated": False,
                "selection_score": 1.0,
                "local_path": "casos/TST/_raw_filings/SRC_C_ANNUAL_REPORT_2023.txt",
                "clean_md_status": "REJECTED_QUALITY",
                "extraction_status": "OK",
            },
            {
                "source_id": "SRC_D",
                "tipo": "ANNUAL_REPORT",
                "fecha_publicacion": "2022-12-31",
                "fecha_publicacion_estimated": False,
                "selection_score": 1.0,
                "local_path": "casos/TST/_raw_filings/SRC_D_ANNUAL_REPORT_2022.txt",
                "clean_md_status": "REJECTED_QUALITY",
                "extraction_status": "OK",
            },
            {
                "source_id": "SRC_E",
                "tipo": "ANNUAL_REPORT",
                "fecha_publicacion": "2021-12-31",
                "fecha_publicacion_estimated": False,
                "selection_score": 0.9,
                "local_path": "casos/TST/_raw_filings/SRC_E_ANNUAL_REPORT_2021.clean.md",
                "clean_md_status": "GENERATED",
                "extraction_status": "OK",
            },
        ]
        cfg = _Cfg({"tp_extractor_max_per_type": {"ANNUAL_REPORT": 4, "_default": 999}})
        selected = _select_filings(filings, cfg)
        selected_ids = {s.get("source_id") for s in selected}
        self.assertEqual(len(selected), 4)
        self.assertIn("SRC_E", selected_ids)
        self.assertNotIn("SRC_D", selected_ids)


if __name__ == "__main__":
    unittest.main()
