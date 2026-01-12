# LeanQuantHub

本项目用于量化交易学习与研究，不构成任何投资建议。

LeanQuantHub 是一套本地化多用户量化平台：前端参考 QuantConnect 风格，后端基于 Lean Runner 的任务执行模型，支持主题管理、数据管理、回测与报告归档。

## 目录结构
- `backend/`：FastAPI + MySQL 元数据服务
- `frontend/`：React + Vite 前端
- `algorithms/`：Lean 算法脚本
- `ml/`：ML 评分与推理工具
- `configs/`：Lean 配置模板与主题权重
- `deploy/`：systemd 与部署脚本

## 本地开发

### 后端
```bash
cd /app/stocklean
cp backend/.env.example backend/.env
# 填写 DB_* / LEAN_* / ML_* 等环境变量
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r ml/requirements.txt
cd backend
../.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8021
```

### 前端
```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

默认前端：http://localhost:5173  
默认后端：http://localhost:8021

## 服务器部署（systemd）
```bash
cd frontend
npm install
npm run build

# 部署 systemd
cp deploy/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user restart stocklean-backend stocklean-frontend
```

默认前端：http://<host>:8081  
默认后端：http://<host>:8021

## Lean Runner 配置
在后端 `.env` 中设置：
- `LEAN_LAUNCHER_PATH`：Lean Launcher csproj 路径
- `LEAN_CONFIG_TEMPLATE`：Lean 配置模板 JSON
- `LEAN_ALGORITHM_PATH`：算法脚本路径
- `LEAN_DATA_FOLDER`：Lean 数据目录
- `LEAN_PYTHON_VENV`：**统一 Python 3.11 venv（推荐 `/app/stocklean/.venv`）**
- `PYTHON_DLL`：Python 3.11 的 `libpython` 路径（推荐 `/app/stocklean/.venv/lib/libpython3.11.so`）
- `DOTNET_PATH` / `DOTNET_ROOT`

## 数据与生命周期覆盖说明
回测使用 `data_root/universe/alpha_symbol_life.csv` 作为股票生命周期来源（IPO/退市日期）。  
当 Alpha 的 `delistingDate` 与价格历史冲突时，可以使用覆盖文件修正：
- 覆盖文件默认路径：`data_root/universe/symbol_life_override.csv`
- 覆盖文件格式：`symbol,ipoDate,delistingDate,source,note`
- 覆盖优先级：`symbol_life_override.csv` **高于** `alpha_symbol_life.csv`
- 可通过权重配置 `symbol_life_override_path` 指定自定义路径

## 数据源文档
- 统一目录：`docs/data_sources/`
- 已整理数据源：
  - Alpha Vantage：`docs/data_sources/alpha.md`

## TODOLIST 规范
- 统一目录：`docs/todolists/`
- 文件命名：`<主题>TODO.md` / `<主题>TestTODO.md`
- 项目根目录不再存放 TODO 文件

## 报告归档
- 回测报告：`docs/reports/backtests/`
- 训练对比与曲线：`docs/reports/ml/`

## ML 评分（统一 venv）
- Lean 与 ML 统一使用 Python 3.11（兼容 Python.NET）
- 在 `.env` 中配置：
  - `ML_PYTHON_PATH=/app/stocklean/.venv/bin/python`

## 安全与提交
- 禁止提交 `.env`、数据目录、日志与构建产物
- 使用 `.env.example` 提供模板，不暴露真实密钥或内网地址
