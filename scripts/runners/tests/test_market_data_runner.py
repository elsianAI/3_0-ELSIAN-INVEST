import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runners.market_data_v1_runner import (
    _build_yahoo_symbol_candidates,
    _select_yahoo_symbol_context,
)


class MarketDataRunnerTests(unittest.TestCase):
    def test_build_yahoo_candidates_euronext_fr_prefers_pa(self):
        candidates = _build_yahoo_symbol_candidates(
            ticker="TEP",
            exchange="EURONEXT",
            country="FR",
            web_ir="https://www.tp.com/en-us/investors/investors-homepage",
        )
        self.assertGreaterEqual(len(candidates), 2)
        self.assertEqual(candidates[0], "TEP.PA")
        self.assertIn("TEP", candidates)

    @mock.patch("scripts.runners.market_data_v1_runner.fetch_yahoo_snapshot")
    def test_symbol_selection_rejects_non_equity(self, snapshot_mock):
        def _fake_snapshot(ticker, exchange, symbol_override=None):
            symbol = symbol_override or ticker
            if symbol == "TEP":
                return {
                    "symbol": "TEP",
                    "instrument_type": "MUTUALFUND",
                    "snapshot": {"Price": "46.5"},
                    "company_name": "Wrong fund",
                    "exchange": "YHD",
                    "country": None,
                    "currency": "USD",
                    "url": "",
                }
            if symbol == "TEP.PA":
                return {
                    "symbol": "TEP.PA",
                    "instrument_type": "EQUITY",
                    "snapshot": {"Price": "95.0"},
                    "company_name": "Teleperformance SE",
                    "exchange": "PAR",
                    "country": "France",
                    "currency": "EUR",
                    "url": "",
                }
            return {
                "symbol": symbol,
                "instrument_type": None,
                "snapshot": {},
                "company_name": ticker,
                "exchange": exchange,
                "country": None,
                "currency": "USD",
                "url": "",
            }

        snapshot_mock.side_effect = _fake_snapshot
        ctx, trace = _select_yahoo_symbol_context(
            ticker="TEP",
            exchange="EURONEXT",
            country="FR",
            web_ir="https://example.com",
        )
        self.assertEqual(ctx.get("symbol"), "TEP.PA")
        self.assertEqual(trace.get("selected_symbol"), "TEP.PA")
        self.assertEqual(trace.get("selection_reason"), "equity_with_price")

    @mock.patch("scripts.runners.market_data_v1_runner.fetch_yahoo_snapshot")
    def test_symbol_selection_no_equity_candidate_keeps_hints(self, snapshot_mock):
        def _fake_snapshot(ticker, exchange, symbol_override=None):
            symbol = symbol_override or ticker
            return {
                "symbol": symbol,
                "instrument_type": "MUTUALFUND",
                "snapshot": {"Price": "10.0"},
                "company_name": "Wrong instrument",
                "exchange": "YHD",
                "country": None,
                "currency": "USD",
                "url": "",
            }

        snapshot_mock.side_effect = _fake_snapshot
        ctx, trace = _select_yahoo_symbol_context(
            ticker="TEP",
            exchange="EURONEXT",
            country="FR",
            web_ir="https://example.com",
        )
        self.assertIsNone(ctx.get("symbol"))
        self.assertEqual(ctx.get("company_name"), "TEP")
        self.assertEqual(ctx.get("exchange"), "EURONEXT")
        self.assertEqual(ctx.get("country"), "FR")
        self.assertEqual(trace.get("selection_reason"), "no_equity_candidate")


if __name__ == "__main__":
    unittest.main()
