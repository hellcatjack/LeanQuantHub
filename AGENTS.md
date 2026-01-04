# Repository Guidelines

## 当前状态
- 项目页「算法」已集成模型训练区块，可在同一页完成参数配置、训练任务查看与模型激活。
- 后端新增训练作业接口与执行器，训练产物统一输出到 `ml/models/`（`torch_model.pt`、`torch_payload.json`、`scores.csv`）。
- 数据源默认使用 Alpha，训练与回测均基于 `data_root/curated_adjusted` 的复权数据。

## 项目结构
- `backend/`：FastAPI + MySQL，负责配置、数据同步、回测与训练任务。
- `frontend/`：React + Vite 前端界面。
- `ml/`：特征工程、训练与预测脚本（`train_torch.py`、`predict_torch.py`）。
- `algorithms/`：Lean 策略脚本。
- `configs/`：主题模板与权重配置。
- `deploy/mysql/`：数据库初始化脚本。

## 运行与构建
- 后端：`uvicorn app.main:app --host 0.0.0.0 --port 8021`
- 前端：`npm run dev` / `npm run build`
- 服务器（systemd 用户服务）：`systemctl --user restart stocklean-backend stocklean-frontend`

## 模型训练
- 入口：项目页 → 算法 → 模型训练。
- 训练参数：训练年限、验证月份、预测期（天）、设备（auto/CPU/GPU）。
- 产物：`/app/stocklean/artifacts/ml_job_{id}/` 日志与输出，激活后覆盖 `ml/models/`。

## 测试与验证
- 关键流程需手动验证：项目选择、算法绑定、训练任务创建、回测触发、报告显示。
- 如需自动化回归，优先使用 Playwright。

## 编码与安全
- 保持 UTF-8，前后端新增文案同步在 `frontend/src/i18n.tsx`。
- 禁止提交 `.env`、API Key、数据库口令与数据文件；配置示例写入 `.env.example`。
