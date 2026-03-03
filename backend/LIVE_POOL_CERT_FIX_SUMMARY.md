# LIVE Pool Certification Fix Summary

Date: 2026-02-24

## Root Causes Identified
- Harness polled `/district/solver-status`, which returns latest completed run, not the specific triggered run.
- Harness read unmet from `/district/allocations` instead of `/district/unmet`, forcing unmet totals toward zero.
- Harness linked allocations only by `request_id`; many live allocations are persisted with `request_id=0`, so valid evidence was missed.
- Requests were sometimes created while a live run was already `running`, so those requests were not included in that run and remained `solving/queued`.
- Invariants were permissive and allowed non-terminal request states to pass.

## Fixes Implemented
- Switched solver polling to run-id-bound polling via `/district/run-history` using the exact `solver_run_id` from trigger response.
- Added idle guard before each attempt: wait until no live run is `running` before creating a new request.
- Added robust trigger run-id fallback using latest live running run if trigger response times out.
- Switched unmet retrieval to `/district/unmet` and filtered by run/resource/time.
- Added run-slot evidence fallback (run + resource + time) when request-id linkage is unavailable.
- Tightened invariants: run must be completed, request must be terminal, request must be included in run, conservation must hold, stock non-negative, and provenance valid.

## Safety/Integrity Notes
- No DB direct edits or bypasses were introduced.
- No positive-result forcing was added; certification still depends on measured outcomes.
- Manual-aid remains conditional on real unmet quantities.
