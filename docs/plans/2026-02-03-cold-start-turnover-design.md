# 冷启动换手限制（cold_start_turnover）设计

## 背景
当前组合在“冷启动”（上一期权重为 0 或缺失）时仍使用周换手限制 `turnover_limit`，导致目标权重总和被强制压低，出现目标市值偏小（例如仅约 10% 资金被使用）。需要在冷启动场景允许更高的换手上限，但仍可审计与可控。

## 目标
- 冷启动时使用独立的换手上限 `cold_start_turnover`（默认 0.3）。
- 非冷启动仍遵循 `turnover_limit`。
- 决策快照与日志中明确记录“冷启动判定”和“生效的换手限制”，确保可审计。

## 范围
- 训练/回测与实盘的决策流水均可使用该参数。
- 仅影响换手约束，不改变风控与其他权重约束逻辑。

## 非目标
- 不引入新的数据源或价格回退。
- 不改变现有组合构建算法的核心计算方式。

## 需求与约束
- 参数范围：`(0, 1]`，超出返回 422。
- 前端输入限制在 `0-1`，默认 `0.3`。
- 冷启动判定：`prev_weight_sum <= 1e-6` 或缺失上一期快照。
- 冷启动与非冷启动均记录 `effective_turnover_limit`。

## 设计方案
### 参数定义
- 新增 `cold_start_turnover`（默认 0.3）。
- 作为算法参数传入并落地到决策配置（weights_cfg）。

### 核心逻辑
- 计算 `prev_weight_sum`：上一期权重绝对值求和。
- 若冷启动：`effective_turnover_limit = cold_start_turnover`；否则为 `turnover_limit`。
- 保持原有 `_apply_turnover_limit` 实现不变，仅调整其输入。

### 可观测性
- 在 `decision_summary.json` 记录：
  - `cold_start: true/false`
  - `prev_weight_sum`
  - `effective_turnover_limit`
  - `turnover_limit` / `cold_start_turnover`
- 日志中输出 run_id 与生效换手限制（不包含账户敏感信息）。

## 涉及模块
- 后端：决策快照参数映射（decision_snapshot）
- 组合构建：`scripts/universe_pipeline.py`
- 前端：项目/算法参数输入与默认值
- 文案：`frontend/src/i18n.tsx`

## 错误处理
- 参数校验失败返回 422，提示范围要求。
- 未提供 `cold_start_turnover` 时回退为 `turnover_limit`。

## 测试计划
- 单元测试：
  - 冷启动时权重总和 ≤ `cold_start_turnover`
  - 非冷启动时权重总和 ≤ `turnover_limit`
  - 缺参回退正确
- 集成测试：决策快照 summary 中 `cold_start` 与 `effective_turnover_limit` 输出正确。

## 验收标准
- 冷启动资金使用率提升且满足新上限。
- 非冷启动行为不变。
- 可审计字段齐全并可追踪。

