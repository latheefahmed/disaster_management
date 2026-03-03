from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from app.database import SessionLocal
from app.models.meta_controller_setting import MetaControllerSetting
from app.services.neural_controller import get_params

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = REPO_ROOT / "core_engine/phase4/scenarios/generated/validation_matrix/neural_mode_matrix_snapshot.json"


@contextmanager
def _setting_guard(db):
    row = db.query(MetaControllerSetting).filter(MetaControllerSetting.id == 1).first()
    if row is None:
        row = MetaControllerSetting(id=1, mode="shadow", influence_pct=0.2, nn_enabled=1)
        db.add(row)
        db.commit()
        db.refresh(row)

    backup = {
        "mode": str(row.mode or "shadow"),
        "influence_pct": float(row.influence_pct or 0.2),
        "nn_enabled": int(row.nn_enabled or 0),
    }
    try:
        yield row
    finally:
        row.mode = backup["mode"]
        row.influence_pct = backup["influence_pct"]
        row.nn_enabled = backup["nn_enabled"]
        db.commit()


def _serialize_case(name: str, expected_source: str, out: dict, expectation_ok: bool, extra: dict | None = None) -> dict:
    payload = {
        "case": name,
        "expected_source": expected_source,
        "actual_source": str(out.get("source", "")),
        "actual_mode": str(out.get("mode", "")),
        "fallback_used": int(out.get("fallback_used", 0) or 0),
        "alpha": float(out.get("alpha", 0.0)),
        "beta": float(out.get("beta", 0.0)),
        "gamma": float(out.get("gamma", 0.0)),
        "p_mult": float(out.get("p_mult", 0.0)),
        "u_mult": float(out.get("u_mult", 0.0)),
        "passed": bool(expectation_ok),
    }
    if extra:
        payload.update(extra)
    return payload


def main() -> None:
    db = SessionLocal()
    try:
        rows: list[dict] = []

        with _setting_guard(db) as setting:
            setting.mode = "fallback"
            setting.influence_pct = 0.2
            setting.nn_enabled = 0
            db.commit()
            out = get_params(db, solver_run_id=None, context={"unmet_ratio": 0.0, "delay_ratio": 0.0})
            rows.append(
                _serialize_case(
                    "fallback_only",
                    "fallback",
                    out,
                    expectation_ok=str(out.get("source")) == "fallback",
                    extra={"toggle": "disabled"},
                )
            )

        with _setting_guard(db) as setting:
            setting.mode = "shadow"
            setting.influence_pct = 0.2
            setting.nn_enabled = 1
            db.commit()
            with patch("app.services.neural_controller.infer_raw_params", return_value={
                "alpha": 0.9,
                "beta": 0.8,
                "gamma": 1.1,
                "p_mult": 1.2,
                "u_mult": 1.1,
            }):
                out = get_params(db, solver_run_id=None, context={"unmet_ratio": 0.1, "delay_ratio": 0.1})
            rows.append(
                _serialize_case(
                    "shadow",
                    "fallback",
                    out,
                    expectation_ok=str(out.get("source")) == "fallback",
                    extra={"toggle": "enabled"},
                )
            )

        with _setting_guard(db) as setting:
            setting.mode = "blended"
            setting.influence_pct = 0.2
            setting.nn_enabled = 1
            db.commit()
            with patch("app.services.neural_controller.infer_raw_params", return_value={
                "alpha": 0.7,
                "beta": 0.55,
                "gamma": 1.0,
                "p_mult": 1.05,
                "u_mult": 1.03,
            }):
                out = get_params(db, solver_run_id=None, context={"unmet_ratio": 0.2, "delay_ratio": 0.2})
            rows.append(
                _serialize_case(
                    "blended_20pct",
                    "neural_blend",
                    out,
                    expectation_ok=str(out.get("source")) == "neural_blend" and str(out.get("mode")) == "blended",
                    extra={"influence_pct": 0.2},
                )
            )

        with _setting_guard(db) as setting:
            setting.mode = "blended"
            setting.influence_pct = 0.45
            setting.nn_enabled = 1
            db.commit()
            with patch("app.services.neural_controller.infer_raw_params", return_value={
                "alpha": 0.65,
                "beta": 0.6,
                "gamma": 1.1,
                "p_mult": 1.08,
                "u_mult": 1.07,
            }):
                out = get_params(db, solver_run_id=None, context={"unmet_ratio": 0.3, "delay_ratio": 0.25})
            rows.append(
                _serialize_case(
                    "blended_45pct",
                    "neural_blend",
                    out,
                    expectation_ok=str(out.get("source")) == "neural_blend" and str(out.get("mode")) == "blended",
                    extra={"influence_pct": 0.45},
                )
            )

        with _setting_guard(db) as setting:
            setting.mode = "blended"
            setting.influence_pct = 0.2
            setting.nn_enabled = 1
            db.commit()
            with patch("app.services.neural_controller.infer_raw_params", side_effect=RuntimeError("simulated_nn_failure")):
                out = get_params(db, solver_run_id=None, context={"unmet_ratio": 0.2, "delay_ratio": 0.2})
            rows.append(
                _serialize_case(
                    "nn_failure",
                    "fallback",
                    out,
                    expectation_ok=str(out.get("source")) == "fallback",
                )
            )

        all_passed = all(bool(r.get("passed")) for r in rows)
        report = {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "cases": rows,
            "all_passed": all_passed,
        }
        ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        print(f"[ok] neural mode matrix artifact written: {ARTIFACT_PATH}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
