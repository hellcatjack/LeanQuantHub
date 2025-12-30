# 贡献指南

## 提交流程
1. 创建分支：eature/<name> 或 ix/<name>
2. 保持提交信息清晰简短（建议 eat: / ix: / chore:）
3. 提交前请确认 .env、数据目录、构建产物未被加入

## 本地验证
- 前端：
pm run dev，确认 /projects 可访问
- 后端：uvicorn app.main:app --host 0.0.0.0 --port 8021
- 数据刷新与回测流程能正常触发

## 文档更新
- 配置项调整需同步更新 README.md 与 .env.example
- 新增脚本请在 scripts/ 中说明用途
