# 贡献指南

感谢参与 LeanQuantHub。请遵循以下规范，确保代码与文档一致、可复现、可审计。

## 分支与提交
1. 分支命名：`feature/<topic>` 或 `fix/<topic>`
2. 提交信息建议使用：`feat:` / `fix:` / `docs:` / `chore:`
3. 提交前确认 `.env`、数据目录与构建产物未被加入版本库

## 本地验证
- 前端：`npm run dev`，确保核心页面可访问
- 后端：`uvicorn app.main:app --host 0.0.0.0 --port 8021`
- 回测：在 UI 或调用 `/api/backtests` 触发一次回测，确认状态与报告生成

## 文档更新
涉及环境变量、部署流程、算法参数的改动，请同步更新：
- `README.md`
- `backend/.env.example`
- `frontend/.env.example`
