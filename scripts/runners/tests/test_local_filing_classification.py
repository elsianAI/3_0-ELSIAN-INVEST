import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runners.sec_fetcher_v2_runner import _classify_local_filing_type


class LocalFilingClassificationTests(unittest.TestCase):
    def test_press_release_with_annual_keyword_is_not_annual_report(self):
        filing_type = _classify_local_filing_type(
            "TP press release 2024 annual results",
            "https://example.com/tp-press-release-2024-annual-results.pdf",
            "press release annual results",
        )
        self.assertEqual(filing_type, "REGULATORY_FILING")

    def test_press_release_about_annual_report_is_ir_news(self):
        filing_type = _classify_local_filing_type(
            "Press release: Annual report 2024 now available",
            "https://example.com/press-release-annual-report-2024.pdf",
            "press release annual report available",
        )
        self.assertEqual(filing_type, "IR_NEWS")

    def test_urd_is_classified_as_annual_report(self):
        filing_type = _classify_local_filing_type(
            "Universal Registration Document 2024",
            "https://example.com/media/tp-2024-urd.pdf",
            "universal registration document",
        )
        self.assertEqual(filing_type, "ANNUAL_REPORT")


if __name__ == "__main__":
    unittest.main()
