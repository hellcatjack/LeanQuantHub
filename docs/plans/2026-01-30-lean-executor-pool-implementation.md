# Lean 执行器常驻池实施计划

> 目标：每个模式 10 个常驻执行器池，Leader 独占 Bridge 输出，Worker 只下单，<1s 下单延迟。

## Task 1：新增数据表与配置

**DB Patch（必须）**
- 新增 `lean_executor_pool` 与 `lean_executor_events` 表。
- 记录变更说明、影响范围、回滚指引，幂等。

**配置项（app.core.config）**
- `lean_pool_size`（默认 10）
- `lean_pool_max_active_connections`（默认 10）
- `lean_pool_heartbeat_ttl_seconds`（默认 20）
- `lean_pool_leader_restart_limit`（默认 3）

**测试**
- `pytest tests/test_lean_pool_settings.py -v`

## Task 2：池管理器服务

**新增模块**
- `backend/app/services/lean_executor_pool.py`

**能力**
- 启动池（paper/live）
- Leader 选举/切换
- 心跳与健康扫描（5s）
- 重启与补位

**测试**
- 单元测试：健康状态判定、Leader 切换逻辑

## Task 3：订单路由改造

**改造点**
- `trade_direct_order` 下单改为选择 healthy Worker
- Worker 禁止订阅行情与历史

**测试**
- 回归：直接下单路径仍可用

## Task 4：Bridge 输出与读写隔离

**改造点**
- Leader 输出写入 `lean_bridge/`
- Worker 输出写入独立目录
- 读桥接数据只读 Leader 目录

**测试**
- Bridge 目录一致性检测

## Task 5：API 接口

**新增接口**
- `GET /api/lean/pool/status`
- `POST /api/lean/pool/restart`
- `POST /api/lean/pool/leader/switch`
- `POST /api/lean/pool/reset`

**测试**
- 接口返回字段完整性
- 强制 reset 需 token

## Task 6：前端 Bridge Pool 子页面

**前端改动**
- 新增页面展示池状态、事件流
- 操作按钮与确认弹窗
- i18n 文案同步

**测试**
- Playwright 覆盖：展示、过滤、按钮可见性

## Task 7：监控与审计

**改造点**
- 事件写入 `lean_executor_events`
- 关键异常写入 audit_log

**测试**
- 事件记录可检索

## 验证清单
- 下单延迟稳定 <1s
- Leader 异常自动切换
- Worker 异常不影响其他实例
- 连接数与请求速率不触碰 IB 限制

