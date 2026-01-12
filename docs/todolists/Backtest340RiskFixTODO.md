# 回测340 数据链路风险修复 TODO

目标：修复当前回测 340 的 4 个关键缺陷，保证数据一致性、可复现与口径统一。

## 1) 主题标的资产类型过滤（只保留 STOCK）
### 问题
- 主题标的构建未强制按资产类型过滤，导致 ADR/ETF/非美股混入，评分与价格缺失。

### 方案
- 在主题→symbols 解析链路中加入 asset_type 过滤，仅允许 `STOCK`。
- 过滤逻辑应对 `symbol_types` 配置与 `universe/alpha_symbol_life.csv` 资产类型对齐。

### 开发任务
- 后端：在主题成员解析流程引入 `asset_types` 过滤开关（默认 STOCK）。
- 前端：在项目配置页明确展示/固定 `asset_types=STOCK`（可读不可改）。
- 数据：对现有主题 symbol 缓存做一次重算（只移除非 STOCK）。

### 自测
- 新建回测：symbols 列表中不再出现 ADR/ETF/非美股。
- Missing Scores 数量下降或保持不升（对比回测 340）。

---

## 2) 回测绑定训练作业（可复现）
### 问题
- 回测默认使用 `ml/models/scores.csv`，模型更新后历史回测不可复现。

### 方案
- 回测参数中增加 `pipeline_train_job_id` 优先级（或 UI 显式选择训练任务）。
- 回测创建时将 `score_csv_path` 固定为训练产物路径。
- 回测详情中展示训练任务 ID 与 scores 文件路径。

### 开发任务
- 后端：回测创建接口补齐训练作业绑定字段与校验。
- 前端：回测参数面板增加「训练任务」选择器（默认当前激活训练）。
- 回测详情：显示 `train_job_id` + `score_csv_path`。

### 自测
- 使用训练 53 的 scores 发起回测，确认 `score_csv_path` 指向 artifacts 下路径。
- 再切换训练任务发起回测，确认结果与路径不同。

---

## 3) PIT 缺失策略可控 + 覆盖率提示
### 问题
- 当前 `missing_policy=fill_zero`，可能引入系统性偏差。

### 方案
- 提供 `fill_zero` / `drop` / `sample_on_snapshot` 的 UI 选择。
- 训练/回测运行前输出 PIT 覆盖率与缺失策略提示（含最小覆盖阈值）。

### 开发任务
- 后端：在训练/预测入参中暴露 `pit_fundamentals.missing_policy` 与 `sample_on_snapshot`。
- 前端：模型训练参数面板增加 PIT 缺失策略与样本采样方式。
- 运行日志：打印 PIT 覆盖率 + 策略摘要。

### 自测
- 使用 `missing_policy=drop` 启动训练，确认样本量下降且日志有覆盖率。
- 使用 `fill_zero` 训练，确认覆盖率提示与策略显示正常。

---

## 4) 项目配置数据源统一为 Alpha
### 问题
- 项目配置仍显示 `stooq/yahoo`，与系统“Alpha-only”实际不一致。

### 方案
- 项目配置保存时强制写入 `data.primary_vendor=alpha`，`fallback_vendor` 清空。
- UI 文案明确显示「Alpha only」。

### 开发任务
- 后端：保存项目配置时覆写 vendor 字段（只 Alpha）。
- 前端：配置页显示只读「Alpha」标识。
- 文档：补充 Alpha-only 说明与配置约束。

### 自测
- 保存项目配置后再次读取，确认 vendor 字段为 Alpha。
- 触发一次数据同步/回测，确认未再引用 stooq/yahoo。

---

## 验收标准（统一）
- 回测 340 再跑：symbols 全为 STOCK，scores 缺失显著减少。
- 回测可复现：同一训练作业绑定多次回测结果一致。
- PIT 策略可配置，覆盖率提示可见。
- 配置与系统实际数据源一致为 Alpha。
