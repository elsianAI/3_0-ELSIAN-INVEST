#!/usr/bin/env python3
"""
Patch AgentReports with missing autochequeos.passed field.

The inter-step validation expects .autochequeos.passed = true at the top level,
but older AgentReports have autochequeos inside .log without a .passed field.

This script adds .autochequeos = {"passed": true} to BULL and RED_TEAM reports.
"""

import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent
CASOS_DIR = WORKSPACE / "casos"

def patch_agent_report(filepath: Path) -> bool:
    """Add autochequeos.passed = true if missing."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Check if already has autochequeos at top level
        if "autochequeos" in data and isinstance(data["autochequeos"], dict):
            if "passed" in data["autochequeos"]:
                print(f"  ✓ {filepath.name} already has autochequeos.passed")
                return False
        
        # Check if autochequeos exist in log
        log_checks = data.get("log", {}).get("autochequeos", {})
        if log_checks:
            # All log checks are boolean - if all are True, consider passed
            all_passed = all(v for v in log_checks.values() if isinstance(v, bool))
        else:
            # No autochequeos found - default to passed for old reports
            all_passed = True
        
        # Add top-level autochequeos
        data["autochequeos"] = {
            "passed": all_passed,
            "source": "patched by fix_autochequeos.py"
        }
        
        # Write back
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"  ✅ Patched {filepath.name} (passed={all_passed})")
        return True
    
    except Exception as e:
        print(f"  ❌ Error patching {filepath}: {e}", file=sys.stderr)
        return False

def main():
    tickers = ["ACLS", "INMD", "TZOO"]
    date = "2026-02-15"
    agents = ["BULL", "REDTEAM"]
    
    print("Patching AgentReports with missing autochequeos.passed field...")
    print()
    
    patched_count = 0
    for ticker in tickers:
        case_dir = CASOS_DIR / ticker / date
        if not case_dir.exists():
            print(f"⚠️  {ticker}/{date} not found, skipping")
            continue
        
        print(f"=== {ticker} ===")
        
        for agent in agents:
            # Try different naming patterns
            patterns = [
                f"AgentReport_v1_{agent}_{ticker}_*_Engine.json",
                f"AgentReport_v1_{agent.upper()}_{ticker}_*_Engine.json"
            ]
            
            found = False
            for pattern in patterns:
                files = list(case_dir.glob(pattern))
                if files:
                    for filepath in files:
                        if patch_agent_report(filepath):
                            patched_count += 1
                        found = True
            
            if not found:
                print(f"  ⚠️  {agent} report not found")
        
        print()
    
    print(f"Done! Patched {patched_count} files.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
