from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.db import SessionLocal
from app.models import BacktestRun, Report
from app.services.audit_log import record_audit


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _parse_metric_value(value: object) -> tuple[float | None, str]:
    if value is None:
        return None, "none"
    if isinstance(value, (int, float)):
        return float(value), "number"
    if not isinstance(value, str):
        return None, "none"
    raw = value.strip()
    if not raw:
        return None, "none"
    unit = "number"
    if raw.endswith("%"):
        unit = "percent"
        raw = raw[:-1]
    if raw.startswith("$"):
        unit = "currency"
        raw = raw[1:]
    raw = raw.replace(",", "")
    try:
        num = float(raw)
    except ValueError:
        return None, "none"
    if unit == "percent":
        return num / 100.0, unit
    return num, unit


def _format_percent(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def _format_number(value: float | None, unit: str) -> str:
    if value is None:
        return "-"
    if unit == "currency":
        return f"${value:,.2f}"
    if unit == "percent":
        return _format_percent(value)
    return f"{value:.4f}"


def _evaluate_risk(metrics: dict, risk_params: dict) -> tuple[str, list[str]]:
    warnings: list[str] = []
    status = "pass"

    drawdown_val, drawdown_unit = _parse_metric_value(metrics.get("Drawdown"))
    if drawdown_unit == "percent" and drawdown_val is not None:
        max_dd = risk_params.get("max_drawdown")
        if isinstance(max_dd, (int, float)) and drawdown_val > float(max_dd):
            warnings.append(f"回撤超限：{_format_percent(drawdown_val)} > {max_dd:.2%}")

    sharpe_val, _ = _parse_metric_value(metrics.get("Sharpe Ratio"))
    min_sharpe = risk_params.get("min_sharpe")
    if isinstance(min_sharpe, (int, float)) and sharpe_val is not None:
        if sharpe_val < float(min_sharpe):
            warnings.append(f"夏普不足：{sharpe_val:.3f} < {float(min_sharpe):.3f}")

    turnover_val, turnover_unit = _parse_metric_value(metrics.get("Portfolio Turnover"))
    max_turnover = risk_params.get("max_turnover")
    if isinstance(max_turnover, (int, float)) and turnover_val is not None:
        turnover_value = turnover_val if turnover_unit != "percent" else turnover_val
        if turnover_value > float(max_turnover):
            warnings.append("换手超限")

    fees_val, fees_unit = _parse_metric_value(metrics.get("Total Fees"))
    max_fees = risk_params.get("max_total_fees")
    if isinstance(max_fees, (int, float)) and fees_val is not None:
        if fees_unit == "currency" and fees_val > float(max_fees):
            warnings.append(f"费用超限：${fees_val:,.2f} > ${float(max_fees):,.2f}")

    if warnings:
        status = "warn"
    return status, warnings


def _write_report(
    run_id: int,
    metrics: dict,
    output_dir: Path,
    risk_summary: dict,
    cost_summary: dict,
    params: dict,
    data_notes: str | None,
) -> Path:
    report_path = output_dir / "report.html"
    lines = [
        "<!doctype html>",
        "<html lang=\"zh\">",
        "<head>",
        "<meta charset=\"utf-8\" />",
        "<title>回测报告</title>",
        "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;line-height:1.6;color:#222;}table{border-collapse:collapse;}th,td{border:1px solid #ddd;padding:6px 10px;text-align:left;}th{background:#f5f5f5;}</style>",
        "</head>",
        "<body>",
        f"<h1>回测报告 #{run_id}</h1>",
        "<h2>核心指标</h2>",
        "<table>",
    ]
    for key, value in metrics.items():
        lines.append(f"<tr><th>{key}</th><td>{value}</td></tr>")
    lines.append("</table>")

    if risk_summary or cost_summary or params or data_notes:
        lines.append("<h2>成本与风控</h2>")
        lines.append("<table>")
        if cost_summary:
            for key, value in cost_summary.items():
                lines.append(f"<tr><th>{key}</th><td>{value}</td></tr>")
        if risk_summary:
            for key, value in risk_summary.items():
                lines.append(f"<tr><th>{key}</th><td>{value}</td></tr>")
        if data_notes:
            lines.append(f"<tr><th>公司行为风险</th><td>{data_notes}</td></tr>")
        if params:
            lines.append(
                "<tr><th>参数</th><td><pre>"
                + json.dumps(params, ensure_ascii=False, indent=2)
                + "</pre></td></tr>"
            )
        lines.append("</table>")

    lines.extend(["</body>", "</html>"])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _load_config(template_path: str) -> dict:
    if template_path and Path(template_path).exists():
        return json.loads(Path(template_path).read_text(encoding="utf-8"))
    return {
        "environment": "backtesting",
        "algorithm-language": "Python",
        "data-folder": "",
        "log-handler": "QuantConnect.Logging.CompositeLogHandler",
        "messaging-handler": "QuantConnect.Messaging.Messaging",
        "job-queue-handler": "QuantConnect.Queues.JobQueue",
        "api-handler": "QuantConnect.Api.Api",
        "map-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskMapFileProvider",
        "factor-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskFactorFileProvider",
        "data-provider": "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider",
        "data-aggregator": "QuantConnect.Lean.Engine.DataFeeds.AggregationManager",
        "symbol-minute-limit": 10000,
        "symbol-second-limit": 10000,
        "symbol-tick-limit": 10000,
        "show-missing-data-logs": False,
        "force-exchange-always-open": False,
        "results-destination-folder": "",
        "environments": {
            "backtesting": {
                "live-mode": False,
                "setup-handler": "QuantConnect.Lean.Engine.Setup.BacktestingSetupHandler",
                "result-handler": "QuantConnect.Lean.Engine.Results.BacktestingResultHandler",
                "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.FileSystemDataFeed",
                "real-time-handler": "QuantConnect.Lean.Engine.RealTime.BacktestingRealTimeHandler",
                "history-provider": [
                    "QuantConnect.Lean.Engine.HistoricalData.SubscriptionDataReaderHistoryProvider"
                ],
                "transaction-handler": "QuantConnect.Lean.Engine.TransactionHandlers.BacktestingTransactionHandler",
            }
        },
    }


def _extract_metrics(summary: dict) -> dict:
    metrics = summary.get("statistics") or {}
    if metrics:
        return metrics
    perf = summary.get("totalPerformance", {}).get("portfolioStatistics", {})
    if not perf:
        return {}
    return {
        "Compounding Annual Return": perf.get("compoundingAnnualReturn"),
        "Drawdown": perf.get("drawdown"),
        "Sharpe Ratio": perf.get("sharpeRatio"),
        "Net Profit": perf.get("totalNetProfit"),
        "Portfolio Turnover": perf.get("portfolioTurnover"),
    }


def run_backtest(run_id: int) -> None:
    session = SessionLocal()
    try:
        run = session.get(BacktestRun, run_id)
        if not run:
            return

        run.status = "running"
        run.started_at = datetime.utcnow()
        session.commit()

        output_dir = Path(settings.artifact_root) / f"run_{run_id}"
        _ensure_dir(output_dir)
        log_path = output_dir / "lean_run.log"
        lean_results_dir = output_dir / "lean_results"
        _ensure_dir(lean_results_dir)

        config = _load_config(settings.lean_config_template)
        params = run.params if isinstance(run.params, dict) else {}
        algo_language = (params.get("algorithm_language") or "Python").strip()
        config["algorithm-language"] = algo_language
        algo_path = params.get("algorithm_path") or params.get("algorithm")
        algo_type = params.get("algorithm_type_name")

        algo_params: dict[str, str] = {}
        if isinstance(params.get("algorithm_parameters"), dict):
            algo_params.update(
                {str(k): str(v) for k, v in params["algorithm_parameters"].items()}
            )
        if isinstance(params.get("costs"), dict):
            for key in ("fee_bps", "slippage_open_bps", "slippage_close_bps"):
                if key in params["costs"]:
                    algo_params[key] = str(params["costs"][key])
        if algo_params:
            config["parameters"] = algo_params

        if algo_language.lower() == "python":
            if not algo_path:
                algo_path = settings.lean_algorithm_path
            if not algo_path:
                raise RuntimeError("Lean algorithm path is not configured.")
            config["algorithm-location"] = algo_path
            if settings.lean_python_venv:
                config["python-venv"] = settings.lean_python_venv
        else:
            if not algo_path:
                launcher_dir = Path(settings.lean_launcher_path).parent
                algo_path = str(launcher_dir / "bin" / "Debug" / "QuantConnect.Algorithm.CSharp.dll")
            config["algorithm-location"] = algo_path
            if algo_type:
                config["algorithm-type-name"] = algo_type

        data_folder_override = None
        if isinstance(params.get("data_folder"), str) and params["data_folder"].strip():
            data_folder_override = params["data_folder"].strip()
        config["data-folder"] = data_folder_override or settings.lean_data_folder
        config["results-destination-folder"] = str(lean_results_dir)

        config_path = output_dir / "lean_config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

        launcher_path = settings.lean_launcher_path
        if not launcher_path:
            raise RuntimeError("Lean launcher path is not configured.")
        dotnet_path = settings.dotnet_path or "dotnet"
        env = os.environ.copy()
        if settings.dotnet_root:
            env["DOTNET_ROOT"] = settings.dotnet_root
            env["PATH"] = f"{settings.dotnet_root}:{env.get('PATH', '')}"
        if settings.python_dll:
            env["PYTHONNET_PYDLL"] = settings.python_dll
        if settings.lean_python_venv:
            env["PYTHONHOME"] = settings.lean_python_venv

        with log_path.open("w", encoding="utf-8") as handle:
            proc = subprocess.run(
                [
                    dotnet_path,
                    "run",
                    "--project",
                    launcher_path,
                    "--",
                    "--config",
                    str(config_path),
                ],
                cwd=str(Path(launcher_path).parent),
                stdout=handle,
                stderr=subprocess.STDOUT,
                env=env,
                check=False,
            )
        if proc.returncode != 0:
            raise RuntimeError(f"Lean backtest failed (code={proc.returncode}).")

        summary_candidates = list(lean_results_dir.glob("*-summary.json"))
        if not summary_candidates:
            summary_candidates = list(lean_results_dir.glob("*summary.json"))
        summary_path = summary_candidates[0] if summary_candidates else None

        if not summary_path:
            raise RuntimeError("Lean summary file not found.")

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        metrics = _extract_metrics(summary)

        risk_params = params.get("risk", {}) if isinstance(params.get("risk"), dict) else {}
        risk_status, risk_warnings = _evaluate_risk(metrics, risk_params)
        if risk_status:
            metrics["Risk Status"] = risk_status
        if risk_warnings:
            metrics["Risk Warnings"] = "；".join(risk_warnings)

        total_fees_val, total_fees_unit = _parse_metric_value(metrics.get("Total Fees"))
        turnover_val, turnover_unit = _parse_metric_value(metrics.get("Portfolio Turnover"))
        start_equity_val, start_equity_unit = _parse_metric_value(metrics.get("Start Equity"))

        cost_summary: dict[str, str] = {}
        if algo_params:
            cost_summary["成本参数"] = ", ".join(f"{k}={v}" for k, v in algo_params.items())
        if total_fees_val is not None:
            cost_summary["总费用"] = _format_number(total_fees_val, total_fees_unit)
        if turnover_val is not None:
            cost_summary["换手率"] = _format_number(turnover_val, turnover_unit)
        if start_equity_val is not None and total_fees_val is not None:
            if start_equity_unit in {"currency", "number"} and total_fees_unit == "currency":
                cost_summary["费用占初始资金"] = _format_percent(
                    total_fees_val / start_equity_val
                )

        risk_summary: dict[str, str] = {}
        if risk_params:
            risk_summary["风控阈值"] = json.dumps(risk_params, ensure_ascii=False)
        if risk_warnings:
            risk_summary["风控结果"] = "；".join(risk_warnings)
        elif risk_params:
            risk_summary["风控结果"] = "通过"

        data_notes = (
            "公司行为映射依赖本地 map_files/factor_files；若缺失将导致更名、拆分处理不完整。"
        )
        if data_folder_override:
            tag = "复权版" if "lean_adjusted" in data_folder_override else "原始数据"
            data_notes = f"{data_notes} 数据目录：{data_folder_override}（{tag}）。"
        report_path = _write_report(
            run_id,
            metrics,
            output_dir,
            risk_summary,
            cost_summary,
            params,
            data_notes,
        )

        result_candidates = []
        for candidate in lean_results_dir.glob("*.json"):
            name = candidate.name
            if name.endswith("-summary.json"):
                continue
            if "order-events" in name or "data-monitor-report" in name:
                continue
            if candidate.stat().st_size == 0:
                continue
            result_candidates.append(candidate)
        result_path = max(result_candidates, key=lambda p: p.stat().st_size) if result_candidates else None

        run.metrics = metrics
        run.status = "success"
        run.ended_at = datetime.utcnow()
        session.add(
            Report(
                run_id=run_id,
                report_type="summary",
                path=str(summary_path),
            )
        )
        session.add(
            Report(
                run_id=run_id,
                report_type="html",
                path=str(report_path),
            )
        )
        if result_path:
            session.add(
                Report(
                    run_id=run_id,
                    report_type="result",
                    path=str(result_path),
                )
            )
        session.add(
            Report(
                run_id=run_id,
                report_type="log",
                path=str(log_path),
            )
        )
        record_audit(
            session,
            action="backtest.success",
            resource_type="backtest",
            resource_id=run_id,
            detail={"status": "success", "metrics": metrics},
        )
        session.commit()
    except Exception as exc:
        run = session.get(BacktestRun, run_id)
        if run:
            run.status = "failed"
            run.metrics = {"error": str(exc)}
            run.ended_at = datetime.utcnow()
            record_audit(
                session,
                action="backtest.failed",
                resource_type="backtest",
                resource_id=run_id,
                detail={"error": str(exc)},
            )
            session.commit()
    finally:
        session.close()
