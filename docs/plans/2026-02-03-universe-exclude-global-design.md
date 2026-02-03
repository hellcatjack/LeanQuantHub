# 全局排除标的清单设计（数据页面）

## 背景与问题
当前系统在 PreTrade、回测、实盘执行、主题筛选等环节存在多处“排除标的”逻辑，来源分散且缺乏统一维护入口，导致排除规则不一致、难追踪与难复用。

## 目标
- 建立**单一全局排除清单**作为唯一真源（Source of Truth）。
- 在“数据页面”提供**固定的排除列表管理 UI**（增删改查）。
- 全系统读取同一份排除清单，避免重复配置与冲突。
- 采用**软删除**以保留历史并支持恢复。
- 预设排除：`WY/XOM/YUM`。

## 非目标
- 不引入新的 DB 表（本期不做 DB 迁移）。
- 不做复杂的权限分级体系（复用现有权限框架或暂不限制）。

## 数据模型
**文件路径（推荐跟随 data_root）：**
- 逻辑路径：`data_root/universe/exclude_symbols.csv`
- 默认 data_root：`/data/share/stock/data`

**CSV 字段：**
- `symbol`：大写标的
- `enabled`：是否启用（软删除用 false）
- `reason`：排除原因
- `source`：来源（如 `manual/ui`、`import/legacy`）
- `created_at`、`updated_at`

## 后端接口（统一入口）
建议新增 `/api/universe/excludes`：
- `GET /api/universe/excludes`：返回全量记录，支持 `enabled` 过滤
- `POST /api/universe/excludes`：新增或恢复（若已存在则置 `enabled=true`）
- `PATCH /api/universe/excludes/{symbol}`：更新 `enabled/reason/source`
- `DELETE /api/universe/excludes/{symbol}`：等价于 `enabled=false`

**校验：**
- `symbol` 仅允许字母/数字/点号，长度 1–10，强制大写与去空格
- 非法输入返回 400，错误信息可直接用于 UI 展示

**并发与错误处理：**
- 写入时加进程内锁或文件锁，避免并发写冲突
- 写入失败返回 500，并记录上下文日志

## 系统读取与迁移
- 统一读取方法：`get_active_excludes()`
- PreTrade / 回测 / 实盘执行 / 主题筛选 / 数据管道均通过统一方法读取
- 迁移旧逻辑：将现有排除来源导入 CSV 并标注 `source=import/legacy`
- 禁止各模块继续维护私有排除列表

## 数据页面 UI
新增固定区块「全局排除列表」：
- 列表列：`symbol / enabled / reason / source / updated_at`
- 支持搜索、过滤（enabled/all）
- 行内操作：禁用/启用/编辑原因与来源
- 新增入口：symbol + reason（source 默认 `manual/ui`）
- 初次加载若 CSV 不存在：自动创建并写入 `WY/XOM/YUM`

**i18n：**新增文案均进入 `frontend/src/i18n.tsx`，避免 key 重复。

## 测试与回归
**后端单测：**
- 新增/读取/禁用/恢复流程
- 校验非法 symbol
- 并发写入异常处理

**Playwright：**
- 数据页面 CRUD 流程
- 预设标的展示与禁用/启用

**回归关注：**
- 旧排除逻辑不再生效，仅以全局清单为准
- CSV 缺失可自动恢复并不影响任务执行

## 验收标准
- 数据页面可完成排除列表 CRUD（软删除）
- WY/XOM/YUM 默认存在且启用
- PreTrade/回测/实盘/主题均能识别并排除相同标的
- 旧排除入口不再产生影响
