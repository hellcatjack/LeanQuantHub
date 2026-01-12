# QC 数据管理对齐 TODO

目标：对齐 QuantConnect 的周频交易数据与基本面管理经验，落地到本系统。

## TODO 列表

1. [x] Security Master 基础对齐
   - 统一记录 symbol 生命周期与 override
   - 明确映射文件/公司行为因子来源
   - 在 PIT 基本面输出元数据中记录依赖路径

2. [x] PIT 基本面 as-of + 缺省延迟
   - reportedDate 优先
   - reportedDate 缺失时使用 fiscalDate + 默认延迟（如 45 天）
   - 输出 availability_source/available_date

3. [x] Fill-forward 与数据新鲜度标记
   - 每个快照输出 data_age/filled_forward 标识
   - 元数据记录 fill-forward 策略

4. [x] 资产类型过滤（默认仅普通股）
   - 默认排除 ETF/ADR/OTC
   - 支持配置 asset_types
   - 元数据输出过滤统计

5. [x] 交付时点与可用性元数据
   - 写入 PIT 基本面快照 meta（含报表延迟与可用时间假设）
   - 标注“周一开盘调仓、快照取上个交易日收盘”规则

## 验收

- PIT 基本面快照脚本支持新参数
- 生成的 `pit_fundamentals_meta.json` 可追溯策略与依赖
- 数据页 PIT 基本面表单支持新参数输入
- 小样本测试通过（最小数据根目录）
