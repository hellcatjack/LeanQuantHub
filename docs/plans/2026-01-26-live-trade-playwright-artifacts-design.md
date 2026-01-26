# 实盘交易 Playwright 异常取证设计

## 目标
在实盘交易（Paper）全流程 Playwright 回归中，当出现 PreTrade 单实例阻塞或关键断言失败时，自动保存证据（截图 + 页面 HTML + 控制台日志），便于定位问题。

## 范围
- 仅调整 `frontend/tests/live-trade-flow.spec.ts`。
- 不改后端/接口，不增加运行时依赖。
- 仅在触发条件时写入附件；正常成功路径不产出。

## 触发条件
1. **PreTrade 被单实例锁定**：提示包含“已有运行中的”或“单实例”。
2. **关键断言失败**：
   - 决策快照日期仍为 “-”。
   - 实盘页快照状态/日期缺失。
   - 账户金额断言不在 30000–32000。

## 产物与格式
- **截图**：全页 `image/png`。
- **HTML**：`page.content()` 结果，`text/html`。
- **控制台日志**：捕获 `page.on("console")` 输出，包含时间戳与类型，`text/plain`。
- 附件写入 Playwright `testInfo.attach()`，标签统一为 `playwright-artifacts/<label>/<kind>`。

## 数据流
1. 测试启动时注册 console 监听器，保存到内存数组。
2. 命中触发条件时调用 `attachArtifacts(label, page, testInfo, consoleLines)`：
   - 依次写入 screenshot/html/console。
3. 断言失败时先写附件，再抛出错误，保持用例失败。

## 验收标准
- 触发 PreTrade 阻塞时生成 3 类附件。
- 断言失败时生成 3 类附件并失败退出。
- 成功路径不生成附件。

