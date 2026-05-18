# 2026-04-07 防御资产矩阵最终决策

## 决策目标
本决策基于以下长期目标：
- **稳健优先于收益**
- 默认防御路径必须优先满足回撤可控、恢复稳定、跨阶段行为一致
- 高收益但依赖单一宏观或商品风格暴露的方案，只能作为显式研究扩展，不进入默认值

## 实验范围与证据来源
本轮矩阵实验覆盖四层：
- Layer A：核心防御候选组
- Layer B：黄金对冲扩展组
- Layer C：商品观察组
- Layer D：benchmark 敏感度组

对应报告：
- [Layer A](/app/stocklean/docs/reports/2026-04-07-defensive-asset-layer-a-report.md)
- [Layer B](/app/stocklean/docs/reports/2026-04-07-defensive-asset-layer-b-report.md)
- [Layer C](/app/stocklean/docs/reports/2026-04-07-defensive-asset-layer-c-report.md)
- [Layer D](/app/stocklean/docs/reports/2026-04-07-defensive-asset-layer-d-report.md)

## 最终结论

### 1. 默认防御资产/篮子建议
- 默认防御主标的：`SGOV`
- 默认防御篮子：`SGOV,VGSH`
- 默认 benchmark：`SPY`

原因：
- `SGOV,VGSH` 在 Layer A 中仍然是收益效率与稳健性的最好平衡点。
- `SGOV,VGSH,IEF` 虽然更保守，但没有形成足够强的跨阶段优势来替代默认值。
- `SPY` 作为 benchmark 仍然是更中性的市场过滤基准；`QQQ/SOXX` 会让过滤器更偏向 risk-on。

### 2. 保守替代候选
- 保守替代候选：`SGOV,VGSH,IEF`

定位：
- 作为显式 opt-in 的保守版研究候选
- 适合后续专门评估“更低回撤优先”的策略分支
- 不直接升级为系统默认值

### 3. 显式 opt-in 对冲扩展建议
- `GLD` 只保留为显式 opt-in 对冲扩展或收益增强研究项
- 不进入默认防御篮子

原因：
- Layer B 证明 `GLD` 能显著抬高收益，但防御行为会塌缩为黄金主导
- 在 2022 压力阶段，`GLD` 组明显弱于债券型默认候选
- 这属于风格暴露增强，不属于默认稳健防御

### 4. 不进入默认值、仅保留研究用途的标的
以下标的不进入默认防御或默认 benchmark 路径，只保留研究或敏感度测试用途：
- `GLD`：显式 opt-in 对冲扩展
- `USO`：商品观察组
- `BNO`：商品观察组
- `TLT`：高久期研究候选，不进入默认主线
- `QQQ`：benchmark 敏感度测试
- `SOXX`：benchmark 敏感度测试

## 各层结论摘要

### Layer A 摘要
- `SGOV,VGSH` 继续保留为默认防御篮子
- `SGOV,VGSH,IEF` 进入保守替代候选
- `SGOV,VGSH,TLT` 退出默认候选主线

### Layer B 摘要
- `GLD` 组提升收益，但以风格集中和更差压力阶段表现为代价
- 不进入默认值，只保留 opt-in 扩展定位

### Layer C 摘要
- `USO/BNO` 提供的是商品 beta，不是稳健防御属性
- `BNO` 比 `USO` 略稳，但仍只适合研究观察
- `USO+BNO` 双商品组合应停止继续作为候选主线

### Layer D 摘要
- `QQQ/SOXX` benchmark 略微提升全样本效率，但会让市场过滤器更少进入 risk-off
- 它们更适合作为敏感度测试，不应替代 `SPY`

## 后续开发约束
后续所有涉及 `risk-off`、`idle allocation`、`benchmark filter`、`defensive basket` 的开发，默认遵守以下约束：

1. **新增默认防御资产前，必须证明跨阶段稳健性优于当前默认值。**
2. **不得因为单阶段高收益就把 `GLD/USO/BNO` 引入默认路径。**
3. **`QQQ/SOXX` 只用于敏感度测试，不作为默认 benchmark。**
4. **若修改 `idle_allocation` 或 `risk_off_pick` 逻辑，必须重新验证是否导致默认路径塌缩为单一风格资产。**
5. **任何新的防御路径设计，都必须至少复核：**
   - 全样本 MaxDD
   - 63/126 日最差滚动收益
   - 最大回撤持续时间
   - 2022 压力阶段表现
   - 2025+ 最近阶段表现

## 当前默认开发基线
除非后续实验明确推翻，本项目后续默认基线固定为：
- `risk_off_symbol = SGOV`
- `risk_off_symbols = SGOV,VGSH`
- `benchmark = SPY`
- `GLD/USO/BNO/QQQ/SOXX` 不进入默认路径

## 下一步
后续如果继续推进，应优先做两类工作：
1. 把上述最终结论沉淀进配置默认值校验和研究模板
2. 若要继续研究，只在显式实验分支里验证：
   - `SGOV,VGSH,IEF` 是否值得作为单独“稳健模式”
   - `GLD` 是否适合作为可开关的增强模块，而不是默认值
