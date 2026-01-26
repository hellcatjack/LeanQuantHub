# Playwright 异常取证 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在实盘交易 Playwright 回归中，PreTrade 单实例阻塞或关键断言失败时自动附加截图+HTML+控制台日志。

**Architecture:** 在 `live-trade-flow.spec.ts` 中新增本地 helper（attachArtifacts）与 console 监听器；在指定异常分支调用 helper 并 rethrow，成功路径不写附件。

**Tech Stack:** Playwright、TypeScript、Vite 前端测试。

---

### Task 1: 为异常取证添加失败测试（TDD）

**Files:**
- Modify: `frontend/tests/live-trade-flow.spec.ts`

**Step 1: 写失败测试**

在文件顶部新增一个小测试 `paper flow - attach artifacts helper`：
- 使用 `page.goto("/live-trade")`
- 调用 `attachArtifacts("smoke", page, testInfo, ["log"])`
- 断言 `testInfo.attachments.length` 增加

> 此时 `attachArtifacts` 尚未实现，测试应失败（ReferenceError）。

**Step 2: 运行测试确认失败**

Run:
```bash
cd frontend
PLAYWRIGHT_LIVE_TRADE=1 E2E_BASE_URL="http://192.168.1.31:8081" npx playwright test tests/live-trade-flow.spec.ts -g "attach artifacts helper" --reporter=line
```
Expected: FAIL，提示 `attachArtifacts is not defined`。

---

### Task 2: 实现 attachArtifacts 与 console 捕获

**Files:**
- Modify: `frontend/tests/live-trade-flow.spec.ts`

**Step 1: 实现 helper**

在文件中新增函数：
```ts
const attachArtifacts = async (
  label: string,
  page: Page,
  testInfo: TestInfo,
  consoleLines: string[]
) => {
  const prefix = `playwright-artifacts/${label}`;
  await testInfo.attach(`${prefix}/screenshot`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
  await testInfo.attach(`${prefix}/html`, {
    body: await page.content(),
    contentType: "text/html",
  });
  await testInfo.attach(`${prefix}/console`, {
    body: consoleLines.join("\n"),
    contentType: "text/plain",
  });
};
```

**Step 2: 注册 console 监听器**

在测试开始处：
```ts
const consoleLines: string[] = [];
page.on("console", (msg) => {
  consoleLines.push(`[${new Date().toISOString()}] ${msg.type()} ${msg.text()}`);
});
```

**Step 3: 运行测试确认通过**

Run:
```bash
cd frontend
PLAYWRIGHT_LIVE_TRADE=1 E2E_BASE_URL="http://192.168.1.31:8081" npx playwright test tests/live-trade-flow.spec.ts -g "attach artifacts helper" --reporter=line
```
Expected: PASS，并生成附件。

**Step 4: 提交**

```bash
git add frontend/tests/live-trade-flow.spec.ts
git commit -m "test: add playwright artifact helper"
```

---

### Task 3: 在 PreTrade 阻塞与断言失败时附加证据

**Files:**
- Modify: `frontend/tests/live-trade-flow.spec.ts`

**Step 1: PreTrade 阻塞分支附加**

在检测到 `已有运行中的/单实例` 后，调用：
```ts
await attachArtifacts("pretrade-blocked", page, testInfo, consoleLines);
```

**Step 2: 关键断言失败时附加**

用 `try/catch` 包裹以下断言：
- 决策快照日期不为 “-”
- 实盘快照状态与日期不为空
- NetLiquidation 范围断言

在 `catch` 中调用 `attachArtifacts("decision-empty" | "snapshot-missing" | "account-mismatch", ...)`，随后 `throw` 让测试失败。

**Step 3: 运行全流程测试**

Run:
```bash
cd frontend
PLAYWRIGHT_LIVE_TRADE=1 E2E_BASE_URL="http://192.168.1.31:8081" npx playwright test tests/live-trade-flow.spec.ts --reporter=line
```
Expected: PASS（成功路径无附件），阻塞/失败时生成附件。

**Step 4: 提交**

```bash
git add frontend/tests/live-trade-flow.spec.ts
git commit -m "test: attach artifacts on pretrade blocked"
```

---

### Task 4: 前端构建与回归

**Files:**
- Modify: `frontend/` 构建产物

**Step 1: 构建**

```bash
cd frontend
npm run build
```

**Step 2: 重启前端服务**

```bash
systemctl --user restart stocklean-frontend
```

**Step 3: 生产 URL 回归**

```bash
cd frontend
PLAYWRIGHT_LIVE_TRADE=1 E2E_BASE_URL="http://192.168.1.31:8081" npx playwright test tests/live-trade-flow.spec.ts --reporter=line
```
Expected: PASS。

**Step 4: 提交**

```bash
git add -A
git commit -m "chore: rebuild frontend after playwright artifacts"
```

