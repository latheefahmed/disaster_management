from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    source = root / "ADMIN_SCENARIO_CERT_ENRICHED_RUN_OBJECTS.json"
    target = root / "ADMIN_SCENARIO_CERT_FORENSICS.md"

    data = json.loads(source.read_text(encoding="utf-8"))
    runs = list(data.get("run_objects") or [])

    notes = Counter(n for r in runs for n in (r.get("cert_status", {}).get("notes") or []))

    lines: list[str] = []
    lines.append("# Admin Scenario Certification Forensics")
    lines.append("")
    lines.append(f"Generated: {data.get('generated_at')}")
    lines.append(
        f"Overall: {data.get('overall_status')} | Runs: {data.get('executed_runs')} | "
        f"Pass: {data.get('pass_count')} | Fail: {data.get('fail_count')}"
    )
    lines.append(f"Failure notes: {dict(notes)}")
    lines.append("")
    lines.append("## Key Counters")
    lines.append("")
    lines.append(f"- run_status_200: {sum(1 for r in runs if r.get('cert_status', {}).get('run_status') == 200)}")
    lines.append(f"- run_status_500: {sum(1 for r in runs if r.get('cert_status', {}).get('run_status') == 500)}")
    lines.append(f"- db_completed: {sum(1 for r in runs if r.get('scenario_run_db_status') == 'completed')}")
    lines.append(f"- db_failed: {sum(1 for r in runs if r.get('scenario_run_db_status') == 'failed')}")
    lines.append(f"- verify_ok_true: {sum(1 for r in runs if r.get('cert_status', {}).get('verify_ok') is True)}")
    lines.append(f"- shipments_nonzero_runs: {sum(1 for r in runs if float(r.get('shipment_rows') or 0.0) > 0.0)}")
    lines.append(
        f"- non_district_alloc_runs: {sum(1 for r in runs if float(r.get('non_district_allocation_rows') or 0.0) > 0.0)}"
    )
    lines.append("")
    lines.append("## Full Per-Run Table")
    lines.append("")
    lines.append(
        "|Cycle|Preset|Scenario|Run|Pass|RunStatus|DBStatus|SummaryStatus|Revert|Verify|Net|Debit|RevertQty|Shipments|"
        "NonDistrictAlloc|ScopeCounts(d,s,ns,n)|Notes|"
    )
    lines.append("|---:|---|---:|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")

    for r in runs:
        cs = r.get("cert_status") or {}
        scope = r.get("allocation_source_scope_counts") or {}
        scope_counts = f"{scope.get('district', 0)},{scope.get('state', 0)},{scope.get('neighbor_state', 0)},{scope.get('national', 0)}"
        notes_text = ",".join(cs.get("notes") or []) or "-"
        line = (
            f"|{r.get('cycle')}|{r.get('preset')}|{r.get('scenario_id')}|{r.get('run_id')}|"
            f"{'PASS' if cs.get('pass') else 'FAIL'}|{cs.get('run_status')}|{r.get('scenario_run_db_status')}|"
            f"{cs.get('summary_status')}|{cs.get('revert_status')}|{cs.get('verify_status')}|"
            f"{cs.get('verify_net_total')}|{cs.get('verify_debit_total')}|{cs.get('verify_revert_total')}|"
            f"{r.get('shipment_rows')}|{r.get('non_district_allocation_rows')}|{scope_counts}|{notes_text}|"
        )
        lines.append(line)

    target.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(target), "rows": len(runs)}))


if __name__ == "__main__":
    main()
