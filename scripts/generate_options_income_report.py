from __future__ import annotations

import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
for path in (ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.options_income_policy import load_options_income_thresholds
from scripts.run_options_income_matrix import MANIFEST

REPORT_BASELINE = Path("/app/stocklean/docs/reports/2026-04-07-options-income-matrix-baseline.md")
REPORT_PROXY = Path("/app/stocklean/docs/reports/2026-04-07-options-income-proxy-report.md")
REPORT_DECISION = Path("/app/stocklean/docs/reports/2026-04-07-options-income-final-decision.md")


def _parse_percent(raw: Any) -> float:
    text = str(raw or "").strip().replace("%", "")
    if not text:
        return 0.0
    return float(text) / 100.0


def _parse_money(raw: Any) -> float:
    text = str(raw or "").strip().replace("$", "").replace(",", "")
    if not text:
        return 0.0
    return float(text)


def _load_manifest() -> list[dict[str, Any]]:
    if not MANIFEST.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _summary_path(run_id: int) -> Path:
    return Path(f"/app/stocklean/artifacts/run_{run_id}/lean_results/-summary.json")


def _ulcer_index_from_equity_curve(values: list[list[float]]) -> float:
    peak = 0.0
    squares: list[float] = []
    for row in values:
        if len(row) < 2:
            continue
        equity = float(row[1])
        peak = max(peak, equity)
        if peak <= 0:
            continue
        dd_pct = max(0.0, (peak - equity) / peak) * 100.0
        squares.append(dd_pct * dd_pct)
    if not squares:
        return 0.0
    return math.sqrt(sum(squares) / len(squares))


def load_run_metrics(run_id: int) -> dict[str, Any]:
    payload = json.loads(_summary_path(run_id).read_text(encoding="utf-8"))
    statistics = payload.get("statistics") or {}
    charts = payload.get("charts") or {}
    strategy_equity = charts.get("Strategy Equity") or {}
    series = (strategy_equity.get("series") or {}).get("Equity") or {}
    values = series.get("values") or []
    return {
        "cagr": _parse_percent(statistics.get("Compounding Annual Return")),
        "sharpe": float(statistics.get("Sharpe Ratio") or 0.0),
        "max_drawdown": _parse_percent(statistics.get("Drawdown")),
        "ulcer_index": _ulcer_index_from_equity_curve(values),
        "recovery_days": int(statistics.get("Drawdown Recovery") or 0),
        "net_profit": _parse_percent(statistics.get("Net Profit")),
        "fees": _parse_money(statistics.get("Total Fees")),
    }


def evaluate_candidate(*, baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    thresholds = load_options_income_thresholds()
    reasons: list[str] = []

    drawdown_delta_pp = (float(candidate["max_drawdown"]) - float(baseline["max_drawdown"])) * 100.0
    if drawdown_delta_pp > float(thresholds["max_drawdown_delta_pp"]):
        reasons.append("max_drawdown")

    baseline_recovery = max(float(baseline["recovery_days"]), 1.0)
    recovery_delta_ratio = (
        float(candidate["recovery_days"]) - float(baseline["recovery_days"])
    ) / baseline_recovery
    if recovery_delta_ratio > float(thresholds["recovery_time_delta_ratio"]):
        reasons.append("recovery_time")

    baseline_ulcer = max(float(baseline["ulcer_index"]), 1e-9)
    ulcer_delta_ratio = (
        float(candidate["ulcer_index"]) - float(baseline["ulcer_index"])
    ) / baseline_ulcer
    if ulcer_delta_ratio > float(thresholds["ulcer_index_delta_ratio"]):
        reasons.append("ulcer_index")

    cagr_delta_pp = (float(candidate["cagr"]) - float(baseline["cagr"])) * 100.0
    sharpe_delta = float(candidate["sharpe"]) - float(baseline["sharpe"])
    passed_return = (
        cagr_delta_pp >= float(thresholds["min_cagr_delta_pp"])
        or sharpe_delta >= float(thresholds["min_sharpe_delta"])
    )

    return {
        "passed": bool(passed_return and not reasons),
        "reasons": reasons,
        "drawdown_delta_pp": drawdown_delta_pp,
        "recovery_delta_ratio": recovery_delta_ratio,
        "ulcer_delta_ratio": ulcer_delta_ratio,
        "cagr_delta_pp": cagr_delta_pp,
        "sharpe_delta": sharpe_delta,
    }


def _format_percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _format_delta_pp(value: float) -> str:
    return f"{value:.2f}pp"


def _write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    print(f"wrote {path}")


def main() -> None:
    rows = _load_manifest()
    if not rows:
        raise SystemExit(f"manifest not found or empty: {MANIFEST}")

    by_name = {row["name"]: row for row in rows}
    if "baseline" not in by_name:
        raise SystemExit("baseline row missing from manifest")

    baseline_row = by_name["baseline"]
    baseline_run_id = int(baseline_row["id"])
    baseline_metrics = load_run_metrics(baseline_run_id)

    comparisons: list[dict[str, Any]] = []
    for row in rows:
        if row["name"] == "baseline":
            continue
        run_id = int(row["id"])
        metrics = load_run_metrics(run_id)
        decision = evaluate_candidate(baseline=baseline_metrics, candidate=metrics)
        comparisons.append(
            {
                "name": row["name"],
                "group": row["group"],
                "run_id": run_id,
                "metrics": metrics,
                "decision": decision,
            }
        )

    comparisons.sort(key=lambda item: item["name"])
    passed = [item for item in comparisons if item["decision"]["passed"]]
    best = max(
        comparisons,
        key=lambda item: (
            item["decision"]["passed"],
            item["metrics"]["sharpe"],
            item["metrics"]["cagr"],
        ),
    ) if comparisons else None

    _write_report(
        REPORT_BASELINE,
        "\n".join(
            [
                "# 2026-04-07 Options Income Matrix Baseline",
                "",
                f"- baseline run: `{baseline_run_id}`",
                f"- CAGR: `{_format_percent(baseline_metrics['cagr'])}`",
                f"- MaxDD: `{_format_percent(baseline_metrics['max_drawdown'])}`",
                f"- Sharpe: `{baseline_metrics['sharpe']:.3f}`",
                f"- Ulcer Index: `{baseline_metrics['ulcer_index']:.2f}`",
                f"- Recovery Days: `{baseline_metrics['recovery_days']}`",
            ]
        ),
    )

    table_lines = [
        "# 2026-04-07 Options Income Proxy Report",
        "",
        "| Name | Group | Run | CAGR | MaxDD | Sharpe | Ulcer | Recovery | Gate | Reasons |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for item in comparisons:
        metrics = item["metrics"]
        decision = item["decision"]
        table_lines.append(
            "| {name} | {group} | {run_id} | {cagr} | {maxdd} | {sharpe:.3f} | {ulcer:.2f} | {recovery} | {gate} | {reasons} |".format(
                name=item["name"],
                group=item["group"],
                run_id=item["run_id"],
                cagr=_format_percent(metrics["cagr"]),
                maxdd=_format_percent(metrics["max_drawdown"]),
                sharpe=metrics["sharpe"],
                ulcer=metrics["ulcer_index"],
                recovery=metrics["recovery_days"],
                gate="PASS" if decision["passed"] else "FAIL",
                reasons=",".join(decision["reasons"]) or "-",
            )
        )
    _write_report(REPORT_PROXY, "\n".join(table_lines))

    decision_lines = [
        "# 2026-04-07 Options Income Final Decision",
        "",
        f"- baseline run: `{baseline_run_id}`",
        f"- candidates tested: `{len(comparisons)}`",
        f"- passed gate: `{len(passed)}`",
    ]
    if best is not None:
        decision_lines.extend(
            [
                f"- top candidate: `{best['name']}` (`run {best['run_id']}`)",
                f"- top candidate gate: `{'PASS' if best['decision']['passed'] else 'FAIL'}`",
                f"- top candidate CAGR delta: `{_format_delta_pp(best['decision']['cagr_delta_pp'])}`",
                f"- top candidate Sharpe delta: `{best['decision']['sharpe_delta']:.3f}`",
            ]
        )
    decision_lines.extend(
        [
            "",
            "## Decision",
            f"- default_path: `{'unchanged' if not passed else 'review_candidate'}`",
            f"- enter_real_options_phase: `{'true' if passed else 'false'}`",
        ]
    )
    _write_report(REPORT_DECISION, "\n".join(decision_lines))


if __name__ == "__main__":
    main()
