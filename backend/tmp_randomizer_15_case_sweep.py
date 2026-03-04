import json
import random
import time
from datetime import datetime
from pathlib import Path

import requests

API = 'http://127.0.0.1:8000'
CASES = 15
PRESETS = ['very_low', 'low', 'medium', 'high', 'extreme']


def req(method, url, headers=None, payload=None, timeout=120):
    if method == 'GET':
        r = requests.get(url, headers=headers, timeout=timeout)
    else:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def main():
    login = requests.post(f'{API}/auth/login', json={'username': 'admin', 'password': 'admin123'}, timeout=30)
    login.raise_for_status()
    headers = {'Authorization': f"Bearer {login.json()['access_token']}"}

    states = req('GET', f'{API}/metadata/states', headers=headers, timeout=30)

    results = []
    for idx in range(CASES):
        preset = PRESETS[idx % len(PRESETS)]
        horizon = 1 if idx < 5 else (2 if idx < 10 else 3)
        stress_mode = preset in {'high', 'extreme'}
        district_count = random.randint(2, 7)
        resource_count = random.randint(2, 7)

        scoped_state_codes = []
        if states and idx % 2 == 0:
            scoped_state_codes = [str(random.choice(states).get('state_code'))]

        scenario = req('POST', f'{API}/admin/scenarios', headers=headers, payload={'name': f'AUTO_RAND_SWEEP_{idx+1}_{int(time.time())}'}, timeout=30)
        scenario_id = int(scenario['id'])

        payload = {
            'preset': preset,
            'seed': 20260304 + idx,
            'time_horizon': horizon,
            'stress_mode': stress_mode,
            'district_count': district_count,
            'resource_count': resource_count,
            'state_codes': scoped_state_codes,
            'district_codes': [],
            'resource_ids': [],
            'quantity_mode': 'stock_aware',
            'stock_aware_distribution': True,
            'replace_existing': False,
        }

        case = {
            'case': idx + 1,
            'scenario_id': scenario_id,
            'preset': preset,
            'horizon': horizon,
            'district_count_requested': district_count,
            'resource_count_requested': resource_count,
            'state_scope': scoped_state_codes,
        }

        try:
            preview = req('POST', f'{API}/admin/scenarios/{scenario_id}/randomizer/preview', headers=headers, payload=payload, timeout=90)
            apply = req('POST', f'{API}/admin/scenarios/{scenario_id}/randomizer/apply', headers=headers, payload=payload, timeout=90)
            run_resp = requests.post(f'{API}/admin/scenarios/{scenario_id}/run', headers=headers, json={'scope_mode': 'focused'}, timeout=240)
            runs = req('GET', f'{API}/admin/scenarios/{scenario_id}/runs', headers=headers, timeout=60)
            run_id = int(runs[0]['id']) if runs else None
            summary = req('GET', f'{API}/admin/scenarios/{scenario_id}/runs/{run_id}/summary', headers=headers, timeout=90) if run_id else None

            allocated = float((summary or {}).get('totals', {}).get('allocated_quantity') or 0.0)
            unmet = float((summary or {}).get('totals', {}).get('unmet_quantity') or 0.0)
            demand = allocated + unmet
            service_ratio = (allocated / demand) if demand > 1e-9 else 0.0

            case.update({
                'preview_ok': True,
                'apply_ok': True,
                'run_http': int(run_resp.status_code),
                'run_status': (runs[0]['status'] if runs else 'unknown'),
                'run_id': run_id,
                'preview_row_count': int(preview.get('row_count') or 0),
                'preview_quantity_mode': preview.get('quantity_mode'),
                'preview_stock_backed_rows': int(preview.get('stock_backed_rows') or 0),
                'preview_zero_stock_rows': int(preview.get('zero_stock_rows') or 0),
                'summary_service_ratio': service_ratio,
                'summary_scope': (summary or {}).get('source_scope_breakdown', {}).get('allocations', {}),
                'summary_escalation_status': (summary or {}).get('escalation_status', {}),
            })

            case['pass'] = bool(
                case['run_http'] == 200
                and str(case['run_status']).lower() == 'completed'
                and case['preview_quantity_mode'] == 'stock_aware'
                and case['preview_row_count'] > 0
            )
        except Exception as exc:
            case.update({
                'preview_ok': False,
                'apply_ok': False,
                'run_http': None,
                'run_status': 'failed',
                'error': str(exc),
                'pass': False,
            })

        results.append(case)

    passed = sum(1 for r in results if r.get('pass'))
    failed = len(results) - passed

    report = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'cases': len(results),
        'passed': passed,
        'failed': failed,
        'pass_rate': (passed / len(results)) if results else 0.0,
        'results': results,
    }

    out_json = Path('RANDOMIZER_SWEEP_15_CASE_REPORT_2026-03-04.json')
    out_md = Path('RANDOMIZER_SWEEP_15_CASE_REPORT_2026-03-04.md')
    out_json.write_text(json.dumps(report, indent=2), encoding='utf-8')

    lines = [
        '# Randomizer 15-Case Sweep Report (2026-03-04)',
        '',
        f"- Cases: {report['cases']}",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        f"- Pass rate: {report['pass_rate']:.2%}",
        '',
        '| Case | Scenario | Run | Preset | HTTP | Status | Rows | Mode | StockBacked | ZeroStock | ServiceRatio | Pass |',
        '|---:|---:|---:|---|---:|---|---:|---|---:|---:|---:|---|',
    ]
    for r in results:
        lines.append(
            f"| {r.get('case')} | {r.get('scenario_id')} | {r.get('run_id') or '-'} | {r.get('preset')} | {r.get('run_http') or '-'} | {r.get('run_status')} | {r.get('preview_row_count') or 0} | {r.get('preview_quantity_mode') or '-'} | {r.get('preview_stock_backed_rows') or 0} | {r.get('preview_zero_stock_rows') or 0} | {float(r.get('summary_service_ratio') or 0.0):.4f} | {'PASS' if r.get('pass') else 'FAIL'} |"
        )

    out_md.write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'json_report': str(out_json.resolve()), 'md_report': str(out_md.resolve()), 'passed': passed, 'failed': failed}, indent=2))


if __name__ == '__main__':
    main()
