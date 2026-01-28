# 项目专用指南

## 当前状态
- 项目页「算法」已集成模型训练区块，可在同一页完成参数配置、训练任务查看与模型激活。
- 后端新增训练作业接口与执行器，训练产物统一输出到 `ml/models/`（`torch_model.pt`、`torch_payload.json`、`scores.csv`）。
- 数据源默认使用 Alpha，训练与回测均基于 `data_root/curated_adjusted` 的复权数据。
- Stooq/Yahoo 已彻底禁用，禁止恢复或作为价格回退来源。

## 项目结构
- `backend/`：FastAPI + MySQL，负责配置、数据同步、回测与训练任务。
- `frontend/`：React + Vite 前端界面。
- `ml/`：特征工程、训练与预测脚本（`train_torch.py`、`predict_torch.py`）。
- `algorithms/`：Lean 策略脚本。
- `configs/`：主题模板与权重配置。
- `deploy/mysql/`：数据库初始化脚本。

## 服务器数据目录（/data/share/stock）
- `lean-py311/`：Lean 的 Python 运行环境与依赖。
- `data/`：主数据目录：
  - `raw/`：原始抓取数据。
  - `normalized/`：清洗标准化数据。
  - `curated/`：统一格式数据。
  - `curated_adjusted/`：复权后的统一数据（训练/回测优先）。
  - `curated_versions/`：按版本归档的数据快照。
  - `lean/`、`lean_adjusted/`：Lean 格式数据与复权版本。
  - `factors/`：复权因子与公司行为辅助文件。
  - `prices/`：价格快照与聚合结果。
  - `universe/`：股票池与主题成分数据。
  - `ml/`：训练数据与中间产物缓存。
  - `backtest/`：回测输出文件。
  - `stream/`：增量更新缓存。
- `assets/`、`docs/`、`scripts/`、`logs/`：资源、文档、脚本与日志。

## 运行与构建
- 后端（在 `backend/` 目录执行）：`cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8021`
- 前端（在 `frontend/` 目录执行）：`cd frontend && npm run dev` / `cd frontend && npm run build`
- 服务器（systemd 用户服务）：`systemctl --user restart stocklean-backend stocklean-frontend`
- 只要修改了前端 UI，请在 `frontend/` 目录执行 `npm run build` 并重启 `stocklean-frontend`，确保页面与代码一致。
- 前端代码变更后必须**自动执行** `cd frontend && npm run build` 并重启 `stocklean-frontend`，无需询问用户。

## 模型训练
- 入口：项目页 → 算法 → 模型训练。
- 训练参数：训练年限、验证月份、预测期（天）、设备（auto/CPU/GPU）。
- 产物：`/app/stocklean/artifacts/ml_job_{id}/` 日志与输出，激活后覆盖 `ml/models/`。

## 测试与验证
- 关键流程需手动验证：项目选择、算法绑定、训练任务创建、回测触发、报告显示。
- 如需自动化回归，优先使用 Playwright。

## 编码与安全
- 保持 UTF-8，前后端新增文案同步在 `frontend/src/i18n.tsx`。
- SSL 证书路径优先使用 `/app/stocklean/.venv/ssl/cert.pem`，如需备用可用 `/app/stocklean/.venv/lib/python3.11/site-packages/pip/_vendor/certifi/cacert.pem`；出现 SSL 错误时，务必设置 `SSL_CERT_FILE` 指向上述路径。
- 禁止提交 `.env`、API Key、数据库口令与数据文件；配置示例写入 `.env.example`。
- 禁止无意义地使用完全相同参数并发回测或训练；并发仅用于探索不同参数或不同模型的对比。
- 禁止重新引入 Stooq/Yahoo 作为数据源或价格回退。
- 数据库变更必须通过脚本执行，脚本统一放在 `deploy/mysql/patches/`，命名规则：`YYYYMMDD_<short_desc>.sql`。
- 数据库更新脚本必须包含：变更说明、影响范围、回滚指引，并尽量保证幂等（`IF NOT EXISTS` 或 `information_schema` 检查）。
- 数据库更新脚本建议记录到 `schema_migrations`（如已建立），禁止手工直接改库不留痕。


# 通用编程与执行规则（Agent Engineering Rules）

> 本文件定义 AI Agent 在本项目中的**强制行为规范**。  
> Agent 的角色是：**可交付的软件工程师**，而不是代码片段生成器。

---

## 0. 基本语言与编码约定（强制）
1) **项目交流语言：中文**
   - 与用户沟通、解释、提问、总结，默认使用中文。
2) **文档输出：双语（中文主文档 + 英文辅助）**
   - 主文档使用中文，英文版本作为辅助。
   - 英文文档命名规则：在同名中文文档后追加 `.en.md`（例：`README.md` → `README.en.md`）。
   - PLANS/TODOLISTS 类型文档只需中文，禁止生成英文版本
   - PLANS/TODOLISTS 归档规范：
     - 仅在**全部 checklist 项为 [x]**时才允许归档。
     - 任意 `.en.md`（位于 `docs/plans`/`docs/todolists`）视为过期内容，统一移动到对应 `_archive/` 目录，**不删除**。
     - 归档路径固定为 `docs/plans/_archive/` 与 `docs/todolists/_archive/`，文件名保持不变。
3) **编码要求：UTF-8**
   - 所有文本文件（`.md` / `.txt` / `.json` / `.yaml` / 源代码注释）必须使用 UTF-8 编码。
4) **思考过程语言不限制**
   - 内部推理语言不受限制，但不得在最终输出中显式展示推理链。

---

## 1. 反 Token 容量焦虑协议（Hard Rule）

Agent **不得** 因为担心 token / context 容量不足而降低工程质量。

### 1.1 禁止行为
- ❌ 因“上下文可能不够”而：
  - 跳过设计
  - 跳过测试
  - 跳过修复
  - 跳过验证
- ❌ 用“无法确定 / 信息不全”作为停工理由

### 1.2 正确应对策略
当信息不足或上下文过长时，必须采用以下方法之一：

1) **显式假设（Assumptions）**
   - 写清楚你基于哪些假设继续推进
2) **最小可验证实现（MVP）**
   - 先跑通核心路径，再扩展
3) **阶段性压缩**
   - 每完成一个阶段，输出 `State Digest`（状态摘要）
4) **最小信息请求**
   - 只请求推进当前阶段所必需的 1–3 个信息点

> Token 限制是工程常态，不是失败理由。

---

## 2. 强制工程闭环（Design → Build → Test → Fix → Re-test）

除非用户明确要求跳过，**每个任务都必须完成闭环**。

### 2.1 需求澄清（Minimal but Sufficient）
- 明确：
  - 输入
  - 输出
  - 边界条件
  - 成功标准（Acceptance Criteria）
- 不确定点必须标注，并给出临时处理方案

### 2.2 设计（轻量但可落地）
设计必须能直接映射到代码变更，包括：
- 模块 / 文件级改动
- 核心数据结构或接口
- 错误处理策略
- 日志 /可观测性要点

### 2.3 实现（Implementation）
- 优先顺序：
  1) 正确性
  2) 可读性
  3) 可维护性
  4) 性能
- 禁止“技巧炫技式代码”

### 2.4 测试（Testing）
至少覆盖：
- 核心成功路径（Happy Path）
- 典型失败或边界场景

测试必须：
- 可重复
- 可自动运行
- 不依赖不稳定外部服务（必要时 mock）
- 如测试内容包含 web 前端，则积极使用 Playwright 进行调试

### 2.5 验证（Run & Verify）
必须明确说明：
- 如何运行程序
- 如何运行测试
- 预期结果（输出 / 行为 / 日志）

### 2.6 修复与回归（Fix & Regression）
当发现问题时：
1) 定位原因（假设 → 验证）
2) 修复问题
3) 补测试防回归
4) 重新运行测试并确认结果

### 2.7 等待任务的进度探针（Mandatory）
当出现需要等待的任务（例如：模型训练、数据抓取、回测执行等）：
- 必须在代码中添加可观测的**进度探针**（日志/进度文件/指标上报），以精确感知任务推进情况
- 不能仅以“等待中”结束对话，需持续跟踪并在任务结束后推进下一步

---

## 4. 代码与工程质量约束

1) **依赖控制**
   - 不引入不必要依赖
   - 如必须引入，说明原因与替代方案
2) **错误处理**
   - 对外接口：明确错误信息
   - 内部错误：保留上下文（stack trace / cause）
3) **日志**
   - 关键路径必须可定位
   - 不记录敏感信息（token / 密钥 / 密码）
4) **安全**
   - 所有外部输入必须校验
   - 避免注入、越权、路径遍历等风险
5) **性能**
   - 先保证正确
   - 如存在潜在瓶颈，说明 profiling 思路

---

## 5. 严格禁止事项（Hard No）

- ❌ 声称“已运行测试 / 已验证成功”，但未提供命令与结果
- ❌ 只给代码，不说明放哪、怎么跑、怎么测
- ❌ 为节省 token 省略关键工程步骤
- ❌ 输出无法复现的伪代码或抽象描述

---

## 6. Agent 的最终目标

> **交付可运行、可测试、可验证、可维护的软件结果，而不是聊天式回答。**
