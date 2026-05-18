# 稳健期权收益增强研究 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不引入真实期权交易链路的前提下，为 StockLean 建立一套“稳健优先”的期权收益增强代理研究框架，并产出可复用的实验矩阵、回测执行入口和决策报告。

**Architecture:** 方案分四层：研究基线配置、可测试的收益增强 sleeve 纯函数、主策略接入点、研究执行与报告生成。默认路径只研究 option-income ETF 代理，不触碰真实期权执行。收益增强 sleeve 仅允许插入 idle/defensive 路径，禁止替代主 alpha 风险仓。

**Tech Stack:** Python 3.11, FastAPI backend helpers, Lean Python algorithm (`ml_overlay_scores.py`), pytest, JSON config, Markdown reports

---

## 文件结构

- Create: `configs/research_options_income_matrix.json`
  - 定义代理资产、集成模式、研究组、门槛和默认基线。
- Create: `backend/app/services/options_income_policy.py`
  - 负责读取矩阵配置、返回默认基线、阈值和研究场景。
- Create: `algorithms/options_income_overlay.py`
  - 纯函数：根据 idle weight、mode、symbol、sleeve_weight 计算收益增强 sleeve 权重。
- Modify: `algorithms/ml_overlay_scores.py`
  - 增加收益增强 sleeve 参数并在 idle 分配阶段接入。
- Create: `backend/tests/test_options_income_policy.py`
  - 验证配置读取、默认值和场景展开。
- Create: `backend/tests/test_options_income_overlay.py`
  - 验证 idle replacement / defensive replacement 的权重计算。
- Create: `scripts/run_options_income_matrix.py`
  - 生成并提交研究矩阵回测，支持 `--dry-run` 与 `--group`。
- Create: `backend/tests/test_options_income_script_payloads.py`
  - 验证 runner 生成的回测 payload。
- Create: `scripts/generate_options_income_report.py`
  - 从回测结果生成 markdown 报告，并基于硬门槛给出 pass/fail 结论。
- Create: `backend/tests/test_options_income_report.py`
  - 验证门槛判定与报告输出。
- Create: `docs/reports/2026-04-07-options-income-matrix-baseline.md`
  - 研究基线说明。
- Create: `docs/reports/2026-04-07-options-income-proxy-report.md`
  - 代理资产研究报告。
- Create: `docs/reports/2026-04-07-options-income-final-decision.md`
  - 最终是否进入真实期权阶段的结论。

---

### Task 1: 建立研究基线配置与策略门槛

**Files:**
- Create: `configs/research_options_income_matrix.json`
- Create: `backend/app/services/options_income_policy.py`
- Test: `backend/tests/test_options_income_policy.py`

- [ ] **Step 1: 先写失败测试，锁定默认基线、场景组和硬门槛**

```python
from app.services.options_income_policy import (
    DEFAULT_OPTIONS_INCOME_BENCHMARK,
    DEFAULT_OPTIONS_INCOME_DEFENSIVE_BASKET,
    DEFAULT_OPTIONS_INCOME_DEFENSIVE_SYMBOL,
    load_options_income_matrix,
    load_options_income_thresholds,
)


def test_options_income_policy_defaults_and_thresholds():
    matrix = load_options_income_matrix()
    thresholds = load_options_income_thresholds()

    assert DEFAULT_OPTIONS_INCOME_DEFENSIVE_SYMBOL == "SGOV"
    assert DEFAULT_OPTIONS_INCOME_DEFENSIVE_BASKET == ["SGOV", "VGSH"]
    assert DEFAULT_OPTIONS_INCOME_BENCHMARK == "SPY"
    assert matrix["proxy_assets"] == ["JEPI", "JEPQ", "XYLD", "QYLD", "DIVO"]
    assert thresholds["max_drawdown_delta_pp"] == 1.5
    assert thresholds["recovery_time_delta_ratio"] == 0.20
    assert thresholds["ulcer_index_delta_ratio"] == 0.10
    assert thresholds["min_cagr_delta_pp"] == 0.5
    assert thresholds["min_sharpe_delta"] == 0.05
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run:

```bash
cd /app/stocklean && pytest backend/tests/test_options_income_policy.py -v
```

Expected:

```text
E   ModuleNotFoundError: No module named 'app.services.options_income_policy'
```

- [ ] **Step 3: 写最小实现，固化默认基线、代理资产和门槛**

`configs/research_options_income_matrix.json`

```json
{
  "baseline": {
    "risk_off_symbol": "SGOV",
    "risk_off_symbols": ["SGOV", "VGSH"],
    "benchmark": "SPY"
  },
  "proxy_assets": ["JEPI", "JEPQ", "XYLD", "QYLD", "DIVO"],
  "integration_modes": ["defensive_replacement", "idle_replacement"],
  "sleeve_weights": [0.2, 0.3],
  "thresholds": {
    "max_drawdown_delta_pp": 1.5,
    "recovery_time_delta_ratio": 0.2,
    "ulcer_index_delta_ratio": 0.1,
    "min_cagr_delta_pp": 0.5,
    "min_sharpe_delta": 0.05
  }
}
```

`backend/app/services/options_income_policy.py`

```python
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_CONFIG_PATH = Path("/app/stocklean/configs/research_options_income_matrix.json")

DEFAULT_OPTIONS_INCOME_DEFENSIVE_SYMBOL = "SGOV"
DEFAULT_OPTIONS_INCOME_DEFENSIVE_BASKET = ["SGOV", "VGSH"]
DEFAULT_OPTIONS_INCOME_BENCHMARK = "SPY"


@lru_cache(maxsize=1)
def load_options_income_matrix() -> dict:
    payload = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return payload


def load_options_income_thresholds() -> dict:
    payload = load_options_income_matrix()
    return dict(payload.get("thresholds") or {})
```

- [ ] **Step 4: 重新运行测试，确认基线配置可读**

Run:

```bash
cd /app/stocklean && pytest backend/tests/test_options_income_policy.py -v
```

Expected:

```text
1 passed
```

- [ ] **Step 5: 提交本任务**

```bash
cd /app/stocklean
git add configs/research_options_income_matrix.json \
        backend/app/services/options_income_policy.py \
        backend/tests/test_options_income_policy.py
git commit -m "feat(research): add options income policy baseline"
```

---

### Task 2: 抽出收益增强 sleeve 纯函数，并接入主策略 idle 路径

**Files:**
- Create: `algorithms/options_income_overlay.py`
- Modify: `algorithms/ml_overlay_scores.py`
- Test: `backend/tests/test_options_income_overlay.py`

- [ ] **Step 1: 先写失败测试，锁定两种允许的集成模式**

```python
from algorithms.options_income_overlay import apply_income_sleeve


def test_apply_income_sleeve_idle_replacement():
    weights = {"AMD": 0.30, "NVDA": 0.20, "SGOV": 0.50}
    result = apply_income_sleeve(
        weights=weights,
        idle_symbol="SGOV",
        income_symbol="JEPI",
        sleeve_weight=0.20,
        mode="idle_replacement",
    )
    assert result["JEPI"] == 0.20
    assert result["SGOV"] == 0.30
    assert result["AMD"] == 0.30
    assert result["NVDA"] == 0.20


def test_apply_income_sleeve_defensive_replacement():
    weights = {"AMD": 0.30, "NVDA": 0.20, "SGOV": 0.50}
    result = apply_income_sleeve(
        weights=weights,
        idle_symbol="SGOV",
        income_symbol="DIVO",
        sleeve_weight=0.30,
        mode="defensive_replacement",
    )
    assert result["DIVO"] == 0.30
    assert result["SGOV"] == 0.20
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run:

```bash
cd /app/stocklean && pytest backend/tests/test_options_income_overlay.py -v
```

Expected:

```text
E   ModuleNotFoundError: No module named 'algorithms.options_income_overlay'
```

- [ ] **Step 3: 写最小实现，并在 `ml_overlay_scores.py` 的 idle 分配后接入**

`algorithms/options_income_overlay.py`

```python
from __future__ import annotations


def apply_income_sleeve(
    *,
    weights: dict[str, float],
    idle_symbol: str | None,
    income_symbol: str | None,
    sleeve_weight: float,
    mode: str,
) -> dict[str, float]:
    if not idle_symbol or not income_symbol or sleeve_weight <= 0:
        return dict(weights)
    current_idle = float(weights.get(idle_symbol, 0.0) or 0.0)
    if current_idle <= 0:
        return dict(weights)
    applied = min(current_idle, sleeve_weight)
    if applied <= 0:
        return dict(weights)
    updated = dict(weights)
    updated[idle_symbol] = max(0.0, current_idle - applied)
    updated[income_symbol] = updated.get(income_symbol, 0.0) + applied
    if updated[idle_symbol] <= 1e-9:
        updated.pop(idle_symbol, None)
    return updated
```

`algorithms/ml_overlay_scores.py`

```python
from options_income_overlay import apply_income_sleeve

# initialize() 内新增
self.income_sleeve_symbol = (self.get_parameter("income_sleeve_symbol") or "").strip().upper()
self.income_sleeve_weight = self._coerce_float_param("income_sleeve_weight", 0.0)
self.income_sleeve_mode = (self.get_parameter("income_sleeve_mode") or "none").strip().lower()

# idle 分配后新增
if self.income_sleeve_mode in {"idle_replacement", "defensive_replacement"}:
    weights = apply_income_sleeve(
        weights=weights,
        idle_symbol=idle_symbol,
        income_symbol=self.income_sleeve_symbol,
        sleeve_weight=self.income_sleeve_weight,
        mode=self.income_sleeve_mode,
    )
    if self.income_sleeve_symbol in weights:
        self._set_runtime_stat("IncomeSleeve_Symbol", self.income_sleeve_symbol)
        self._set_runtime_stat("IncomeSleeve_Weight", f"{weights[self.income_sleeve_symbol]:.2%}")
        self._set_runtime_stat("IncomeSleeve_Mode", self.income_sleeve_mode)
```

- [ ] **Step 4: 重新运行测试，确认 pure function 通过**

Run:

```bash
cd /app/stocklean && pytest backend/tests/test_options_income_overlay.py -v
```

Expected:

```text
2 passed
```

- [ ] **Step 5: 提交本任务**

```bash
cd /app/stocklean
git add algorithms/options_income_overlay.py \
        algorithms/ml_overlay_scores.py \
        backend/tests/test_options_income_overlay.py
git commit -m "feat(algorithm): add options income sleeve overlay"
```

---

### Task 3: 增加研究矩阵 runner，批量生成回测 payload

**Files:**
- Create: `scripts/run_options_income_matrix.py`
- Test: `backend/tests/test_options_income_script_payloads.py`

- [ ] **Step 1: 先写失败测试，锁定矩阵展开和 payload 结构**

```python
from scripts.run_options_income_matrix import build_matrix_payloads


def test_build_matrix_payloads_expands_proxy_assets():
    payloads = build_matrix_payloads()
    names = {item["name"] for item in payloads}

    assert "baseline" in names
    assert "idle_replacement_jepi_20" in names
    assert "defensive_replacement_qyld_30" in names

    sample = next(item for item in payloads if item["name"] == "idle_replacement_jepi_20")
    algo = sample["payload"]["params"]["algorithm_parameters"]
    assert algo["income_sleeve_symbol"] == "JEPI"
    assert algo["income_sleeve_weight"] == "0.2"
    assert algo["income_sleeve_mode"] == "idle_replacement"
    assert algo["risk_off_symbols"] == "SGOV,VGSH"
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run:

```bash
cd /app/stocklean && pytest backend/tests/test_options_income_script_payloads.py -v
```

Expected:

```text
E   ModuleNotFoundError: No module named 'scripts.run_options_income_matrix'
```

- [ ] **Step 3: 写 runner，支持 `--dry-run`、`--group` 和 manifest**

`scripts/run_options_income_matrix.py`

```python
from __future__ import annotations

import json
from pathlib import Path

from app.services.options_income_policy import load_options_income_matrix


def build_matrix_payloads() -> list[dict]:
    matrix = load_options_income_matrix()
    baseline = matrix["baseline"]
    proxy_assets = matrix["proxy_assets"]
    modes = matrix["integration_modes"]
    sleeve_weights = matrix["sleeve_weights"]

    payloads: list[dict] = [
        {
            "name": "baseline",
            "payload": {
                "project_id": 18,
                "params": {
                    "algorithm_parameters": {
                        "benchmark": baseline["benchmark"],
                        "risk_off_symbol": baseline["risk_off_symbol"],
                        "risk_off_symbols": ",".join(baseline["risk_off_symbols"]),
                    }
                },
            },
        }
    ]

    for mode in modes:
        for symbol in proxy_assets:
            for weight in sleeve_weights:
                payloads.append(
                    {
                        "name": f"{mode}_{symbol.lower()}_{int(weight * 100)}",
                        "payload": {
                            "project_id": 18,
                            "params": {
                                "algorithm_parameters": {
                                    "benchmark": baseline["benchmark"],
                                    "risk_off_symbol": baseline["risk_off_symbol"],
                                    "risk_off_symbols": ",".join(baseline["risk_off_symbols"]),
                                    "income_sleeve_symbol": symbol,
                                    "income_sleeve_weight": str(weight),
                                    "income_sleeve_mode": mode,
                                }
                            },
                        },
                    }
                )
    return payloads
```

- [ ] **Step 4: 重新运行测试，确认矩阵展开正确**

Run:

```bash
cd /app/stocklean && pytest backend/tests/test_options_income_script_payloads.py -v
```

Expected:

```text
1 passed
```

- [ ] **Step 5: 提交本任务**

```bash
cd /app/stocklean
git add scripts/run_options_income_matrix.py \
        backend/tests/test_options_income_script_payloads.py
git commit -m "feat(research): add options income matrix runner"
```

---

### Task 4: 增加报告生成器和硬门槛判定

**Files:**
- Create: `scripts/generate_options_income_report.py`
- Test: `backend/tests/test_options_income_report.py`

- [ ] **Step 1: 先写失败测试，锁定 pass/fail 判定规则**

```python
from scripts.generate_options_income_report import evaluate_candidate


def test_evaluate_candidate_passes_when_return_improves_and_risk_stays_bounded():
    result = evaluate_candidate(
        baseline={
            "cagr": 0.08,
            "sharpe": 0.62,
            "max_drawdown": 0.128,
            "ulcer_index": 5.0,
            "recovery_days": 120,
        },
        candidate={
            "cagr": 0.086,
            "sharpe": 0.69,
            "max_drawdown": 0.138,
            "ulcer_index": 5.3,
            "recovery_days": 132,
        },
    )
    assert result["passed"] is True


def test_evaluate_candidate_fails_when_drawdown_gate_breaks():
    result = evaluate_candidate(
        baseline={
            "cagr": 0.08,
            "sharpe": 0.62,
            "max_drawdown": 0.128,
            "ulcer_index": 5.0,
            "recovery_days": 120,
        },
        candidate={
            "cagr": 0.095,
            "sharpe": 0.71,
            "max_drawdown": 0.150,
            "ulcer_index": 5.4,
            "recovery_days": 128,
        },
    )
    assert result["passed"] is False
    assert "max_drawdown" in result["reasons"]
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run:

```bash
cd /app/stocklean && pytest backend/tests/test_options_income_report.py -v
```

Expected:

```text
E   ModuleNotFoundError: No module named 'scripts.generate_options_income_report'
```

- [ ] **Step 3: 写最小报告判定器和 markdown 输出**

`scripts/generate_options_income_report.py`

```python
from __future__ import annotations

from app.services.options_income_policy import load_options_income_thresholds


def evaluate_candidate(*, baseline: dict, candidate: dict) -> dict:
    thresholds = load_options_income_thresholds()
    reasons: list[str] = []

    if (candidate["max_drawdown"] - baseline["max_drawdown"]) * 100 > thresholds["max_drawdown_delta_pp"]:
        reasons.append("max_drawdown")
    if (candidate["recovery_days"] - baseline["recovery_days"]) / baseline["recovery_days"] > thresholds["recovery_time_delta_ratio"]:
        reasons.append("recovery_time")
    if (candidate["ulcer_index"] - baseline["ulcer_index"]) / baseline["ulcer_index"] > thresholds["ulcer_index_delta_ratio"]:
        reasons.append("ulcer_index")

    cagr_delta_pp = (candidate["cagr"] - baseline["cagr"]) * 100
    sharpe_delta = candidate["sharpe"] - baseline["sharpe"]
    passed_return = cagr_delta_pp >= thresholds["min_cagr_delta_pp"] or sharpe_delta >= thresholds["min_sharpe_delta"]

    return {
        "passed": passed_return and not reasons,
        "reasons": reasons,
        "cagr_delta_pp": cagr_delta_pp,
        "sharpe_delta": sharpe_delta,
    }
```

- [ ] **Step 4: 重新运行测试，确认门槛判定稳定**

Run:

```bash
cd /app/stocklean && pytest backend/tests/test_options_income_report.py -v
```

Expected:

```text
2 passed
```

- [ ] **Step 5: 提交本任务**

```bash
cd /app/stocklean
git add scripts/generate_options_income_report.py \
        backend/tests/test_options_income_report.py
git commit -m "feat(research): add options income decision gate"
```

---

### Task 5: 跑研究矩阵并产出正式报告

**Files:**
- Create: `docs/reports/2026-04-07-options-income-matrix-baseline.md`
- Create: `docs/reports/2026-04-07-options-income-proxy-report.md`
- Create: `docs/reports/2026-04-07-options-income-final-decision.md`

- [ ] **Step 1: 先 dry-run runner，确认矩阵展开符合预期**

Run:

```bash
cd /app/stocklean && python scripts/run_options_income_matrix.py --dry-run
```

Expected:

```text
baseline
idle_replacement_jepi_20
idle_replacement_jepi_30
...
defensive_replacement_divo_30
```

- [ ] **Step 2: 正式提交回测矩阵**

Run:

```bash
cd /app/stocklean && python scripts/run_options_income_matrix.py --group all
```

Expected:

```text
submitted <run_id> -> baseline
submitted <run_id> -> idle_replacement_jepi_20
...
```

- [ ] **Step 3: 生成报告**

Run:

```bash
cd /app/stocklean && python scripts/generate_options_income_report.py
```

Expected:

```text
wrote docs/reports/2026-04-07-options-income-matrix-baseline.md
wrote docs/reports/2026-04-07-options-income-proxy-report.md
wrote docs/reports/2026-04-07-options-income-final-decision.md
```

- [ ] **Step 4: 验证报告落盘且结论可读**

Run:

```bash
cd /app/stocklean && ls docs/reports/2026-04-07-options-income-*.md && sed -n '1,80p' docs/reports/2026-04-07-options-income-final-decision.md
```

Expected:

```text
docs/reports/2026-04-07-options-income-final-decision.md
Decision:
- default_path: unchanged
- enter_real_options_phase: false|true
```

- [ ] **Step 5: 提交本任务**

```bash
cd /app/stocklean
git add docs/reports/2026-04-07-options-income-matrix-baseline.md \
        docs/reports/2026-04-07-options-income-proxy-report.md \
        docs/reports/2026-04-07-options-income-final-decision.md
git commit -m "docs(research): publish options income proxy results"
```

---

## 计划自检

- 规格覆盖：
  - 代理研究路径：Task 1, 3, 5
  - 稳健门槛：Task 1, 4
  - 仅允许插入 idle/defensive：Task 2
  - 不进入真实期权默认路径：Task 4, 5
- Placeholder 扫描：
  - 无 `TODO/TBD/implement later`
- 类型一致性：
  - `income_sleeve_symbol`
  - `income_sleeve_weight`
  - `income_sleeve_mode`
  - `idle_replacement`
  - `defensive_replacement`
  以上名称在任务间保持一致。
