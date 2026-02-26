#!/usr/bin/env python3
"""
R1 Canary Validation Script - Phase R1 V6.2 Implementation
Validates 5 canary cases (TEP, GCT, KAR, 0327, EVER) against R1 acceptance criteria.

Checks:
  1. Structural completeness (historico_anual, trimestral, balance_sheet, metricas_derivadas, data_quality)
  2. Quantitative thresholds (confidence >= 70, TEP completitud_ajustada >= 60%, no critical gate FAILs)
  3. Field-level spot checks (core fields in recent period, provenance, balance sheet)
  4. Merge/reconciliation quality (_merge_conflicts, reconciliation_log)
  5. Market data sanity (market_cap, precio from tp.mercado + cross-check vs _market_data_output)
  6. Filing partials existence (keep_tp_filing_partials=true)
"""

import json
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class CheckStatus(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    status: CheckStatus
    message: str
    details: Optional[Dict[str, Any]] = None


def _auto_base_path() -> str:
    """Resolve base path: script is at scripts/r1_canary_validation.py → parent is project root."""
    return str(Path(__file__).resolve().parent.parent)


class R1CanaryValidator:
    """Validates canary cases against R1 acceptance criteria."""

    CANARY_CASES = {
        "TEP": {"dir": "TEP", "run": "2026-02-25"},
        "GCT": {"dir": "GCT", "run": "2026-02-23"},
        "KAR": {"dir": "KAR", "run": "2026-02-22"},
        "0327": {"dir": "0327", "run": "2026-02-23"},
        "EVER": {"dir": "EVER", "run": "2026-02-23"},
    }

    def __init__(self, base_path: str, verbose: bool = False):
        self.base_path = Path(base_path)
        self.verbose = verbose

    def get_case_path(self, ticker: str) -> Path:
        case_config = self.CANARY_CASES[ticker]
        return self.base_path / "casos" / case_config["dir"] / case_config["run"]

    def load_json(self, file_path: Path) -> Optional[Any]:
        try:
            if not file_path.exists():
                return None
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            if self.verbose:
                print(f"  [ERROR] Failed to load {file_path.name}: {e}")
            return None

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace(",", "").strip())
            except ValueError:
                return None
        return None

    @staticmethod
    def _is_non_empty_dict(value: Any) -> bool:
        return isinstance(value, dict) and len(value) > 0

    def _resolve_market_cap_usd(
        self, tp_data: Dict, tp_calculated: Optional[Any], market_data_raw: Optional[Any]
    ) -> Tuple[Optional[float], str]:
        mercado = tp_data.get("mercado", {}) if isinstance(tp_data.get("mercado", {}), dict) else {}
        value = self._to_float(mercado.get("market_cap_usd"))
        if value and value > 0:
            return value, "tp.mercado.market_cap_usd"

        md = tp_data.get("metricas_derivadas", {}) if isinstance(tp_data.get("metricas_derivadas", {}), dict) else {}
        value = self._to_float(md.get("market_cap_usd"))
        if value and value > 0:
            return value, "tp.metricas_derivadas.market_cap_usd"

        if isinstance(tp_calculated, dict):
            md_calc = tp_calculated.get("metricas_derivadas", {})
            if isinstance(md_calc, dict):
                value = self._to_float(md_calc.get("market_cap_usd"))
                if value and value > 0:
                    return value, "_tp_calculated.metricas_derivadas.market_cap_usd"

        if isinstance(market_data_raw, dict):
            fuentes = market_data_raw.get("fuentes", [])
            if isinstance(fuentes, list) and fuentes:
                datos = fuentes[0].get("datos", {}) if isinstance(fuentes[0], dict) else {}
                raw_mm = self._to_float(datos.get("market_cap_millones"))
                if raw_mm and raw_mm > 0:
                    return raw_mm * 1_000_000, "_market_data_output.fuentes[0].datos.market_cap_millones*1e6"

        return None, "missing"

    def _resolve_price_usd(self, tp_data: Dict) -> Tuple[Optional[float], str]:
        mercado = tp_data.get("mercado", {}) if isinstance(tp_data.get("mercado", {}), dict) else {}

        price = self._to_float(mercado.get("precio_actual_usd"))
        if price and price > 0:
            return price, "tp.mercado.precio_actual_usd"

        precio_obj = mercado.get("precio", {})
        if isinstance(precio_obj, dict):
            divisa = str(precio_obj.get("divisa", "")).upper()
            valor = self._to_float(precio_obj.get("valor"))
            if divisa == "USD" and valor and valor > 0:
                return valor, "tp.mercado.precio.valor(USD)"

        return None, "missing"

    def _count_annual_filing_partials(self, case_path: Path) -> int:
        annual_types = {"ANNUAL_REPORT", "10-K", "20-F"}
        count = 0
        for partial_path in case_path.glob("_tmp_tp_filing_*.json"):
            payload = self.load_json(partial_path)
            if not isinstance(payload, dict):
                continue
            filing_type = str(payload.get("filing_type", "")).upper()
            if filing_type in annual_types:
                count += 1
        return count

    def _required_annual_periods(self, ticker: str, case_path: Path) -> int:
        if ticker != "TEP":
            return 0
        annual_filing_count = self._count_annual_filing_partials(case_path)
        if annual_filing_count <= 0:
            return 8
        # Dynamic threshold based on available annual reports.
        # 4 annual filings => 6 annual periods expected.
        return max(5, min(8, annual_filing_count + 2))

    # ── Check 1: Structural completeness ──────────────────────────────

    def validate_structural_completeness(self, ticker: str, tp_data: Dict,
                                         tp_calculated: Optional[Any], case_path: Path) -> CheckResult:
        issues = []

        # historico_anual
        ha = tp_data.get("historico_anual")
        if not ha or not isinstance(ha, list) or len(ha) == 0:
            issues.append("historico_anual missing or empty")
        elif ticker == "TEP":
            required_min = self._required_annual_periods(ticker, case_path)
            if required_min > 0 and len(ha) < required_min:
                issues.append(
                    f"TEP historico_anual has {len(ha)} periods (require >= {required_min})"
                )

        # historico_trimestral
        ht = tp_data.get("historico_trimestral")
        if not ht or not isinstance(ht, list) or len(ht) == 0:
            issues.append("historico_trimestral missing or empty")

        # balance_sheet_ultimo
        bs = tp_data.get("balance_sheet_ultimo")
        if not bs:
            issues.append("balance_sheet_ultimo missing")
        else:
            core = ["activos_totales_usd", "pasivos_totales_usd", "patrimonio_usd"]
            if not any(f in bs for f in core):
                issues.append("balance_sheet_ultimo missing all core fields")

        # _tp_calculated + metricas_derivadas required in strict mode
        if tp_calculated is None:
            issues.append("_tp_calculated file missing or invalid JSON")
        elif not isinstance(tp_calculated, dict):
            issues.append("_tp_calculated must be a JSON object")
        else:
            md_calc = tp_calculated.get("metricas_derivadas")
            if not self._is_non_empty_dict(md_calc):
                issues.append("_tp_calculated.metricas_derivadas missing or empty")

        # data_quality
        dq = tp_data.get("data_quality", {})
        if not dq:
            issues.append("data_quality missing")
        elif "confidence_score" not in dq:
            issues.append("data_quality missing confidence_score")

        if issues:
            return CheckResult(CheckStatus.FAIL,
                               f"Structural issues: {'; '.join(issues)}", {"issues": issues})
        return CheckResult(CheckStatus.PASS, "All structural requirements met")

    # ── Check 2: Quantitative thresholds ──────────────────────────────

    def validate_quantitative_checks(
        self,
        ticker: str,
        tp_data: Dict,
        tp_calculated: Optional[Any],
        market_data_raw: Optional[Any],
    ) -> CheckResult:
        issues = []
        details: Dict[str, Any] = {}

        dq = tp_data.get("data_quality", {})

        # confidence_score >= 70
        confidence = dq.get("confidence_score")
        details["confidence_score"] = confidence
        if confidence is None:
            issues.append("confidence_score missing")
        elif confidence < 70:
            issues.append(f"confidence_score {confidence} < 70")

        # TEP: completitud_ajustada >= 60%
        if ticker == "TEP":
            comp_obj = dq.get("completitud_ajustada_por_tipo", {})
            comp_pct = comp_obj.get("pct") if isinstance(comp_obj, dict) else None
            details["completitud_ajustada"] = comp_pct
            if comp_pct is None:
                issues.append("TEP completitud_ajustada_por_tipo.pct missing")
            elif comp_pct < 60:
                issues.append(f"TEP completitud_ajustada {comp_pct}% < 60%")

        # Critical gates (real key is "name", not "gate")
        gates = dq.get("gates", [])
        if isinstance(gates, list):
            failed = [g.get("name", g.get("gate", "?")) for g in gates
                      if g.get("status") == "FAIL" and g.get("critical")]
            if failed:
                issues.append(f"Critical gates FAIL: {', '.join(failed)}")
                details["failed_gates"] = failed

        # market_cap_usd with strict source order
        mc, mc_source = self._resolve_market_cap_usd(tp_data, tp_calculated, market_data_raw)
        details["market_cap_usd"] = mc
        details["market_cap_source"] = mc_source
        if not mc or mc <= 0:
            issues.append("market_cap_usd is null or <= 0")

        if issues:
            return CheckResult(CheckStatus.FAIL,
                               f"Quantitative failures: {'; '.join(issues)}", details)
        return CheckResult(CheckStatus.PASS, "All quantitative checks passed", details)

    # ── Check 3: Field-level spot checks ──────────────────────────────

    def validate_field_level_spot_checks(self, ticker: str, tp_data: Dict) -> CheckResult:
        issues = []
        details: Dict[str, Any] = {}

        ha = tp_data.get("historico_anual", [])
        if ha and isinstance(ha, list):
            recent = sorted(ha, key=lambda e: e.get("periodo", ""), reverse=True)[0]
            details["recent_period"] = recent.get("periodo", "?")

            core = ["ingresos_usd", "net_income_usd", "cfo_usd"]
            missing = [f for f in core if recent.get(f) is None]
            for f in core:
                details[f] = recent.get(f)
            if missing:
                issues.append(f"Missing core fields in recent period: {', '.join(missing)}")

            details["has_field_sources"] = "_field_sources" in recent
            if "_field_sources" not in recent:
                issues.append("_field_sources not present in recent period")

        bs = tp_data.get("balance_sheet_ultimo", {})
        if bs:
            bs_core = ["activos_totales_usd", "pasivos_totales_usd", "patrimonio_usd"]
            bs_vals = {f: bs.get(f) for f in bs_core}
            details["balance_sheet_fields"] = bs_vals
            if all(v is None or v == 0 for v in bs_vals.values()):
                issues.append("All balance_sheet_ultimo core fields are null/zero")

        if issues:
            return CheckResult(CheckStatus.WARN,
                               f"Field-level issues: {'; '.join(issues)}", details)
        return CheckResult(CheckStatus.PASS, "Field-level checks passed", details)

    # ── Check 4: Merge / reconciliation quality ───────────────────────

    def validate_merge_quality(self, ticker: str, tp_data: Dict) -> CheckResult:
        details: Dict[str, Any] = {}
        merge_conflicts_found = False
        potential_restatements: list = []

        for section in ("historico_anual", "historico_trimestral"):
            for entry in tp_data.get(section, []):
                conflicts = entry.get("_merge_conflicts", [])
                if conflicts:
                    merge_conflicts_found = True
                    details[f"{entry.get('periodo', '?')}_conflicts"] = len(conflicts)

        dq = tp_data.get("data_quality", {})
        rec_log = dq.get("reconciliation_log", [])
        if rec_log and isinstance(rec_log, list):
            details["reconciliation_entries"] = len(rec_log)
            for item in rec_log:
                if item.get("clasificacion") == "potential_restatement":
                    potential_restatements.append({
                        "periodo": item.get("periodo"),
                        "campo": item.get("campo"),
                        "diff_pct": item.get("diff_pct"),
                    })

        if merge_conflicts_found or potential_restatements:
            msg_parts = []
            if merge_conflicts_found:
                msg_parts.append("merge conflicts detected")
            if potential_restatements:
                msg_parts.append(f"{len(potential_restatements)} potential restatement(s)")
                details["potential_restatements"] = potential_restatements
            return CheckResult(CheckStatus.WARN, "; ".join(msg_parts), details)

        return CheckResult(CheckStatus.PASS, "Merge quality acceptable", details)

    # ── Check 5: Market data sanity ───────────────────────────────────

    def validate_market_data_sanity(self, ticker: str, tp_data: Dict,
                                    tp_calculated: Optional[Any],
                                    market_data_raw: Optional[Any]) -> CheckResult:
        issues = []
        details: Dict[str, Any] = {}

        mercado = tp_data.get("mercado", {}) if isinstance(tp_data.get("mercado", {}), dict) else {}

        # market_cap_usd (effective resolved)
        mc, mc_source = self._resolve_market_cap_usd(tp_data, tp_calculated, market_data_raw)
        details["market_cap_usd"] = mc
        details["market_cap_source"] = mc_source
        if not mc or mc <= 0:
            issues.append(f"market_cap_usd invalid: {mc}")

        # precio_actual_usd with explicit fallback from precio.valor when divisa==USD
        precio, price_source = self._resolve_price_usd(tp_data)
        details["precio_actual_usd_effective"] = precio
        details["price_source"] = price_source
        precio_obj = mercado.get("precio", {}) if isinstance(mercado.get("precio", {}), dict) else {}
        details["divisa"] = precio_obj.get("divisa")
        if not precio or precio <= 0:
            issues.append(f"precio_actual_usd invalid: {precio}")

        # EV
        ev = mercado.get("enterprise_value_usd")
        details["enterprise_value_usd"] = ev

        # Cross-check vs _market_data_output.json raw fetch
        if isinstance(market_data_raw, dict):
            fuentes = market_data_raw.get("fuentes", [])
            if isinstance(fuentes, list) and fuentes:
                datos = fuentes[0].get("datos", {}) if isinstance(fuentes[0], dict) else {}
                raw_mc_mm = self._to_float(datos.get("market_cap_millones"))
                tp_market_cap = self._to_float(mercado.get("market_cap_usd"))
                if raw_mc_mm is not None:
                    details["market_data_raw_market_cap_millones"] = raw_mc_mm
                if raw_mc_mm is not None and tp_market_cap and tp_market_cap > 0:
                    raw_mc = raw_mc_mm * 1_000_000
                    diff_pct = abs(tp_market_cap - raw_mc) / max(tp_market_cap, 1) * 100
                    details["cross_check_market_cap"] = {
                        "tp_mercado": tp_market_cap,
                        "market_data_raw_millions": raw_mc_mm,
                        "diff_pct": round(diff_pct, 2),
                    }
                    if diff_pct > 10:
                        issues.append(
                            f"market_cap cross-check diff {diff_pct:.1f}% "
                            f"(tp={tp_market_cap:.0f} vs raw={raw_mc:.0f})"
                        )

        if issues:
            return CheckResult(CheckStatus.FAIL,
                               f"Market data issues: {'; '.join(issues)}", details)
        return CheckResult(CheckStatus.PASS, "Market data sanity checks passed", details)

    # ── Check 6: Filing partials ──────────────────────────────────────

    def check_filing_partials(self, ticker: str) -> CheckResult:
        case_path = self.get_case_path(ticker)
        filing_files = list(case_path.glob("_tmp_tp_filing_*.json"))
        if not filing_files:
            return CheckResult(
                CheckStatus.WARN,
                "No filing partial files found (expected with keep_tp_filing_partials=true)",
                {"count": 0},
            )
        return CheckResult(
            CheckStatus.PASS,
            f"Filing partials present ({len(filing_files)} files)",
            {"count": len(filing_files), "files": [f.name for f in filing_files]},
        )

    # ── Case orchestrator ─────────────────────────────────────────────

    def validate_case(self, ticker: str) -> Dict[str, Any]:
        case_path = self.get_case_path(ticker)
        results: Dict[str, Any] = {
            "ticker": ticker,
            "case_path": str(case_path),
            "exists": case_path.exists(),
            "checks": {},
            "critical_passed": True,
            "warnings": [],
            "errors": [],
        }

        if not case_path.exists():
            results["critical_passed"] = False
            results["errors"].append(f"Case directory not found: {case_path}")
            return results

        # Load files
        tp_data = self.load_json(case_path / f"TruthPack_v1_{ticker}.json")
        if not tp_data:
            results["critical_passed"] = False
            results["errors"].append("TruthPack file not found or invalid")
            return results

        tp_calculated = self.load_json(case_path / f"_tp_calculated_{ticker}.json")
        market_data_raw = self.load_json(case_path / "_market_data_output.json")

        # Run all checks
        check_results = {
            "structural_completeness": self.validate_structural_completeness(
                ticker, tp_data, tp_calculated, case_path),
            "quantitative_checks": self.validate_quantitative_checks(
                ticker, tp_data, tp_calculated, market_data_raw),
            "field_level_spot_checks": self.validate_field_level_spot_checks(ticker, tp_data),
            "merge_quality": self.validate_merge_quality(ticker, tp_data),
            "market_data_sanity": self.validate_market_data_sanity(
                ticker, tp_data, tp_calculated, market_data_raw),
            "filing_partials": self.check_filing_partials(ticker),
        }

        for check_name, cr in check_results.items():
            results["checks"][check_name] = {
                "status": cr.status.value,
                "message": cr.message,
                "details": cr.details or {},
            }
            if cr.status == CheckStatus.FAIL:
                results["critical_passed"] = False
                results["errors"].append(f"{check_name}: {cr.message}")
            elif cr.status == CheckStatus.WARN:
                results["warnings"].append(f"{check_name}: {cr.message}")

        return results

    # ── Run & print ───────────────────────────────────────────────────

    def run_validation(self, cases: Optional[List[str]] = None) -> int:
        if cases is None:
            cases = list(self.CANARY_CASES.keys())
        else:
            cases = [c for c in cases if c in self.CANARY_CASES]
        if not cases:
            print("Error: No valid cases specified")
            return 1

        print("=" * 80)
        print("R1 CANARY VALIDATION - V6.2")
        print("=" * 80)
        print()

        all_passed = True
        case_results = {}

        for ticker in cases:
            print(f"Validating {ticker}...")
            result = self.validate_case(ticker)
            case_results[ticker] = result
            self._print_case(result)
            if not result["critical_passed"]:
                all_passed = False

        self._print_summary(case_results)
        return 0 if all_passed else 1

    def _print_case(self, result: Dict):
        ticker = result["ticker"]
        print(f"  Path: {result['case_path']}")
        if not result["exists"]:
            for e in result["errors"]:
                print(f"  [✗] {e}")
            print()
            return
        if not result["checks"]:
            for e in result["errors"]:
                print(f"  [✗] {e}")
            print()
            return

        for name, cr in result["checks"].items():
            sym = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}[cr["status"]]
            print(f"  [{sym}] {name}: {cr['status']} — {cr['message']}")
            if self.verbose and cr["details"]:
                print(f"      {json.dumps(cr['details'], indent=6, default=str)}")

        if result["warnings"]:
            print(f"  Warnings: {len(result['warnings'])}")

        sym = "✓" if result["critical_passed"] else "✗"
        label = "PASS" if result["critical_passed"] else "FAIL"
        print(f"  [{sym}] Overall: {label}")
        print()

    def _print_summary(self, case_results: Dict):
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        total = len(case_results)
        passed = sum(1 for r in case_results.values() if r["critical_passed"])
        for ticker, r in case_results.items():
            sym = "✓" if r["critical_passed"] else "✗"
            w = f" ({len(r['warnings'])} warn)" if r["warnings"] else ""
            print(f"  [{sym}] {ticker}: {'PASS' if r['critical_passed'] else 'FAIL'}{w}")
        print()
        print(f"Result: {passed}/{total} cases passed")
        if passed == total:
            print("Status: ALL CANARY CASES PASSED R1 VALIDATION")
        else:
            print(f"Status: {total - passed} case(s) FAILED")
        print()


def main():
    parser = argparse.ArgumentParser(description="R1 Canary Validation - V6.2")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--cases", type=str, default=None,
                        help="Comma-separated list (e.g. TEP,GCT)")
    parser.add_argument("--base-path", type=str, default=None,
                        help="Base path to project root (default: auto-detect from script location)")
    args = parser.parse_args()

    base = args.base_path or _auto_base_path()
    cases = [c.strip().upper() for c in args.cases.split(",")] if args.cases else None

    validator = R1CanaryValidator(base, verbose=args.verbose)
    sys.exit(validator.run_validation(cases))


if __name__ == "__main__":
    main()
