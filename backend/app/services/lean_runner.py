from __future__ import annotations

import csv
import json
import os
import subprocess
import zipfile
import time
from datetime import datetime
from datetime import date as date_type
from pathlib import Path

from app.core.config import settings
from app.db import SessionLocal
from app.models import BacktestRun, Report
from app.services.audit_log import record_audit


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_price_policy(value: str | None) -> str | None:
    if not value:
        return None
    key = str(value).strip().lower()
    if not key:
        return None
    if key in {"adjusted", "adjusted_only", "adjusted_prefer"}:
        return "adjusted_only"
    if key in {"raw", "raw_only"}:
        return "raw_only"
    return key


def _resolve_price_policy(params: dict[str, object]) -> str | None:
    for key in ("price_source_policy", "price_policy", "price_mode", "corporate_action_policy"):
        if isinstance(params.get(key), str):
            policy = _normalize_price_policy(params[key])
            if policy:
                return policy
    weights_path = os.environ.get("WEIGHTS_CONFIG_PATH")
    if not weights_path:
        candidate = _project_root() / "configs" / "portfolio_weights.json"
        if candidate.exists():
            weights_path = str(candidate)
    if weights_path:
        try:
            cfg = json.loads(Path(weights_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
        if isinstance(cfg, dict):
            policy = _normalize_price_policy(cfg.get("price_source_policy"))
            if policy:
                return policy
            policy = _normalize_price_policy(cfg.get("corporate_action_policy"))
            if policy:
                return policy
    return None


def _resolve_ml_python() -> str:
    if settings.ml_python_path:
        return settings.ml_python_path
    candidate = _project_root() / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return "python3"


def _resolve_launcher_dll(launcher_path: str) -> str | None:
    if settings.lean_launcher_dll:
        candidate = Path(settings.lean_launcher_dll)
        if candidate.exists():
            return str(candidate)
    if not launcher_path:
        return None
    candidate = Path(launcher_path)
    if candidate.suffix.lower() == ".dll" and candidate.exists():
        return str(candidate)
    if candidate.suffix.lower() == ".csproj":
        base = candidate.parent
        direct = [
            base / "bin" / "Debug" / "QuantConnect.Lean.Launcher.dll",
            base / "bin" / "Release" / "QuantConnect.Lean.Launcher.dll",
        ]
        for dll in direct:
            if dll.exists():
                return str(dll)
        for dll in base.glob("bin/*/QuantConnect.Lean.Launcher.dll"):
            if dll.exists():
                return str(dll)
    return None


def _read_score_symbols(score_path: str) -> set[str]:
    path = Path(score_path)
    if not path.exists():
        return set()
    symbols: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if symbol:
                symbols.add(symbol)
    return symbols


def _append_scores(score_path: str, extra_path: Path) -> None:
    if not extra_path.exists():
        return
    if not Path(score_path).exists():
        Path(score_path).write_text(extra_path.read_text(encoding="utf-8"), encoding="utf-8")
        return
    with extra_path.open("r", encoding="utf-8") as src, open(
        score_path, "a", encoding="utf-8"
    ) as dst:
        header = src.readline()
        if header and not header.endswith("\n"):
            dst.write("\n")
        for line in src:
            if line.strip():
                dst.write(line if line.endswith("\n") else f"{line}\n")


def _parse_symbols(raw: str) -> list[str]:
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _fill_missing_scores(
    missing: list[str],
    score_csv_path: str,
    data_root: str,
    output_dir: Path,
    log_path: Path,
) -> tuple[list[str], str | None]:
    if not missing:
        return missing, None
    ml_root = _project_root() / "ml"
    ml_config_path = ml_root / "config.json"
    ml_script = ml_root / "predict_torch.py"
    if not ml_config_path.exists() or not ml_script.exists():
        return missing, "ml_config_or_script_missing"
    if not data_root:
        return missing, "data_root_missing"

    tmp_config = output_dir / "scores_missing_config.json"
    tmp_output = output_dir / "scores_missing.csv"
    config = json.loads(ml_config_path.read_text(encoding="utf-8"))
    config["symbols"] = missing
    tmp_config.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = [
        _resolve_ml_python(),
        str(ml_script),
        "--config",
        str(tmp_config),
        "--data-root",
        data_root,
        "--output",
        str(tmp_output),
        "--device",
        "auto",
    ]
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[score-fill] running: {' '.join(cmd)}\n")
        proc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, check=False)
        handle.write(f"[score-fill] exit={proc.returncode}\n")
    if proc.returncode != 0:
        return missing, f"score_fill_failed:{proc.returncode}"
    _append_scores(score_csv_path, tmp_output)
    remaining = sorted(set(missing) - _read_score_symbols(score_csv_path))
    return remaining, None


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


def _format_metric_value(value: object) -> str:
    if value is None:
        return "-"
    num, unit = _parse_metric_value(value)
    if unit == "none":
        return str(value)
    return _format_number(num, unit)


def _parse_iso_date(value: str | None) -> date_type | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1]
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


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
    portfolio_metrics: dict,
    benchmark_metrics: dict,
    benchmark_symbol: str | None,
    output_dir: Path,
    risk_summary: dict,
    cost_summary: dict,
    params: dict,
    data_notes: str | None,
    missing_scores: list[str] | None,
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
    ]
    if benchmark_metrics:
        lines.append("<table>")
        lines.append(
            "<tr><th>指标</th><th>组合</th><th>基准"
            + (f"（{benchmark_symbol}）" if benchmark_symbol else "")
            + "</th></tr>"
        )
        metric_keys = [
            "Compounding Annual Return",
            "Drawdown",
            "Sharpe Ratio",
            "Net Profit",
            "Portfolio Turnover",
            "Total Fees",
        ]
        for key in metric_keys:
            if key not in portfolio_metrics and key not in benchmark_metrics:
                continue
            lines.append(
                "<tr>"
                f"<th>{key}</th>"
                f"<td>{_format_metric_value(portfolio_metrics.get(key))}</td>"
                f"<td>{_format_metric_value(benchmark_metrics.get(key))}</td>"
                "</tr>"
            )
        lines.append("</table>")
    else:
        lines.append("<table>")
        for key, value in portfolio_metrics.items():
            lines.append(f"<tr><th>{key}</th><td>{_format_metric_value(value)}</td></tr>")
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
        if missing_scores:
            lines.append(
                "<tr><th>缺失清单</th><td>"
                + ", ".join(missing_scores)
                + "</td></tr>"
            )
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


def _coerce_perf_value(perf: dict, keys: list[str]) -> object | None:
    for key in keys:
        if key in perf:
            return perf.get(key)
    return None


def _map_perf_stats(perf: dict) -> dict:
    if not perf:
        return {}
    mapping = {
        "Compounding Annual Return": ["compoundingAnnualReturn", "compounding_annual_return"],
        "Drawdown": ["drawdown"],
        "Sharpe Ratio": ["sharpeRatio", "sharpe_ratio"],
        "Net Profit": ["totalNetProfit", "netProfit", "total_net_profit"],
        "Portfolio Turnover": ["portfolioTurnover", "portfolio_turnover"],
        "Total Fees": ["totalFees", "total_fees"],
        "Start Equity": ["startEquity", "start_equity"],
    }
    out: dict[str, object] = {}
    for label, keys in mapping.items():
        value = _coerce_perf_value(perf, keys)
        if value is not None:
            out[label] = value
    return out


def _extract_portfolio_metrics(summary: dict) -> dict:
    metrics = summary.get("statistics") or {}
    runtime_stats = summary.get("runtimeStatistics") or summary.get("runtime_statistics") or {}
    if metrics:
        merged = dict(metrics)
        if isinstance(runtime_stats, dict):
            merged.update(runtime_stats)
        return merged
    total_perf = summary.get("totalPerformance") or summary.get("total_performance") or {}
    perf = total_perf.get("portfolioStatistics") or total_perf.get("portfolio_statistics") or {}
    merged = _map_perf_stats(perf)
    if isinstance(runtime_stats, dict):
        merged.update(runtime_stats)
    return merged


def _extract_benchmark_metrics(summary: dict) -> dict:
    total_perf = summary.get("totalPerformance") or summary.get("total_performance") or {}
    bench = (
        total_perf.get("benchmark")
        or total_perf.get("benchmarkStatistics")
        or summary.get("benchmark")
        or summary.get("benchmarkStatistics")
        or {}
    )
    if not isinstance(bench, dict):
        return {}
    return _map_perf_stats(bench)


def _extract_benchmark_series(result_payload: dict) -> list[tuple[int, float]]:
    charts = result_payload.get("Charts") or result_payload.get("charts") or {}
    chart = charts.get("Benchmark") or charts.get("benchmark")
    if not isinstance(chart, dict):
        return []
    series_map = chart.get("series") or chart.get("Series") or {}
    series = (
        series_map.get("Benchmark")
        or series_map.get("benchmark")
        or next(iter(series_map.values()), None)
    )
    if not isinstance(series, dict):
        return []
    values = series.get("values") or series.get("Values") or []
    cleaned: list[tuple[int, float]] = []
    for item in values:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            ts = int(item[0])
            val = float(item[1])
        except (TypeError, ValueError):
            continue
        cleaned.append((ts, val))
    return cleaned


def _compute_benchmark_metrics_from_series(values: list[tuple[int, float]]) -> dict:
    if len(values) < 2:
        return {}
    start_ts, start_val = values[0]
    end_ts, end_val = values[-1]
    if start_val <= 0:
        return {}
    net_profit = end_val / start_val - 1.0
    years = (end_ts - start_ts) / (365.25 * 24 * 3600)
    cagr = (end_val / start_val) ** (1 / years) - 1.0 if years > 0 else None

    peak = start_val
    max_dd = 0.0
    returns: list[float] = []
    prev = start_val
    for _, val in values[1:]:
        if val > peak:
            peak = val
        if peak > 0:
            drawdown = (peak - val) / peak
            if drawdown > max_dd:
                max_dd = drawdown
        if prev > 0:
            returns.append(val / prev - 1.0)
        prev = val

    sharpe = None
    if returns:
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        if variance > 0:
            sharpe = (mean / variance ** 0.5) * (252 ** 0.5)

    metrics: dict[str, object] = {
        "Compounding Annual Return": _format_percent(cagr) if cagr is not None else "-",
        "Drawdown": _format_percent(max_dd),
        "Net Profit": _format_percent(net_profit),
        "Start Equity": f"{start_val:.2f}",
        "End Equity": f"{end_val:.2f}",
    }
    if sharpe is not None:
        metrics["Sharpe Ratio"] = f"{sharpe:.3f}"
    return metrics


def _compute_benchmark_metrics_from_lean_data(
    symbol: str,
    data_folder: str,
    start_date: date_type | None,
    end_date: date_type | None,
) -> dict:
    if not symbol or not data_folder:
        return {}
    path = Path(data_folder) / "equity" / "usa" / "daily" / f"{symbol.lower()}.zip"
    if not path.exists():
        return {}
    closes: list[float] = []
    dates: list[date_type] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if not names:
                return {}
            target = f"{symbol.lower()}.csv"
            name = target if target in names else names[0]
            with zf.open(name) as handle:
                for raw in handle:
                    try:
                        line = raw.decode("utf-8").strip()
                    except UnicodeDecodeError:
                        line = raw.decode("latin-1").strip()
                    if not line:
                        continue
                    parts = line.split(",")
                    if len(parts) < 5:
                        continue
                    date_str = parts[0].split()[0]
                    try:
                        row_date = datetime.strptime(date_str, "%Y%m%d").date()
                        close_val = float(parts[4])
                    except (ValueError, IndexError):
                        continue
                    if start_date and row_date < start_date:
                        continue
                    if end_date and row_date > end_date:
                        continue
                    dates.append(row_date)
                    closes.append(close_val)
    except (OSError, zipfile.BadZipFile):
        return {}

    if len(closes) < 2:
        return {}
    start_val = closes[0]
    end_val = closes[-1]
    if start_val <= 0:
        return {}
    net_profit = end_val / start_val - 1.0
    years = (dates[-1] - dates[0]).days / 365.25 if dates[-1] > dates[0] else 0
    cagr = (end_val / start_val) ** (1 / years) - 1.0 if years > 0 else None

    peak = start_val
    max_dd = 0.0
    returns: list[float] = []
    prev = start_val
    for val in closes[1:]:
        if val > peak:
            peak = val
        if peak > 0:
            drawdown = (peak - val) / peak
            if drawdown > max_dd:
                max_dd = drawdown
        if prev > 0:
            returns.append(val / prev - 1.0)
        prev = val

    sharpe = None
    if returns:
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        if variance > 0:
            sharpe = (mean / variance ** 0.5) * (252 ** 0.5)

    metrics: dict[str, object] = {
        "Compounding Annual Return": _format_percent(cagr) if cagr is not None else "-",
        "Drawdown": _format_percent(max_dd),
        "Net Profit": _format_percent(net_profit),
        "Start Equity": f"{start_val:.2f}",
        "End Equity": f"{end_val:.2f}",
    }
    if sharpe is not None:
        metrics["Sharpe Ratio"] = f"{sharpe:.3f}"
    return metrics


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
        price_policy = _resolve_price_policy(params)
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

        missing_scores: list[str] = []
        score_csv_path = ""
        raw_symbols = algo_params.get("symbols")
        if isinstance(algo_params.get("score_csv_path"), str):
            score_csv_path = algo_params["score_csv_path"]
        elif isinstance(params.get("score_csv_path"), str):
            score_csv_path = params["score_csv_path"]
        benchmark_symbol = str(params.get("benchmark") or algo_params.get("benchmark") or "").strip().upper()
        if score_csv_path and isinstance(raw_symbols, str) and raw_symbols.strip():
            symbols = _parse_symbols(raw_symbols)
            missing_scores = sorted(set(symbols) - _read_score_symbols(score_csv_path))
            if missing_scores:
                missing_scores, _ = _fill_missing_scores(
                    missing_scores,
                    score_csv_path,
                    settings.data_root or "",
                    output_dir,
                    log_path,
                )
            if missing_scores:
                filtered = [
                    symbol
                    for symbol in symbols
                    if symbol not in missing_scores or symbol == benchmark_symbol
                ]
                if not filtered and benchmark_symbol:
                    filtered = [benchmark_symbol]
                if filtered:
                    algo_params["symbols"] = ",".join(filtered)

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
                launcher_dir = Path(settings.lean_launcher_path or settings.lean_launcher_dll).parent
                algo_path = str(launcher_dir / "bin" / "Debug" / "QuantConnect.Algorithm.CSharp.dll")
            config["algorithm-location"] = algo_path
            if algo_type:
                config["algorithm-type-name"] = algo_type

        data_folder_override = None
        if isinstance(params.get("data_folder"), str) and params["data_folder"].strip():
            data_folder_override = params["data_folder"].strip()
        default_data_folder = settings.lean_data_folder
        if settings.data_root:
            adjusted_root = Path(settings.data_root) / "lean_adjusted"
            raw_root = Path(settings.data_root) / "lean"
            if price_policy == "raw_only":
                if not default_data_folder or "adjusted" in default_data_folder.lower():
                    if raw_root.exists():
                        default_data_folder = str(raw_root)
            else:
                if adjusted_root.exists():
                    default_data_folder = str(adjusted_root)
        config["data-folder"] = data_folder_override or default_data_folder
        config["results-destination-folder"] = str(lean_results_dir)

        config_path = output_dir / "lean_config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

        launcher_path = settings.lean_launcher_path
        launcher_dll = _resolve_launcher_dll(launcher_path)
        if not launcher_path and not launcher_dll:
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

        launcher_dir = Path(launcher_dll).parent if launcher_dll else Path(launcher_path).parent
        if launcher_dll:
            command = [dotnet_path, launcher_dll, "--config", str(config_path)]
        else:
            command = [
                dotnet_path,
                "run",
                "--project",
                launcher_path,
                "--",
                "--config",
                str(config_path),
            ]
        with log_path.open("w", encoding="utf-8") as handle:
            proc = subprocess.run(
                command,
                cwd=str(launcher_dir),
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
        portfolio_metrics = _extract_portfolio_metrics(summary)
        benchmark_metrics = _extract_benchmark_metrics(summary)

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

        if not benchmark_metrics and result_path:
            try:
                result_payload = json.loads(result_path.read_text(encoding="utf-8"))
                series = _extract_benchmark_series(result_payload)
                benchmark_metrics = _compute_benchmark_metrics_from_series(series)
            except (OSError, json.JSONDecodeError):
                benchmark_metrics = benchmark_metrics or {}

        benchmark_symbol = str(params.get("benchmark") or "").strip().upper()
        flat_benchmark = (
            benchmark_metrics
            and benchmark_metrics.get("Net Profit") in {"0.00%", "0%"}
            and benchmark_metrics.get("Drawdown") in {"0.00%", "0%"}
        )
        if (not benchmark_metrics or flat_benchmark) and benchmark_symbol:
            algo_config = summary.get("algorithmConfiguration") or {}
            start_date = _parse_iso_date(algo_config.get("startDate"))
            end_date = _parse_iso_date(algo_config.get("endDate"))
            data_folder_used = str(config.get("data-folder") or "")
            fallback_metrics = _compute_benchmark_metrics_from_lean_data(
                benchmark_symbol,
                data_folder_used,
                start_date,
                end_date,
            )
            if fallback_metrics:
                benchmark_metrics = fallback_metrics

        metrics = dict(portfolio_metrics)
        if benchmark_metrics:
            metrics["benchmark"] = benchmark_metrics
        if missing_scores:
            metrics["Missing Scores"] = ",".join(missing_scores)
            metrics["Missing Score Count"] = len(missing_scores)

        price_mode = "raw"
        if isinstance(config.get("data-folder"), str):
            data_folder_value = config["data-folder"].lower()
            if "lean_adjusted" in data_folder_value or "adjusted" in data_folder_value:
                price_mode = "adjusted"
        if not price_policy:
            if price_mode == "adjusted":
                price_policy = "adjusted_only"
            elif price_mode == "raw":
                price_policy = "raw_only"
        metrics["Price Mode"] = price_mode
        metrics["Benchmark Price Mode"] = price_mode
        if price_policy:
            metrics["Price Policy"] = price_policy

        turnover_week_val, _ = _parse_metric_value(metrics.get("Turnover_week"))
        turnover_week_last_val, _ = _parse_metric_value(metrics.get("Turnover_week_last"))
        portfolio_turnover_val, _ = _parse_metric_value(metrics.get("Portfolio Turnover"))
        turnover_week_annualized = None
        turnover_sanity_ratio = None
        if turnover_week_val is not None:
            turnover_week_annualized = turnover_week_val * 52
            metrics["Turnover_week_annualized"] = _format_percent(turnover_week_annualized)
        if (
            portfolio_turnover_val is not None
            and turnover_week_val is not None
            and turnover_week_val > 0
        ):
            turnover_sanity_ratio = portfolio_turnover_val / turnover_week_val
            metrics["Turnover_sanity_ratio"] = f"{turnover_sanity_ratio:.2f}"

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
        if turnover_week_val is not None:
            cost_summary["周度换手率(均值)"] = _format_percent(turnover_week_val)
        if turnover_week_last_val is not None:
            cost_summary["周度换手率(最新)"] = _format_percent(turnover_week_last_val)
        if turnover_week_annualized is not None:
            cost_summary["周度换手率年化(估算)"] = _format_percent(turnover_week_annualized)
        if turnover_sanity_ratio is not None:
            cost_summary["换手率对照(组合/周度均值)"] = f"{turnover_sanity_ratio:.2f}x"
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
        if price_policy == "adjusted_only":
            data_notes = f"{data_notes} 回测使用复权价，分红/拆分已计入价格。"
        elif price_policy == "raw_only":
            data_notes = f"{data_notes} 回测使用原始价，分红/拆分需结合公司行为文件。"
        if data_folder_override:
            tag = "复权版" if "lean_adjusted" in data_folder_override else "原始数据"
            data_notes = f"{data_notes} 数据目录：{data_folder_override}（{tag}）。"
        report_path = _write_report(
            run_id,
            portfolio_metrics,
            benchmark_metrics,
            str(params.get("benchmark") or ""),
            output_dir,
            risk_summary,
            cost_summary,
            params,
            data_notes,
            missing_scores,
        )

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
