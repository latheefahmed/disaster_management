import subprocess
import sys
from pathlib import Path
from app.config import (
    CORE_ENGINE_ROOT,
    PHASE8_HORIZON,
    PHASE8_ENABLE_ROLLING,
    PHASE8_WEIGHT_UNMET,
    PHASE8_WEIGHT_HOLD,
    PHASE8_WEIGHT_SHIP,
    PHASE8_SOLVER_TIMEOUT_SEC,
)


def run_solver(
    demand_override_path=None,
    district_stock_override_path=None,
    state_stock_override_path=None,
    national_stock_override_path=None,
    current_time=None,
    horizon_override: int | None = None,
):
    """
    Launch CBC solver with optional override CSVs.
    This version prints FULL stdout/stderr for debugging.
    """

    script = CORE_ENGINE_ROOT / "phase4" / "optimization" / "just_runs_cbc.py"

    cmd = [sys.executable, str(script)]

    if demand_override_path:
        cmd += ["--demand", str(Path(demand_override_path).resolve())]

    if district_stock_override_path:
        cmd += ["--district-stock", str(Path(district_stock_override_path).resolve())]

    if state_stock_override_path:
        cmd += ["--state-stock", str(Path(state_stock_override_path).resolve())]

    if national_stock_override_path:
        cmd += ["--national-stock", str(Path(national_stock_override_path).resolve())]

    effective_horizon = max(1, int(horizon_override if horizon_override is not None else PHASE8_HORIZON))
    cmd += ["--horizon", str(effective_horizon)]
    cmd += ["--w-unmet", str(float(PHASE8_WEIGHT_UNMET))]
    cmd += ["--w-hold", str(float(PHASE8_WEIGHT_HOLD))]
    cmd += ["--w-ship", str(float(PHASE8_WEIGHT_SHIP))]
    cmd += ["--cbc-time-limit", str(max(30, int(PHASE8_SOLVER_TIMEOUT_SEC)))]

    if PHASE8_ENABLE_ROLLING:
        cmd += ["--rolling"]

    if current_time is not None:
        cmd += ["--current-time", str(int(current_time))]

    print("=== RUNNING SOLVER ===")
    print("Command:", " ".join(cmd))
    print("======================")

    result = subprocess.run(
        cmd,
        cwd=str(CORE_ENGINE_ROOT),
        capture_output=True,
        text=True,
    )

    print("=== SOLVER STDOUT ===")
    print(result.stdout)

    print("=== SOLVER STDERR ===")
    print(result.stderr)

    if result.returncode != 0:
        stdout_tail = (result.stdout or "")[-1200:].strip()
        stderr_tail = (result.stderr or "")[-1200:].strip()
        raise RuntimeError(
            f"Solver execution failed (code {result.returncode}); "
            f"stderr_tail={stderr_tail or 'none'}; "
            f"stdout_tail={stdout_tail or 'none'}"
        )
