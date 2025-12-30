# Repository Guidelines

## 项目结构
- ackend/：FastAPI + MySQL 元数据与任务触发
- rontend/：React + Vite 前端
- scripts/：数据构建与回测管线
- deploy/：部署与数据库脚本

## 开发命令
- 后端启动：uvicorn app.main:app --host 0.0.0.0 --port 8021
- 前端启动：
pm run dev
- 前端构建：
pm run build

## 编码与命名
- Python：保持类型注解与现有风格一致，避免引入新框架
- 前端：遵循现有 React 组件与 CSS 命名规则
- 文件命名：小写+短横线（如 schema.sql、	heme_keywords.json）

## 测试与验证
- 目前无自动化测试；提交前请至少验证：
  - 前端页面可访问（/projects）
  - 后端 openapi.json 可用
  - 数据刷新与主题回测能触发

## 提交规范
- 当前无强制规范，建议使用 eat: / ix: / chore: 前缀
- 提交前确认 .env、数据目录与构建产物未被纳入

## 机密与安全
- 禁止提交 .env、API Key、数据库口令
- 如需共享配置，请更新 .env.example
