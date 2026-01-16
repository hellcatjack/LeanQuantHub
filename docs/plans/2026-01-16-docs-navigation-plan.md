# Docs Navigation Index Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为文档新增统一导航入口与索引文件，方便定位数据源、报告与 TODO 列表。

**Architecture:** 仅新增 Markdown 索引，不移动现有文档；根 README 指向 docs/README 总览入口，各子目录提供独立索引。

**Tech Stack:** Markdown

### Task 1: 新增 docs/README.md（文档总览）

**Files:**
- Create: `docs/README.md`

**Step 1: 编写 docs/README.md 内容**
```markdown
# 文档总览

...（包含数据源、TODO、报告、运维/规范入口链接）
```

**Step 2: 校验文件存在**
Run: `test -f docs/README.md`
Expected: exit code 0

### Task 2: 新增 docs/data_sources/README.md（数据源索引）

**Files:**
- Create: `docs/data_sources/README.md`

**Step 1: 编写数据源索引**
```markdown
# 数据源索引
- Alpha Vantage: docs/data_sources/alpha.md
```

**Step 2: 校验索引文件存在**
Run: `test -f docs/data_sources/README.md`
Expected: exit code 0

### Task 3: 新增 docs/reports/README.md（报告索引）

**Files:**
- Create: `docs/reports/README.md`

**Step 1: 编写报告索引**
```markdown
# 报告索引
- 回测报告：docs/reports/backtests/
- 训练曲线：docs/reports/ml/
```

**Step 2: 校验索引文件存在**
Run: `test -f docs/reports/README.md`
Expected: exit code 0

### Task 4: 更新根 README.md 文档导航入口

**Files:**
- Modify: `README.md`

**Step 1: 新增“文档导航”区块，指向 docs/README.md**
```markdown
## 文档导航
- 文档总览：docs/README.md
```

**Step 2: 验证 README 中包含新增入口**
Run: `rg -n "文档导航|docs/README.md" README.md`
Expected: 至少匹配 1 行

### Task 5: 更新 docs/todolists/README.md 增加总览入口提示

**Files:**
- Modify: `docs/todolists/README.md`

**Step 1: 在开头增加“文档总览入口”提示**
```markdown
> 文档总览：docs/README.md
```

**Step 2: 验证变更存在**
Run: `rg -n "docs/README.md" docs/todolists/README.md`
Expected: 至少匹配 1 行

### Task 6: 统一校验文档引用

**Files:**
- Verify: `README.md`, `docs/README.md`, `docs/data_sources/README.md`, `docs/reports/README.md`, `docs/todolists/README.md`

**Step 1: 校验所有索引文件被引用**
Run: `rg -n "docs/README.md|docs/data_sources/README.md|docs/reports/README.md" README.md docs/README.md docs/todolists/README.md`
Expected: 每个路径至少匹配一次

### Task 7: 提交变更

**Step 1: 查看变更列表**
Run: `git status -sb`
Expected: 列出新增/修改的 Markdown 文件

**Step 2: 提交**
```bash
git add README.md docs/README.md docs/data_sources/README.md docs/reports/README.md docs/todolists/README.md
git commit -m "docs: add documentation index"
```

