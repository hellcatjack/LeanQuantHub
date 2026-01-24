# 信息泄露审计实施计划

> **给 Claude：** 必须子技能：使用 `superpowers:executing-plans` 按任务逐步执行。

**目标：** 系统化扫描当前工作区（含被忽略文件）的潜在敏感信息，产出可复核的审计结论与整改建议。

**架构：** 以“范围界定 → 现状扫描 → 历史排查 → 结果归档/建议”的顺序执行；所有输出仅记录文件路径与摘要，不回显敏感值。

**技术栈：** bash、rg(ripgrep)、git、awk/sed（必要时）

### 任务 1：明确审计范围与排除目录

**文件：**
- 记录：`/tmp/stocklean_audit_files.txt`

**步骤 1：列出文件清单（排除噪声目录）**

命令：
```bash
rg --files \
  -g '!*node_modules/*' \
  -g '!.venv/*' \
  -g '!frontend/dist/*' \
  -g '!.git/*' \
  > /tmp/stocklean_audit_files.txt
```

预期：生成文件清单用于后续扫描。

**步骤 2：统计文件数量**

命令：
```bash
wc -l /tmp/stocklean_audit_files.txt
```

预期：输出文件总数（记录在审计结论中）。

### 任务 2：扫描当前工作区（已跟踪文件）敏感信息

**文件：**
- 读取：`/tmp/stocklean_audit_files.txt`
- 记录：`/tmp/stocklean_audit_hits_tracked.txt`

**步骤 1：在已跟踪文件中搜索常见敏感模式**

命令：
```bash
rg -n --fixed-strings \
  -e 'API_KEY' -e 'SECRET' -e 'TOKEN' -e 'PASSWORD' -e 'ACCESS_KEY' \
  $(cat /tmp/stocklean_audit_files.txt) \
  > /tmp/stocklean_audit_hits_tracked.txt
```

预期：生成匹配结果（后续仅保留“文件路径 + 行号 + 关键词”，不回显值）。

**步骤 2：筛除明显非敏感文案（占位符/示例）**

命令：
```bash
rg -v -n --fixed-strings \
  -e 'example' -e 'placeholder' -e 'CHANGEME' -e 'YOUR_' -e '***' \
  /tmp/stocklean_audit_hits_tracked.txt \
  > /tmp/stocklean_audit_hits_tracked_filtered.txt
```

预期：得到更精简的可疑清单。

### 任务 3：扫描被忽略文件（如 .env）

**文件：**
- 记录：`/tmp/stocklean_audit_hits_ignored.txt`

**步骤 1：对忽略文件进行受控扫描（仅记录路径+关键词）**

命令：
```bash
rg -n --no-ignore --fixed-strings \
  -e 'API_KEY' -e 'SECRET' -e 'TOKEN' -e 'PASSWORD' -e 'ACCESS_KEY' \
  /app/stocklean \
  > /tmp/stocklean_audit_hits_ignored.txt
```

预期：生成包含忽略文件的匹配结果。后续输出严格脱敏，仅报告文件位置与关键词类别。

### 任务 4：检查 Git 历史（可选但推荐）

**文件：**
- 记录：`/tmp/stocklean_audit_hits_gitlog.txt`

**步骤 1：按关键词检索历史提交差异**

命令：
```bash
git log --all -p -S 'API_KEY' -S 'SECRET' -S 'TOKEN' -S 'PASSWORD' \
  > /tmp/stocklean_audit_hits_gitlog.txt
```

预期：若历史包含敏感字样，进行人工确认（不回显值）。

### 任务 5：汇总审计结论与整改建议

**文件：**
- 记录：`docs/todolists/IBAutoTradeTODO.md`（若涉及整改事项，更新 TODO 状态）

**步骤 1：整理发现列表与风险级别**
- 仅输出文件路径、关键词类型与风险等级。

**步骤 2：提出整改建议**
- 涉及敏感文件：建议移动/脱敏/旋转密钥。
- 涉及样例文件：建议统一占位符。

**步骤 3：复核**
- 整改后复跑任务 2/3，确认无新增匹配。
