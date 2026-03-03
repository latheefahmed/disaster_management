from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'core_engine' / 'phase4' / 'optimization' / 'just_runs_cbc.py'
OUT_ALLOC = ROOT / 'core_engine' / 'phase4' / 'optimization' / 'output' / 'allocation_x.csv'
OUT_UNMET = ROOT / 'core_engine' / 'phase4' / 'optimization' / 'output' / 'unmet_demand_u.csv'
RUN_SUMMARY = ROOT / 'core_engine' / 'phase4' / 'optimization' / 'output' / 'run_summary.json'


def run_case(label: str, demand: Path, state_stock: Path | None = None, national_stock: Path | None = None):
    cmd = [sys.executable, str(ENGINE), '--demand', str(demand)]
    if state_stock:
        cmd += ['--state-stock', str(state_stock)]
    if national_stock:
        cmd += ['--national-stock', str(national_stock)]

    result = subprocess.run(cmd, cwd=str(ROOT / 'core_engine'), capture_output=True, text=True)

    status_match = re.search(r'Status:\s*(\w+)', result.stdout)
    status_text = status_match.group(1) if status_match else 'UNKNOWN'

    alloc_rows = pd.read_csv(OUT_ALLOC)
    unmet_rows = pd.read_csv(OUT_UNMET)

    run_summary = {}
    if RUN_SUMMARY.exists():
        run_summary = json.loads(RUN_SUMMARY.read_text(encoding='utf-8'))

    total_alloc = float(alloc_rows['allocated_quantity'].sum()) if 'allocated_quantity' in alloc_rows.columns else 0.0
    total_unmet = float(unmet_rows['unmet_quantity'].sum()) if 'unmet_quantity' in unmet_rows.columns else 0.0

    passed = (
        result.returncode == 0
        and status_text in {'Optimal', 'OPTIMAL'}
        and len(alloc_rows.index) > 0
        and total_alloc >= 0
        and total_unmet >= 0
    )

    return {
        'label': label,
        'passed': passed,
        'return_code': result.returncode,
        'status': status_text,
        'allocation_rows': int(len(alloc_rows.index)),
        'unmet_rows': int(len(unmet_rows.index)),
        'total_allocated': total_alloc,
        'total_unmet': total_unmet,
        'run_summary_status': run_summary.get('status'),
        'run_summary_objective': run_summary.get('objective'),
    }


def main():
    generated = ROOT / 'core_engine' / 'phase4' / 'scenarios' / 'generated'

    cases = [
        {
            'label': 'LIVE_DEMAND',
            'demand': ROOT / 'core_engine' / 'phase4' / 'optimization' / 'output' / 'live_demand.csv',
            'state_stock': None,
            'national_stock': None,
        },
        {
            'label': 'SCENARIO_4',
            'demand': generated / 'scenario_4_demand.csv',
            'state_stock': generated / 'scenario_4_state_stock.csv',
            'national_stock': generated / 'scenario_4_national_stock.csv',
        },
    ]

    reports = []
    for case in cases:
        reports.append(run_case(case['label'], case['demand'], case['state_stock'], case['national_stock']))

    out_path = Path(__file__).resolve().parent / 'manual_solver_validation_report.json'
    out_path.write_text(json.dumps(reports, indent=2), encoding='utf-8')

    print('=== MANUAL SOLVER VALIDATION ===')
    for rep in reports:
        print(
            f"{rep['label']}: pass={rep['passed']} status={rep['status']} alloc_rows={rep['allocation_rows']} "
            f"unmet_rows={rep['unmet_rows']} total_alloc={rep['total_allocated']:.3f} total_unmet={rep['total_unmet']:.3f}"
        )
    print(f'Report written to: {out_path}')


if __name__ == '__main__':
    main()
