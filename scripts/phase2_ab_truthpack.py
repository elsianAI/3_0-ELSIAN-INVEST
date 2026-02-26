#!/usr/bin/env python3
"""V6.2 Phase 2 A/B benchmark runner for TRUTH_PACK (OFF vs ON chunking).

Runs `rehacer TRUTH_PACK` for canary cases with two runtime configs:
- OFF: tp_extractor_chunked_enabled=false
- ON:  tp_extractor_chunked_enabled=true

Outputs:
- per-case snapshots under output-dir/{ticker}/{date}/off|on
- per-case metrics.json
- global summary.json + summary.md with go/no-go verdict
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WORKSPACE = Path(__file__).resolve().parent.parent
CASOS_DIR = WORKSPACE / "casos"

CANARY_CASES = {
    "TEP": "2026-02-25",
    "GCT": "2026-02-23",
    "KAR": "2026-02-22",
    "0327": "2026-02-23",
    "EVER": "2026-02-23",
}

WEIGHTS = {
    "primary": 1.0,
    "chunk": 0.2,
    "fusion": 1.0,
    "reconciliation": 2.0,
}


@dataclass
class RunResult:
    ok: bool
    duration_s: float
    stdout: str
    stderr: str
    return_code: int


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def find_truthpack(case_dir: Path) -> Path:
    candidates = sorted(case_dir.glob("TruthPack_v1*.json"))
    if not candidates:
        raise FileNotFoundError(f"No TruthPack_v1*.json in {case_dir}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def parse_cases_arg(raw_cases: str | None) -> dict[str, str]:
    if not raw_cases:
        return dict(CANARY_CASES)
    out: dict[str, str] = {}
    for token in [t.strip() for t in raw_cases.split(",") if t.strip()]:
        if ":" in token:
            ticker, date_str = token.split(":", 1)
            out[ticker.upper()] = date_str.strip()
            continue
        ticker = token.upper()
        if ticker not in CANARY_CASES:
            raise ValueError(
                f"Unknown case '{ticker}'. Use TICKER:YYYY-MM-DD for custom date."
            )
        out[ticker] = CANARY_CASES[ticker]
    return out


def extract_adjusted_completeness(tp: dict[str, Any]) -> float:
    dq = tp.get("data_quality", {})
    if not isinstance(dq, dict):
        raise ValueError("TruthPack.data_quality missing")
    adj = dq.get("completitud_ajustada_por_tipo", {})
    if not isinstance(adj, dict):
        raise ValueError("TruthPack.data_quality.completitud_ajustada_por_tipo missing")
    pct = adj.get("pct")
    if not isinstance(pct, (int, float)):
        raise ValueError("TruthPack.data_quality.completitud_ajustada_por_tipo.pct missing")
    return float(pct)


def extract_gate_completeness(tp: dict[str, Any]) -> float | None:
    dq = tp.get("data_quality", {})
    if not isinstance(dq, dict):
        return None
    gates = dq.get("gates", [])
    if not isinstance(gates, list):
        return None
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        if gate.get("name") == "DATA_COMPLETENESS":
            pct = gate.get("completeness_pct")
            if isinstance(pct, (int, float)):
                return float(pct)
    return None


def _to_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def compute_proxy_cost(
    provenance: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    w = weights or WEIGHTS
    records = provenance.get("records", [])
    if not isinstance(records, list) or not records:
        raise ValueError("provenance.records missing or empty")

    total = 0.0
    breakdown = {
        "primary_calls_cost": 0.0,
        "chunk_calls_cost": 0.0,
        "fusion_calls_cost": 0.0,
        "reconciliation_calls_cost": 0.0,
    }

    for rec in records:
        if not isinstance(rec, dict):
            continue
        dm = rec.get("dispatch_meta", {})
        if not isinstance(dm, dict):
            continue
        method = str(dm.get("method", ""))
        chunk_successful = max(0, _to_int(dm.get("chunk_successful"), 0))

        if method in {"llm_single", "llm_single_v1", "llm_single_v1_recovered"}:
            total += w["primary"]
            breakdown["primary_calls_cost"] += w["primary"]
        elif method == "llm_chunked_single":
            c = chunk_successful * w["chunk"]
            total += c
            breakdown["chunk_calls_cost"] += c
        elif method in {"llm_chunked_fusion", "llm_chunked_best_chunk_fallback"}:
            c = chunk_successful * w["chunk"]
            total += c + w["fusion"]
            breakdown["chunk_calls_cost"] += c
            breakdown["fusion_calls_cost"] += w["fusion"]

        cross = dm.get("cross_layer_reconciliation", {})
        if isinstance(cross, dict):
            arbitrations = max(0, _to_int(cross.get("arbitrations"), 0))
            if arbitrations > 0:
                c = arbitrations * w["reconciliation"]
                total += c
                breakdown["reconciliation_calls_cost"] += c

    if total <= 0:
        raise ValueError("proxy cost is zero; invalid or missing dispatch metadata")
    return total, breakdown


def collect_snapshot_metrics(snapshot_dir: Path) -> dict[str, Any]:
    tp_path = find_truthpack(snapshot_dir)
    tp = load_json(tp_path)
    adjusted = extract_adjusted_completeness(tp)
    global_pct = extract_gate_completeness(tp)

    provenance_path = snapshot_dir / "_extraction_provenance.json"
    provenance = load_json(provenance_path)
    cost, cost_breakdown = compute_proxy_cost(provenance, weights=WEIGHTS)

    return {
        "truthpack_path": str(tp_path),
        "adjusted_completeness_pct": adjusted,
        "global_completeness_pct": global_pct,
        "proxy_cost": cost,
        "proxy_cost_breakdown": cost_breakdown,
        "provenance_path": str(provenance_path),
    }


def evaluate_go_no_go(
    case_results: dict[str, dict[str, Any]],
    *,
    canary_ok: bool,
    regression_ok: bool,
) -> dict[str, Any]:
    reasons: list[str] = []
    ok_cases = [v for v in case_results.values() if v.get("status") == "ok"]

    if len(ok_cases) != len(case_results):
        failed = [k for k, v in case_results.items() if v.get("status") != "ok"]
        reasons.append(f"Cases without valid metrics: {', '.join(failed)}")
        return {
            "go": False,
            "reasons": reasons,
            "metrics": {},
        }

    mean_delta = sum(float(v["delta_pp_adjusted"]) for v in ok_cases) / len(ok_cases)
    mean_cost_ratio = sum(float(v["cost_ratio"]) for v in ok_cases) / len(ok_cases)
    mean_latency_ratio = sum(float(v["latency_ratio"]) for v in ok_cases) / len(ok_cases)

    if mean_delta < 10.0:
        reasons.append(f"mean delta_pp_adjusted {mean_delta:.2f} < 10.00")
    if mean_cost_ratio > 1.5:
        reasons.append(f"mean cost_ratio {mean_cost_ratio:.3f} > 1.500")
    if mean_latency_ratio > 2.5:
        reasons.append(f"mean latency_ratio {mean_latency_ratio:.3f} > 2.500")
    if not canary_ok:
        reasons.append("r1_canary_validation failed")
    if not regression_ok:
        reasons.append("regression_check failed")

    return {
        "go": len(reasons) == 0,
        "reasons": reasons,
        "metrics": {
            "mean_delta_pp_adjusted": mean_delta,
            "mean_cost_ratio": mean_cost_ratio,
            "mean_latency_ratio": mean_latency_ratio,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown_summary(path: Path, summary: dict[str, Any]) -> None:
    rows = summary.get("cases", {})
    lines = [
        "# V6.2 Phase 2 A/B Summary",
        "",
        f"- Verdict: **{'GO' if summary['go_no_go']['go'] else 'NO_GO'}**",
        "",
        "## Global metrics",
    ]
    g = summary["go_no_go"].get("metrics", {})
    if g:
        lines.extend(
            [
                f"- mean_delta_pp_adjusted: {g['mean_delta_pp_adjusted']:.3f}",
                f"- mean_cost_ratio: {g['mean_cost_ratio']:.3f}",
                f"- mean_latency_ratio: {g['mean_latency_ratio']:.3f}",
            ]
        )
    else:
        lines.append("- n/a")

    lines.extend(
        [
            "",
            "## Per-case",
            "",
            "| Case | Status | Delta pp adj | Cost ratio | Latency ratio |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for case_key, data in rows.items():
        if data.get("status") == "ok":
            lines.append(
                f"| {case_key} | ok | {data['delta_pp_adjusted']:.3f} | "
                f"{data['cost_ratio']:.3f} | {data['latency_ratio']:.3f} |"
            )
        else:
            err = str(data.get("error", "unknown")).replace("|", "/")
            lines.append(f"| {case_key} | error | n/a | n/a | n/a ({err}) |")

    reasons = summary["go_no_go"].get("reasons", [])
    lines.extend(["", "## Go/No-Go reasons"])
    if reasons:
        lines.extend([f"- {r}" for r in reasons])
    else:
        lines.append("- All thresholds passed.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_runtime_config(base_cfg: dict[str, Any], *, chunked_enabled: bool) -> dict[str, Any]:
    out = copy.deepcopy(base_cfg)
    out.setdefault("execution", {})
    out["execution"]["tp_extractor_chunked_enabled"] = bool(chunked_enabled)
    out.setdefault("git", {})
    out["git"]["enabled"] = False
    return out


def absolutize_paths(cfg: dict[str, Any], *, base_config_dir: Path) -> dict[str, Any]:
    out = copy.deepcopy(cfg)

    def _absolutize_map(map_name: str) -> None:
        mapping = out.get(map_name)
        if not isinstance(mapping, dict):
            return
        abs_mapping: dict[str, str] = {}
        for key, value in mapping.items():
            if not isinstance(value, str):
                continue
            p = Path(value)
            if p.is_absolute():
                abs_mapping[key] = str(p)
            else:
                abs_mapping[key] = str((base_config_dir / p).resolve())
        out[map_name] = abs_mapping

    # Support both legacy "_paths" and current "paths" config layouts.
    _absolutize_map("_paths")
    _absolutize_map("paths")
    return out


def run_rehacer(config_path: Path, ticker: str, date_str: str, *, verbose: bool) -> RunResult:
    cmd = [
        sys.executable,
        "-m",
        "engine",
        "--config",
        str(config_path),
        "rehacer",
        ticker,
        "TRUTH_PACK",
        "--date",
        date_str,
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(WORKSPACE),
        capture_output=True,
        text=True,
    )
    dt = time.perf_counter() - t0
    if verbose:
        print(f"[ab] cmd: {' '.join(cmd)}")
        print(f"[ab] rc={proc.returncode} t={dt:.2f}s")
    return RunResult(
        ok=(proc.returncode == 0),
        duration_s=dt,
        stdout=proc.stdout,
        stderr=proc.stderr,
        return_code=proc.returncode,
    )


def run_aux_check(args: list[str], *, output_path: Path, verbose: bool) -> bool:
    proc = subprocess.run(
        args,
        cwd=str(WORKSPACE),
        capture_output=True,
        text=True,
    )
    output_path.write_text(
        f"$ {' '.join(args)}\n\n--- STDOUT ---\n{proc.stdout}\n\n--- STDERR ---\n{proc.stderr}\n",
        encoding="utf-8",
    )
    if verbose:
        print(f"[ab] aux rc={proc.returncode}: {' '.join(args)}")
    return proc.returncode == 0


def cleanup_tmp_partials(case_dir: Path) -> int:
    removed = 0
    for path in case_dir.glob("_tmp_tp_filing_*.json"):
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def snapshot_case(case_dir: Path, target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(case_dir, target_dir)


def runtime_config_paths(run_id: str) -> tuple[Path, Path]:
    return (
        WORKSPACE / f".engine_config_ab_off_{run_id}.json",
        WORKSPACE / f".engine_config_ab_on_{run_id}.json",
    )


def _extract_model_roles(cfg: dict[str, Any]) -> dict[str, str]:
    """Extract model roles from config for display."""
    overrides = cfg.get("step_overrides", {}).get("TP_EXTRACTOR_FILING", {})
    models = overrides.get("models", [])
    chunk_models = overrides.get("chunk_models", [])
    return {
        "primary": models[0] if models else cfg.get("default_single_model", "?"),
        "chunk": chunk_models[0] if chunk_models else "?",
        "fusion": overrides.get("chunk_fusion_model", "?"),
        "reconciliation": overrides.get("reconciliation_model", "?"),
    }


def _log(msg: str, *, err: bool = False) -> None:
    """Print a [benchmark] prefixed message."""
    print(f"[benchmark] {msg}", file=sys.stderr if err else sys.stdout, flush=True)


def assert_truthpack_done(case_dir: Path) -> None:
    state_path = case_dir / "_estado.json"
    state = load_json(state_path)

    pipeline = state.get("pipeline")
    if not isinstance(pipeline, dict):
        raise RuntimeError("pipeline missing in _estado.json")

    tp_state = pipeline.get("TRUTH_PACK")
    if not isinstance(tp_state, dict):
        raise RuntimeError("pipeline.TRUTH_PACK missing in _estado.json")

    if tp_state.get("estado") != "DONE":
        raise RuntimeError(f"pipeline.TRUTH_PACK.estado={tp_state.get('estado')!r}")

    sub_steps = state.get("sub_steps")
    if not isinstance(sub_steps, dict):
        raise RuntimeError("sub_steps missing in _estado.json")

    required_subs = (
        "TP_EXTRACTOR_FILING",
        "TP_EXTRACTOR_MERGER",
        "TP_CALCULATOR",
        "TP_VALIDATOR",
    )
    for sub in required_subs:
        sub_state = sub_steps.get(sub)
        if not isinstance(sub_state, dict):
            raise RuntimeError(f"sub_steps.{sub} missing in _estado.json")
        if sub_state.get("status") != "DONE":
            raise RuntimeError(f"sub_steps.{sub}.status={sub_state.get('status')!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="V6.2 Phase 2 A/B benchmark (TRUTH_PACK).")
    parser.add_argument("--cases", type=str, default=",".join(CANARY_CASES.keys()))
    parser.add_argument("--base-config", type=Path, default=WORKSPACE / "engine_config.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--skip-canary", action="store_true")
    parser.add_argument("--skip-regression", action="store_true")
    parser.add_argument("--keep-temp-configs", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    cases = parse_cases_arg(args.cases)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    base_cfg = load_json(args.base_config)
    off_cfg = make_runtime_config(base_cfg, chunked_enabled=False)
    on_cfg = make_runtime_config(base_cfg, chunked_enabled=True)
    base_cfg_dir = args.base_config.resolve().parent
    off_cfg = absolutize_paths(off_cfg, base_config_dir=base_cfg_dir)
    on_cfg = absolutize_paths(on_cfg, base_config_dir=base_cfg_dir)
    run_id = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000000:06d}"
    off_cfg_path, on_cfg_path = runtime_config_paths(run_id)
    write_json(off_cfg_path, off_cfg)
    write_json(on_cfg_path, on_cfg)

    # ── Header ──────────────────────────────────────────────
    model_roles = _extract_model_roles(base_cfg)
    cases_display = ", ".join(f"{t}({d})" for t, d in cases.items())
    _log("═══ V6.2 Phase 2 A/B Benchmark ═══")
    _log(f"Casos: {cases_display}")
    _log(f"Modelos: primary={model_roles['primary']}, chunk={model_roles['chunk']}, "
         f"fusion={model_roles['fusion']}, reconciliation={model_roles['reconciliation']}")
    _log(f"Thresholds: delta>=+10pp, cost<=1.5x, latency<=2.5x")
    _log(f"Output: {output_dir}")
    _log(f"Configs: OFF={off_cfg_path.name}, ON={on_cfg_path.name}")
    _log("")

    try:
        if args.keep_temp_configs:
            write_json(output_dir / "engine_config_ab_off.json", off_cfg)
            write_json(output_dir / "engine_config_ab_on.json", on_cfg)

        case_results: dict[str, dict[str, Any]] = {}
        total_cases = len(cases)
        for case_idx, (ticker, date_str) in enumerate(cases.items(), 1):
            case_key = f"{ticker}:{date_str}"
            case_dir = CASOS_DIR / ticker / date_str
            per_case_dir = output_dir / ticker / date_str
            per_case_dir.mkdir(parents=True, exist_ok=True)

            _log(f"═══ Caso {case_idx}/{total_cases}: {ticker} ({date_str}) ═══")

            try:
                if not case_dir.exists():
                    raise FileNotFoundError(f"case dir not found: {case_dir}")

                # ── OFF run ──
                _log("  → OFF (chunked=false) ...")
                cleanup_tmp_partials(case_dir)
                off_run = run_rehacer(off_cfg_path, ticker, date_str, verbose=args.verbose)
                (per_case_dir / "off_run.stdout.log").write_text(off_run.stdout, encoding="utf-8")
                (per_case_dir / "off_run.stderr.log").write_text(off_run.stderr, encoding="utf-8")
                if not off_run.ok:
                    _log(f"    ✗ OFF failed rc={off_run.return_code}", err=True)
                    raise RuntimeError(f"OFF run failed rc={off_run.return_code}")
                try:
                    assert_truthpack_done(case_dir)
                except Exception as exc:
                    _log(f"    ✗ OFF TRUTH_PACK not DONE: {exc}", err=True)
                    raise RuntimeError(f"off_truthpack_not_done: {exc}") from exc
                snapshot_case(case_dir, per_case_dir / "off")
                off_metrics = collect_snapshot_metrics(per_case_dir / "off")
                _log(f"    ✓ TRUTH_PACK DONE ({off_run.duration_s:.1f}s)")
                _log(f"    completitud_ajustada: {off_metrics['adjusted_completeness_pct']:.1f}%")
                _log(f"    proxy_cost: {off_metrics['proxy_cost']:.1f}")

                # ── ON run ──
                _log("  → ON  (chunked=true) ...")
                cleanup_tmp_partials(case_dir)
                on_run = run_rehacer(on_cfg_path, ticker, date_str, verbose=args.verbose)
                (per_case_dir / "on_run.stdout.log").write_text(on_run.stdout, encoding="utf-8")
                (per_case_dir / "on_run.stderr.log").write_text(on_run.stderr, encoding="utf-8")
                if not on_run.ok:
                    _log(f"    ✗ ON failed rc={on_run.return_code}", err=True)
                    raise RuntimeError(f"ON run failed rc={on_run.return_code}")
                try:
                    assert_truthpack_done(case_dir)
                except Exception as exc:
                    _log(f"    ✗ ON TRUTH_PACK not DONE: {exc}", err=True)
                    raise RuntimeError(f"on_truthpack_not_done: {exc}") from exc
                snapshot_case(case_dir, per_case_dir / "on")
                on_metrics = collect_snapshot_metrics(per_case_dir / "on")
                _log(f"    ✓ TRUTH_PACK DONE ({on_run.duration_s:.1f}s)")
                _log(f"    completitud_ajustada: {on_metrics['adjusted_completeness_pct']:.1f}%")
                _log(f"    proxy_cost: {on_metrics['proxy_cost']:.1f}")

                # ── Per-case result ──
                latency_ratio = (
                    on_run.duration_s / off_run.duration_s if off_run.duration_s > 0 else float("inf")
                )
                cost_ratio = (
                    on_metrics["proxy_cost"] / off_metrics["proxy_cost"]
                    if off_metrics["proxy_cost"] > 0
                    else float("inf")
                )
                delta_pp = (
                    on_metrics["adjusted_completeness_pct"] - off_metrics["adjusted_completeness_pct"]
                )

                _log(f"  → Resultado {ticker}: delta={delta_pp:+.1f}pp, "
                     f"cost={cost_ratio:.2f}x, latency={latency_ratio:.2f}x")
                _log("")

                metrics = {
                    "status": "ok",
                    "off": {
                        "latency_s": off_run.duration_s,
                        **off_metrics,
                    },
                    "on": {
                        "latency_s": on_run.duration_s,
                        **on_metrics,
                    },
                    "latency_ratio": latency_ratio,
                    "cost_ratio": cost_ratio,
                    "delta_pp_adjusted": delta_pp,
                }
                write_json(per_case_dir / "metrics.json", metrics)
                case_results[case_key] = metrics
            except Exception as exc:
                _log(f"  ✗ {ticker} ERROR: {exc}", err=True)
                _log("")
                case_results[case_key] = {
                    "status": "error",
                    "error": str(exc),
                }
                write_json(per_case_dir / "metrics.json", case_results[case_key])

        # ── Checks ──────────────────────────────────────────
        _log("═══ Checks finales ═══")
        tickers_csv = ",".join(cases.keys())
        canary_ok = True
        regression_ok = True

        if not args.skip_canary:
            canary_ok = run_aux_check(
                [
                    sys.executable,
                    "scripts/r1_canary_validation.py",
                    "--cases",
                    tickers_csv,
                ],
                output_path=output_dir / "canary.log",
                verbose=args.verbose,
            )
            _log(f"  → Canary validation: {'✓ PASS' if canary_ok else '✗ FAIL'}")
        else:
            _log("  → Canary validation: SKIPPED")

        if not args.skip_regression:
            regression_ok = run_aux_check(
                [
                    sys.executable,
                    "scripts/regression_check.py",
                    "--check",
                    "--cases",
                    tickers_csv,
                ],
                output_path=output_dir / "regression.log",
                verbose=args.verbose,
            )
            _log(f"  → Regression check:  {'✓ PASS' if regression_ok else '✗ FAIL'}")
        else:
            _log("  → Regression check:  SKIPPED")

        # ── Verdict ─────────────────────────────────────────
        verdict = evaluate_go_no_go(case_results, canary_ok=canary_ok, regression_ok=regression_ok)
        summary = {
            "version": "V6.2_Phase2_AB_v1",
            "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cases": case_results,
            "checks": {
                "canary_ok": canary_ok,
                "regression_ok": regression_ok,
            },
            "thresholds": {
                "mean_delta_pp_adjusted_min": 10.0,
                "mean_cost_ratio_max": 1.5,
                "mean_latency_ratio_max": 2.5,
            },
            "go_no_go": verdict,
        }
        write_json(output_dir / "summary.json", summary)
        write_markdown_summary(output_dir / "summary.md", summary)

        _log("")
        _log("═══ Veredicto ═══")
        g = verdict.get("metrics", {})
        if g:
            d = g.get("mean_delta_pp_adjusted", 0)
            c = g.get("mean_cost_ratio", 0)
            l = g.get("mean_latency_ratio", 0)
            _log(f"  mean_delta_pp:      {d:+.1f}pp  (threshold: >=+10)  {'✓' if d >= 10.0 else '✗'}")
            _log(f"  mean_cost_ratio:    {c:.2f}x   (threshold: <=1.5)  {'✓' if c <= 1.5 else '✗'}")
            _log(f"  mean_latency_ratio: {l:.2f}x   (threshold: <=2.5)  {'✓' if l <= 2.5 else '✗'}")
        else:
            _log("  No valid metrics (cases failed)")

        if verdict["go"]:
            _log("  → GO")
            _log(f"  summary: {output_dir / 'summary.json'}")
            return 0
        _log("  → NO_GO")
        for reason in verdict.get("reasons", []):
            _log(f"    - {reason}")
        _log(f"  summary: {output_dir / 'summary.json'}")
        return 1
    finally:
        if not args.keep_temp_configs:
            off_cfg_path.unlink(missing_ok=True)
            on_cfg_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
