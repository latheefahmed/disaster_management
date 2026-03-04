import json
import random
import time
from datetime import datetime, UTC
from pathlib import Path

import requests

API = 'http://127.0.0.1:8000'
CASES = 15
PRESETS = ['high', 'extreme', 'extreme', 'high', 'extreme']


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
        horizon = 3 if idx < 5 else (4 if idx < 10 else 5)
        stress_mode = True
        district_count = random.randint(6, 12)
        resource_count = random.randint(5, 10)

        scoped_state_codes = []
        if states and idx % 3 != 0:
            pick = random.sample(states, k=min(2, len(states)))
            scoped_state_codes = [str(s.get('state_code')) for s in pick if s.get('state_code') is not None]

        scenario = req('POST', f'{API}/admin/scenarios', headers=headers, payload={'name': f'AUTO_STRESS_ESC_{idx+1}_{int(time.time())}'}, timeout=30)
        scenario_id = int(scenario['id'])

        payload = {
            'preset': preset,
            'seed': 20260304 + 100 + idx,
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
            preview = req('POST', f'{API}/admin/scenarios/{scenario_id}/randomizer/preview', headers=headers, payload=payload, timeout=120)
            _ = req('POST', f'{API}/admin/scenarios/{scenario_id}/randomizer/apply', headers=headers, payload=payload, timeout=120)
            run_resp = requests.post(f'{API}/admin/scenarios/{scenario_id}/run', headers=headers, json={'scope_mode': 'focused'}, timeout=300)
            run_resp.raise_for_status()
            runs = req('GET', f'{API}/admin/scenarios/{scenario_id}/runs', headers=headers, timeout=90)
            run_id = int(runs[0]['id']) if runs else None
            summary = req('GET', f'{API}/admin/scenarios/{scenario_id}/runs/{run_id}/summary', headers=headers, timeout=120) if run_id else {}

            totals = summary.get('totals', {}) if isinstance(summary, dict) else {}
            allocations = (summary.get('source_scope_breakdown', {}) or {}).get('allocations', {}) if isinstance(summary, dict) else {}
            escalation_status = (summary.get('escalation_status', {}) or {}) if isinstance(summary, dict) else {}

            allocated = float(totals.get('allocated_quantity') or 0.0)
            unmet = float(totals.get('unmet_quantity') or 0.0)
            demand = allocated + unmet
            service_ratio = (allocated / demand) if demand > 1e-9 else 0.0

            state_alloc = float(allocations.get('state') or 0.0)
            national_alloc = float(allocations.get('national') or 0.0)
            neighbor_alloc = float(allocations.get('neighbor') or 0.0)
            escal_events = int(escalation_status.get('events_found') or 0)
            escal_marked_state = int(escalation_status.get('state_scope_marked') or 0)
            escal_marked_national = int(escalation_status.get('national_scope_marked') or 0)
            offers_seeded = int(escalation_status.get('neighbor_offers_seeded') or 0)
            offers_accepted = int(escalation_status.get('neighbor_offers_accepted') or 0)

            escalation_happened = any([
                state_alloc > 0,
                national_alloc > 0,
                neighbor_alloc > 0,
                escal_events > 0,
                escal_marked_state > 0,
                escal_marked_national > 0,
                offers_seeded > 0,
                offers_accepted > 0,
            ])

            case.update({
                'run_http': int(run_resp.status_code),
                'run_status': (runs[0]['status'] if runs else 'unknown'),
                'run_id': run_id,
                'preview_row_count': int(preview.get('row_count') or 0),
                'preview_quantity_mode': preview.get('quantity_mode'),
                'preview_stock_backed_rows': int(preview.get('stock_backed_rows') or 0),
                'preview_zero_stock_rows': int(preview.get('zero_stock_rows') or 0),
                'service_ratio': service_ratio,
                'unmet_quantity': unmet,
                'state_alloc': state_alloc,
                'national_alloc': national_alloc,
                'neighbor_alloc': neighbor_alloc,
                'escalation_status': escalation_status,
                'escalation_happened': escalation_happened,
            })

            case['pass'] = bool(
                case['run_http'] == 200
                and str(case['run_status']).lower() == 'completed'
                and case['preview_quantity_mode'] == 'stock_aware'
                and case['preview_row_count'] > 0
            )
        except Exception as exc:
            case.update({
                'run_http': None,
                'run_status': 'failed',
                'error': str(exc),
                'escalation_happened': False,
                'pass': False,
            })

        results.append(case)

    passed = sum(1 for r in results if r.get('pass'))
    failed = len(results) - passed
    escalation_count = sum(1 for r in results if r.get('escalation_happened'))

    report = {
        'timestamp': datetime.now(UTC).isoformat(),
        'cases': len(results),
        'passed': passed,
        'failed': failed,
        'pass_rate': (passed / len(results)) if results else 0.0,
        'escalation_happened_cases': escalation_count,
        'escalation_rate': (escalation_count / len(results)) if results else 0.0,
        'results': results,
    }

    out_json = Path('RANDOMIZER_STRESS_ESCALATION_15_CASE_REPORT_2026-03-04.json')
    out_md = Path('RANDOMIZER_STRESS_ESCALATION_15_CASE_REPORT_2026-03-04.md')
    out_json.write_text(json.dumps(report, indent=2), encoding='utf-8')

    lines = [
        '# Randomizer Stress + Escalation 15-Case Report (2026-03-04)',
        '',
        f"- Cases: {report['cases']}",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        f"- Pass rate: {report['pass_rate']:.2%}",
        f"- Escalation happened in: {escalation_count}/{report['cases']} ({report['escalation_rate']:.2%})",
        '',
        '| Case | Scenario | Run | Preset | Horizon | HTTP | Status | Rows | StateAlloc | NationalAlloc | NeighborAlloc | Esc? | Unmet | ServiceRatio |',
        '|---:|---:|---:|---|---:|---:|---|---:|---:|---:|---:|---|---:|---:|',
    ]

    for r in results:
        lines.append(
            f"| {r.get('case')} | {r.get('scenario_id')} | {r.get('run_id') or '-'} | {r.get('preset')} | {r.get('horizon')} | {r.get('run_http') or '-'} | {r.get('run_status')} | {r.get('preview_row_count') or 0} | {float(r.get('state_alloc') or 0.0):.2f} | {float(r.get('national_alloc') or 0.0):.2f} | {float(r.get('neighbor_alloc') or 0.0):.2f} | {'YES' if r.get('escalation_happened') else 'NO'} | {float(r.get('unmet_quantity') or 0.0):.2f} | {float(r.get('service_ratio') or 0.0):.4f} |"
        )

    out_md.write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'json_report': str(out_json.resolve()), 'md_report': str(out_md.resolve()), 'passed': passed, 'failed': failed, 'escalation_happened_cases': escalation_count}, indent=2))


if __name__ == '__main__':
    main()
