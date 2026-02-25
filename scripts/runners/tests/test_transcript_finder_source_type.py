import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runners.transcript_finder_v2_runner import classify_presentation_source_type


class TranscriptFinderSourceTypeTests(unittest.TestCase):
    def test_urd_is_classified_as_annual_report(self):
        source_type = classify_presentation_source_type(
            title="tp-2024-urd",
            url="https://www.tp.com/media/2balwxel/tp-2024-urd.pdf",
            row_text="Universal Registration Document 2024",
        )
        self.assertEqual(source_type, "ANNUAL_REPORT")

    def test_generic_presentation_stays_investor_presentation(self):
        source_type = classify_presentation_source_type(
            title="Q1 2025 investor presentation",
            url="https://www.tp.com/media/aipdimi0/tp-presentation-post-q1-2025.pdf",
            row_text="Investor presentation post Q1 2025",
        )
        self.assertEqual(source_type, "INVESTOR_PRESENTATION")


if __name__ == "__main__":
    unittest.main()
