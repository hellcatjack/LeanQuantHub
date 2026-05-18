# 默认防御标的统一为 SGOV 设计

**目标**

将系统默认的防御标的与防御篮子统一为 `SGOV`，并把当前已保存的项目配置与算法参数强制迁移到 `SGOV`。迁移仅作用于配置源，不修改历史回测、交易、决策快照等运行产物。

**背景**

当前系统存在多处默认值来源：
- 项目默认回测参数中的 `risk_off_symbols` / `risk_off_symbol`
- 算法页参数编辑器中的 `defensive.symbols`
- Lean 算法文件中的运行时兜底值
- `configs/default_algorithm.json` 中的默认算法版本参数
- 数据库里的 `project_versions.content` 与 `algorithm_versions.params`

这些来源目前并不一致，既有 `VGSH,IEF,GLD,TLT`，也有 `VGSH`、`SHY,IEF`。如果只改一处，系统仍会在不同入口继续回填旧值。

## 设计决策

### 1. 默认值统一规则

统一后的默认值规则：
- 默认防御标的：`SGOV`
- 默认防御篮子：`SGOV`
- 对外显示与输入预填：使用单值 `SGOV`
- 算法运行时兜底：使用单值列表 `["SGOV"]`

不再保留 `VGSH,IEF,GLD,TLT`、`VGSH` 或 `SHY,IEF` 作为默认组合。

### 2. 变更范围

本次修改覆盖以下对象：

#### 2.1 新默认值
- `backend/app/routes/projects.py`
- `frontend/src/pages/ProjectsPage.tsx`
- `frontend/src/pages/AlgorithmsPage.tsx`
- `configs/default_algorithm.json`

#### 2.2 算法运行时兜底
- `algorithms/ml_overlay_scores.py`
- `algorithms/composite_trend_lowvol.py`
- `algorithms/trend_momentum_defensive.py`
- `algorithms/low_vol_defensive.py`
- `algorithms/lean_trend_rotation.py`

#### 2.3 已保存配置迁移
- `project_versions.content` 中的项目配置 JSON
- `algorithm_versions.params` 中的算法参数 JSON

#### 2.4 明确不改的数据
- `backtest_runs.params`
- `decision_snapshots`
- `trade_runs.params`
- 其他历史执行、审计、报告产物

理由：这些对象承载的是历史事实，修改会破坏回放与审计一致性。

## 架构与数据流

### 1. 后端规范化

后端新增配置规范化逻辑，在读取或保存配置时将防御字段收敛为 `SGOV`：
- 项目配置中的 `backtest_params.risk_off_symbols`
- 项目配置中的 `backtest_params.risk_off_symbol`
- 算法版本参数中的 `risk_off_symbols`
- 算法版本参数中的 `risk_off_symbol`
- 算法版本参数中的 `defensive.symbols`

这层规范化的作用是：
- 即使数据库中仍有漏网旧值，运行时也不会再把旧值扩散出去
- 新保存的配置自动落成 `SGOV`
- 前后端默认值与后端实际行为保持一致

### 2. 数据库迁移

新增一条 MySQL patch，直接迁移当前配置源：
- 将 `project_versions.content` 中相关字段强制改为 `SGOV`
- 将 `algorithm_versions.params` 中相关字段强制改为 `SGOV`
- 同步更新 `project_versions.content_hash`
- 记录 `schema_migrations`

项目配置的真源是 `project_versions.content`，不是独立配置表。因此必须直接更新版本内容，否则系统仍会从旧版本 JSON 读取旧值。

### 3. 前端默认值

前端仅负责展示一致的默认预填：
- 项目页回测参数默认值改为 `SGOV`
- 算法页防御篮子默认值改为 `SGOV`
- placeholder 与默认 state 一并更新

### 4. 算法运行时兜底

Lean 算法保留防御兜底，但兜底内容统一改为 `SGOV`，避免参数缺失时回落到旧标的。

## 错误处理与幂等

### 1. 数据库 patch

Patch 需要满足幂等：
- 仅在表存在时执行
- 仅对可识别 JSON 执行 JSON 更新
- 重复执行不应改变最终结果
- `schema_migrations` 插入应避免重复记录

### 2. 读取旧配置

若配置 JSON 非法，仍维持现有容错逻辑，不因为本次规范化额外抛错。

### 3. 历史运行记录

不做回写修正。旧 run/snapshot 中仍可能看到旧防御符号，这是预期行为，因为它们反映的是当时实际使用的配置。

## 测试策略

### 1. 后端单测
- 默认项目配置应返回 `SGOV`
- 默认算法配置应返回 `SGOV`
- 项目配置规范化应强制把旧值收敛到 `SGOV`
- 算法版本参数规范化应强制把旧值收敛到 `SGOV`

### 2. 数据迁移验证
- 新 patch 至少覆盖 `project_versions.content` 和 `algorithm_versions.params`
- patch 文本包含变更说明、影响范围、回滚指引、`schema_migrations` 记录

### 3. 前端验证
- 项目页默认 `risk_off_symbols` 为 `SGOV`
- 算法页默认 `defensive.symbols` 为 `SGOV`
- 如涉及 UI 变更，执行 `npm run build` 并重启 `stocklean-frontend`

## 回滚策略

若业务确认需要回退：
- 代码层回退到上一版默认值
- 数据层通过新 patch 或数据库备份恢复原配置

注意：由于本次要求“强制统一现有配置”，一旦数据 patch 执行，精确恢复每条记录原来的个性化篮子只能依赖备份或审计记录，不能靠通用 SQL 自动还原。
