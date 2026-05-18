# Defensive Asset Evaluation Matrix Experiment Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以“稳健优先于收益”为长期目标，系统化评估防御候选、对冲扩展、商品观察和风险对照四类资产，形成后续默认防御资产与研究候选集的稳定决策依据。

**Architecture:** 固定当前项目策略逻辑与股票池，仅在防御篮子、对冲扩展和基准敏感度上做受控变量实验。采用“先核心防御、再对冲扩展、再商品观察、最后风险对照”的分层回测矩阵，并以稳定性指标作为主判据、收益指标作为次判据。

**Tech Stack:** Lean backtests, Alpha `curated_adjusted` 日线数据, StockLean project/backtest pipeline, Markdown reports, CSV experiment matrix

---

## 长期原则

1. **稳健是长期目标，不是收益的附属条件。**
2. 默认防御资产必须优先满足回撤可控、恢复能力强、跨阶段一致性好。
3. 高收益但依赖单一宏观风格暴露的标的，只能作为研究候选，不应直接提升为系统默认。
4. 后续开发若涉及防御资产、risk-off、idle allocation、benchmark filter，一律优先检查是否强化了系统稳健性，而不是仅比较 CAGR。

## 当前事实基线

### 1. 当前默认配置
- 默认防御主标的：`SGOV`
- 默认防御篮子：`SGOV,VGSH`
- 当前项目 `18` 解析结果：`benchmark=SPY`、`risk_off_symbols=SGOV,VGSH`、`risk_off_symbol=SGOV`

### 2. 当前系统是否自动纳入 `USO/BNO/QQQ/SOXX`
当前活跃项目自动评估集合只包含：
- 最新 decision snapshot 实际涉及的 symbols
- 项目 `risk_off_symbols / risk_off_symbol`
- 项目 `benchmark`

因此在当前运行态下：
- `SGOV/VGSH` 已自动纳入
- `SPY` 作为 benchmark 已自动纳入
- `USO/BNO/QQQ/SOXX` **不会自动纳入当前活跃项目评估集合**

### 3. 当前数据支持情况
以下标的在 `curated_adjusted` 中已有日线复权数据，可直接用于第一阶段回测研究：
- 防御/利率：`SGOV`, `VGSH`, `IEF`, `TLT`
- 对冲：`GLD`
- 商品观察：`USO`, `BNO`
- 风险对照：`QQQ`, `SOXX`
- 控制基准：`SPY`

## 研究边界

### 允许进入“默认防御候选”的资产类型
- 超短/短久期美债：`SGOV`, `VGSH`
- 中长久期国债：`IEF`, `TLT`
- 通胀/避险对冲：`GLD`

### 只允许作为“观察/对照”的资产类型
- 商品/能源暴露：`USO`, `BNO`
- 风险偏好或行业 beta：`QQQ`, `SOXX`

### 明确禁止的错误结论
- 不允许因为某个标的在某一阶段把收益拉高，就直接把它定义为“默认防御资产”。
- `QQQ`、`SOXX` 不应进入默认防御篮子；它们只能作为风险对照或 benchmark 敏感度实验。
- `USO`、`BNO` 不应直接进入默认防御篮子；它们只能作为商品暴露观察组，判断是否具备独立对冲价值。

## 实验矩阵

### Layer A：核心防御候选组
这些组用于决定默认防御资产和默认防御篮子。

| 组别 | 防御配置 | 目的 |
|---|---|---|
| A0 | `SGOV` | 现金替代单标的控制组 |
| A1 | `SGOV,VGSH` | 当前默认组，对比 A0 是否在不明显增风险的前提下提升稳健性 |
| A2 | `SGOV,VGSH,IEF` | 检验中久期债券是否改善风险关闭阶段表现 |
| A3 | `SGOV,VGSH,TLT` | 检验长久期债券是否带来过度利率风险 |

### Layer B：对冲扩展组
这些组不直接争夺默认值，而是评估 `GLD` 是否应作为显式 opt-in 对冲扩展。

| 组别 | 防御配置 | 目的 |
|---|---|---|
| B1 | `SGOV,VGSH,GLD` | 检验轻量黄金对冲是否改善稳健性 |
| B2 | `SGOV,VGSH,IEF,GLD` | 检验债券 + 黄金混合是否优于纯债券组 |
| B3 | `SGOV,VGSH,TLT,GLD` | 检验高久期 + 黄金是否带来过多风格暴露 |

### Layer C：商品观察组
这些组只用于判断能源商品是否提供额外分散化，默认不进入正式防御候选。

| 组别 | 防御配置 | 目的 |
|---|---|---|
| C1 | `SGOV,VGSH,USO` | 观察原油 ETF 是否在特定阶段改善风险对冲 |
| C2 | `SGOV,VGSH,BNO` | 观察布油 ETF 是否提供比 USO 更稳的商品暴露 |
| C3 | `SGOV,VGSH,USO,BNO` | 观察双能源组合是否只是放大商品风险 |

### Layer D：风险对照与 benchmark 敏感度
这些组不改变防御篮子，只改变风险比较标尺或市场过滤基准。

| 组别 | benchmark | 防御配置 | 目的 |
|---|---|---|---|
| D0 | `SPY` | `SGOV,VGSH` | 当前控制组 |
| D1 | `QQQ` | `SGOV,VGSH` | 检验科技 beta 作为市场过滤基准时是否更脆弱 |
| D2 | `SOXX` | `SGOV,VGSH` | 检验半导体 beta 作为基准时是否过度敏感 |

## 样本窗口

### 全样本
- `2020-01-01` 到最新可用交易日

### 分阶段样本
- Phase 1：`2020-01-01` 至 `2021-12-31`
- Phase 2：`2022-01-01` 至 `2022-12-31`
- Phase 3：`2023-01-01` 至 `2024-12-31`
- Phase 4：`2025-01-01` 至最新可用交易日

### 说明
- 所有组必须在相同股票池、相同模型、相同风控参数、相同手续费假设下运行。
- 每轮实验只能改变一个维度：防御篮子或 benchmark；禁止混入其他参数漂移。

## 指标体系

### 一级判据：稳健性
以下指标决定是否允许某组进入默认候选讨论：
- 最大回撤（Max Drawdown）
- 回撤持续时间（Drawdown Duration）
- 63 交易日最差收益
- 126 交易日最差收益
- Phase 2 / Phase 4 下的回撤与恢复能力
- 换手率与总手续费

### 二级判据：效率
仅在一级判据通过后才比较：
- CAGR
- Sharpe
- Sortino
- 终值

### 统一判定原则
- 若某组显著提升收益但明显恶化最大回撤或回撤持续时间，则判为**不稳健**。
- 若某组收益略低，但跨阶段回撤更小、恢复更稳定，则优先级更高。
- 默认值提升必须是“跨阶段更稳”，不能只依赖单阶段高收益。

## 提升为默认值的门槛

某个防御组要成为新的默认防御配置，至少满足：
1. 全样本最大回撤不劣于当前默认组 `SGOV,VGSH` 超过 `1.0` 个百分点。
2. 四个阶段中至少三个阶段的回撤或恢复表现不差于当前默认组。
3. 总手续费和换手率不能显著恶化。
4. 若收益提升主要来自 `GLD/USO/BNO` 的单一风格暴露，则默认判为“研究候选”，而不是默认配置。

## 当前推荐路径

基于现有证据，后续实验优先顺序为：
1. **先做 Layer A**：决定默认防御候选是否维持 `SGOV,VGSH` 或升级到 `SGOV,VGSH,IEF`
2. **再做 Layer B**：判断 `GLD` 是否只适合作为 opt-in 对冲扩展
3. **再做 Layer C**：验证 `USO/BNO` 是否只是商品收益放大器，而非稳健对冲
4. **最后做 Layer D**：判断 `QQQ/SOXX` 是否只适合作为风险基准敏感度测试

## 任务 1：冻结实验基线

**Files:**
- Read: `backend/app/routes/projects.py`
- Read: `backend/app/routes/algorithms.py`
- Read: `configs/default_algorithm.json`
- Output: `docs/reports/2026-04-07-defensive-asset-matrix-baseline.md`

- [ ] 记录当前项目 `18` 的实际 backtest 参数、benchmark、risk_off 配置。
- [ ] 记录当前使用的算法版本与数据区间，生成基线文档。
- [ ] 确认后续所有实验仅变更防御篮子或 benchmark，不允许混入其他参数变化。

## 任务 2：执行 Layer A 核心防御候选组

**Files:**
- Read: `scripts/run_cagr_opt.py`
- Read: `scripts/run_project18_train120_opt.py`
- Output: `docs/reports/2026-04-07-defensive-asset-layer-a-report.md`

- [ ] 以当前项目配置为控制组运行 A0-A3。
- [ ] 收集每组的全样本与分阶段指标。
- [ ] 输出 Layer A 对比报告，并给出默认防御候选建议。

## 任务 3：执行 Layer B 对冲扩展组

**Files:**
- Output: `docs/reports/2026-04-07-defensive-asset-layer-b-report.md`

- [ ] 运行 B1-B3。
- [ ] 单独分析 `GLD` 带来的收益提升是否伴随风格集中和回撤放大。
- [ ] 判断 `GLD` 是否只能作为显式 opt-in 对冲扩展。

## 任务 4：执行 Layer C 商品观察组

**Files:**
- Output: `docs/reports/2026-04-07-defensive-asset-layer-c-report.md`

- [ ] 运行 C1-C3。
- [ ] 重点检查 `USO/BNO` 在 2022 与 2025+ 阶段的表现稳定性。
- [ ] 明确判断它们是否具备“稳健对冲”属性，还是仅提供商品 beta。

## 任务 5：执行 Layer D 风险对照与 benchmark 敏感度

**Files:**
- Output: `docs/reports/2026-04-07-defensive-asset-layer-d-report.md`

- [ ] 固定防御篮子为 `SGOV,VGSH`，分别运行 `SPY/QQQ/SOXX` benchmark 组。
- [ ] 分析市场过滤器在科技/半导体 benchmark 下是否更容易产生误触发。
- [ ] 明确 `QQQ/SOXX` 只作为风险对照，不作为防御默认候选。

## 任务 6：形成默认值决策与后续开发约束

**Files:**
- Output: `docs/reports/2026-04-07-defensive-asset-matrix-final-decision.md`

- [ ] 汇总 A-D 四层结果，按“稳健优先”输出最终结论。
- [ ] 给出三个明确结论：
- [ ] 默认防御资产/篮子建议
- [ ] 显式 opt-in 对冲扩展建议
- [ ] 不进入默认值、仅保留研究用途的观察标的清单
- [ ] 把结论转化为后续开发约束：新的 risk-off / idle allocation 设计必须先通过该稳健性标准。

## 需要的额外数据支持

### 当前第一阶段不需要新增的数据
- 日线复权数据已经足够覆盖 `SGOV/VGSH/IEF/TLT/GLD/USO/BNO/QQQ/SOXX/SPY`
- 第一阶段目标是方向性结论，不需要分钟级或期权数据

### 第二阶段可能需要补充的数据
若第一阶段发现某类资产值得继续研究，再考虑新增：
- 宏观阶段标签（利率上行/下行、通胀阶段）
- 更长历史窗口的稳定性检验
- 更细粒度的回撤恢复路径分析

## 成功标准

1. 明确回答：当前系统默认评估范围是否自动包含 `USO/BNO/QQQ/SOXX`。
2. 给出分层矩阵，而不是把所有标的塞进同一个“防御篮子”。
3. 形成可以执行的回测顺序和升级门槛。
4. 将“稳健优先于收益”固化为后续防御资产相关开发的默认原则。
