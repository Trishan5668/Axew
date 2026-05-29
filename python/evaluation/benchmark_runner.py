"""
Continuous benchmark runner — Phase 8.4.

Detects python/ source changes via hash and re-runs benchmarks when components change.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SRC = PROJECT_ROOT / "python"
REPORTS_DIR = Path(__file__).parent / "reports"
HASH_FILE = REPORTS_DIR / ".source_hash.json"
QUALITY_MD = PROJECT_ROOT / "python" / "evaluation" / "RETRIEVAL_QUALITY.md"

PHASES = ["baseline", "phase4", "phase5", "phase6", "phase7"]
REGRESSION_THRESHOLD = 0.05


def _hash_sources() -> str:
    h = hashlib.sha256()
    for path in sorted(PYTHON_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        h.update(path.read_bytes())
    return h.hexdigest()


def _load_previous_hash() -> Optional[str]:
    if HASH_FILE.is_file():
        try:
            return json.loads(HASH_FILE.read_text(encoding="utf-8")).get("hash")
        except Exception:
            return None
    return None


def _save_hash(h: str) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    HASH_FILE.write_text(
        json.dumps({"hash": h, "updated": datetime.now(timezone.utc).isoformat()}),
        encoding="utf-8",
    )


def _latest_report(phase: str) -> Optional[Dict[str, Any]]:
    reports = sorted(REPORTS_DIR.glob(f"{phase}_*.json"), reverse=True)
    if not reports:
        return None
    return json.loads(reports[0].read_text(encoding="utf-8"))


def _compare_metrics(prev: Dict[str, Any], curr: Dict[str, Any]) -> List[str]:
    alerts: List[str] = []
    for key in ("hit_rate_at_1", "mean_temporal_iou", "hit_rate_at_5", "mean_ndcg_at_5"):
        p = prev.get(key, 0)
        c = curr.get(key, 0)
        if p > 0 and (p - c) / p > REGRESSION_THRESHOLD:
            alerts.append(f"{key} regressed {p:.3f} -> {c:.3f} ({((p-c)/p)*100:.1f}%)")
    return alerts


def run_benchmarks(phases: Optional[List[str]] = None, force: bool = False) -> Dict[str, Any]:
    """Run benchmark suite if source hash changed (or force=True)."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    current_hash = _hash_sources()
    previous_hash = _load_previous_hash()
    changed = current_hash != previous_hash

    if not changed and not force:
        logger.info("No source changes detected — skipping benchmark run")
        return {"skipped": True, "hash": current_hash}

    from python.evaluation.benchmark import main as bench_main
    import argparse

    phases = phases or PHASES
    results: Dict[str, Any] = {}
    alerts: List[str] = []

    for phase in phases:
        logger.info("Running benchmark phase=%s", phase)
        argv = ["benchmark.py", "--phase", phase]
        # Run via subprocess-style by importing run function
        from python.evaluation import benchmark as bench_mod

        segments = bench_mod.load_fixture_segments()
        if phase == "baseline":
            fn = bench_mod.create_baseline_retriever(segments)
        elif phase == "phase4":
            fn = bench_mod.create_phase4_retriever(segments)
        elif phase == "phase5":
            fn = bench_mod.create_phase5_retriever(segments)
        elif phase == "phase6":
            fn = bench_mod.create_phase6_retriever(segments)
        elif phase == "phase7":
            fn = bench_mod.create_phase7_retriever(segments)
        else:
            continue

        report = bench_mod.evaluate_retrieval(fn, bench_mod.BENCHMARK_CASES, phase=phase)
        report_path = bench_mod.save_report(report, phase=phase)
        curr = bench_mod.report_to_dict(report)
        prev = _latest_report(phase)
        if prev and prev.get("phase") == phase:
            # Compare against second-latest if we just wrote new one
            older = sorted(REPORTS_DIR.glob(f"{phase}_*.json"), reverse=True)
            if len(older) > 1:
                try:
                    prev = json.loads(older[1].read_text(encoding="utf-8"))
                    alerts.extend(_compare_metrics(prev, curr))
                except Exception:
                    pass

        results[phase] = {
            "hit_rate_at_1": curr["hit_rate_at_1"],
            "mean_temporal_iou": curr["mean_temporal_iou"],
            "hit_rate_at_5": curr["hit_rate_at_5"],
            "report": str(report_path),
        }

    _save_hash(current_hash)
    _write_quality_md(results, alerts)
    return {"skipped": False, "hash": current_hash, "results": results, "alerts": alerts}


def _write_quality_md(results: Dict[str, Any], alerts: List[str]) -> None:
    lines = [
        "# AXEW Retrieval Quality",
        "",
        f"Updated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "| Phase | Hit@1 | Mean IoU | Hit@5 |",
        "|-------|-------|----------|-------|",
    ]
    for phase, data in results.items():
        lines.append(
            f"| {phase} | {data['hit_rate_at_1']:.1%} | {data['mean_temporal_iou']:.3f} | {data['hit_rate_at_5']:.1%} |"
        )
    if alerts:
        lines.extend(["", "## Regression Alerts", ""])
        for a in alerts:
            lines.append(f"- {a}")
    QUALITY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Continuous AXEW benchmark runner")
    parser.add_argument("--force", action="store_true", help="Run even if source unchanged")
    parser.add_argument("--phases", nargs="*", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    outcome = run_benchmarks(phases=args.phases, force=args.force)
    if outcome.get("alerts"):
        for a in outcome["alerts"]:
            logger.warning("REGRESSION: %s", a)
    print(json.dumps(outcome, indent=2))
    return 1 if outcome.get("alerts") else 0


if __name__ == "__main__":
    raise SystemExit(main())
