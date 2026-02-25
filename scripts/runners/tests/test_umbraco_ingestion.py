import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runners.sec_fetcher_v2_runner import (
    _collect_umbraco_candidates,
    _extract_umbraco_modules,
    _infer_umbraco_cultures,
    _rows_to_local_candidates,
)


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, url, *, binary=False, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        page = int((params or {}).get("page", 1))
        if "GetFileDownload" in url:
            if page == 1:
                return _FakeResponse(
                    {
                        "results": [
                            {
                                "title": "Universal Registration Document 2024",
                                "file": "/media/2balwxel/tp-2024-urd.pdf",
                            }
                        ]
                    }
                )
            return _FakeResponse({"results": []})
        return _FakeResponse({"resultado": []})


class UmbracoIngestionTests(unittest.TestCase):
    def test_extract_umbraco_modules_parses_node_id(self):
        html = """
        <script>
            new filesDownloadList('50525625','1797','x','y','z');
            new filesDownloadList('50525625','1797','x','y','z');
        </script>
        """
        modules = _extract_umbraco_modules(html)
        self.assertEqual(len(modules), 1)
        self.assertEqual(modules[0]["node_id"], "1797")

    def test_rows_to_candidates_normalizes_relative_pdf_and_filters_register(self):
        rows = [
            {
                "title": "Nine months 2025 revenue - Webcast replay",
                "file": "https://tp.engagestream.companywebcast.com/2025_third_quarter_revenue/register",
            },
            {
                "title": "Universal Registration Document 2024",
                "file": "/media/2balwxel/tp-2024-urd.pdf",
            },
        ]
        candidates = _rows_to_local_candidates(
            rows,
            page_url="https://www.tp.com/en-us/investors/publications-and-events/financial-publications",
            exchange="EPA",
            culture="en-us",
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["tipo_guess"], "ANNUAL_REPORT")
        self.assertTrue(candidates[0]["url"].startswith("https://www.tp.com/media/"))

    def test_infer_umbraco_cultures_handles_locale_and_country(self):
        self.assertEqual(
            _infer_umbraco_cultures("https://www.tp.com/en-us/investors", "FR"),
            ["en-us", "fr-fr"],
        )
        self.assertEqual(
            _infer_umbraco_cultures("https://www.tp.com/fr-fr/investors", None),
            ["fr-fr", "en-us"],
        )
        self.assertEqual(
            _infer_umbraco_cultures("https://www.tp.com/investors", "FR"),
            ["fr-fr", "en-us"],
        )

    def test_collect_umbraco_candidates_accepts_results_key(self):
        client = _FakeClient()
        html = "<script>new filesDownloadList('50525625','1797','x','y','z');</script>"
        candidates, metrics, errors = _collect_umbraco_candidates(
            client=client,
            html=html,
            page_url="https://www.tp.com/en-us/investors/publications-and-events/financial-publications",
            exchange="EPA",
            country="FR",
        )
        self.assertEqual(metrics["modules_detected"], 1)
        self.assertGreaterEqual(metrics["rows_collected"], 1)
        self.assertEqual(metrics["api_errors"], 0)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["tipo_guess"], "ANNUAL_REPORT")
        self.assertGreaterEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
