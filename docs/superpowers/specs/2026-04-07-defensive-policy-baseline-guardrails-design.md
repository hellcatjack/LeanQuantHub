# 防御资产默认基线与研究模板护栏设计

## 背景
2026-04-07 的防御资产矩阵实验已经给出清晰结论：
- 默认防御主标的：`SGOV`
- 默认防御篮子：`SGOV,VGSH`
- 默认 benchmark：`SPY`
- `SGOV,VGSH,IEF` 仅保留为保守候选
- `GLD/USO/BNO/TLT/QQQ/SOXX` 不进入默认路径，只保留研究用途

当前问题不在策略结论，而在工程落地：
- 默认值入口分散在多个路由、配置文件和脚本常量中
- 研究脚本和默认脚本没有统一的策略基线来源
- 结论虽然已有报告，但还没有固化成程序化约束

## 目标
把防御资产实验结论固化到系统中，确保：
1. 默认路径稳定使用 `SGOV / SGOV,VGSH / SPY`
2. 研究路径仍允许显式实验，不被默认逻辑误伤
3. 后续开发不会因为脚本漂移或局部常量而悄悄偏离默认基线

## 非目标
- 不修改前端 UI
- 不新增数据库结构
- 不禁止显式研究型参数
- 不改变当前回测/交易策略语义

## 设计原则
1. 默认路径和研究路径分层
2. 默认值集中定义，避免散落常量
3. 研究模板显式列出允许的扩展方向，避免临时字符串拼接
4. 对默认值做强归一化，对研究值做显式 opt-in

## 方案

### 1. 新增统一策略基线模块
新增 `backend/app/services/defensive_policy.py`，集中提供：
- 默认防御主标的
- 默认防御篮子
- 默认 benchmark
- 保守候选篮子
- 研究型扩展白名单
- 研究模板矩阵文件路径

模块职责：
- 作为后端默认归一化的单一来源
- 为脚本和测试提供统一常量接口
- 明确哪些值属于默认路径，哪些属于研究路径

### 2. 默认值归一化统一收口
更新：
- `backend/app/routes/projects.py`
- `backend/app/routes/algorithms.py`

行为：
- 项目配置默认归一化时，统一回到 `SGOV / SGOV,VGSH / SPY`
- 算法版本默认归一化时，统一回到 `SGOV / SGOV,VGSH`
- 保留显式研究参数输入能力，但默认辅助函数和默认配置加载都从基线模块取值

### 3. 新增研究模板矩阵文件
新增 `configs/research_defensive_matrix.json`，定义：
- default：`SGOV,VGSH`
- conservative：`SGOV,VGSH,IEF`
- hedge_opt_in：`GLD`
- commodity_observation：`USO,BNO`
- benchmark_sensitivity：`QQQ,SOXX`

用途：
- 让研究脚本、后续实验入口和测试共享同一套研究范围定义
- 避免在脚本中重复硬编码实验篮子

### 4. 同步默认实验脚本
更新：
- `scripts/run_project18_train120_opt.py`
- `scripts/run_project18_train120_opt_v2.py`
- `scripts/run_cagr_opt.py`
- `scripts/run_train_model_opt.py`

行为：
- 默认路径使用统一基线模块或与之对齐的常量
- 研究脚本读取研究模板矩阵文件或至少保持与其一致
- 不再让实验入口的默认值和系统默认值出现分叉

## 测试策略

### 后端单测
新增/更新测试覆盖：
- 默认基线常量是否正确暴露
- 项目配置默认归一化是否强制回到 `SGOV,VGSH / SGOV / SPY`
- 算法版本默认归一化是否强制回到 `SGOV,VGSH / SGOV`
- 研究模板文件是否包含默认组、保守组、研究扩展组
- 研究扩展白名单是否包含 `GLD/USO/BNO/TLT/QQQ/SOXX`

### 脚本测试
更新现有 payload 测试：
- `run_project18_train120_opt.py`
- `run_project18_train120_opt_v2.py`
- `run_train_model_opt.py`
- 如有必要，为研究模板矩阵增加独立测试

## 风险与处理

### 风险 1：把研究能力一并锁死
处理：
- 默认归一化只作用于默认路径
- 研究模板单独文件定义，不把研究候选混进默认值

### 风险 2：脚本与后端再次漂移
处理：
- 所有测试都直接对齐统一基线模块和研究模板
- 后续若改默认值，必须同时修改基线模块和测试

## 验收标准
1. 默认值入口不再散落为互相独立的字符串常量
2. `projects.py`、`algorithms.py`、`default_algorithm.json`、默认实验脚本全部对齐到 `SGOV / SGOV,VGSH / SPY`
3. 研究模板文件明确列出保守候选、黄金扩展、商品观察、benchmark 敏感度四类范围
4. 新增和更新测试全部通过
5. 后续开发可以直接复用该基线，不再依赖人工阅读实验报告理解默认路径
